import json
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from chatapp import models


class AuthAndUserTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='alice',
            email='alice@example.com',
            password='Password123!',
            first_name='Alice',
            last_name='Smith',
        )

    def test_user_registration(self):
        response = self.client.post('/auth/register/', {
            'username': 'bob',
            'email': 'bob@example.com',
            'password': 'BobPassword123!',
            'first_name': 'Bob',
            'last_name': 'Jones',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('tokens', response.data)
        self.assertIn('access', response.data['tokens'])
        self.assertIn('refresh', response.data['tokens'])
        self.assertTrue(User.objects.filter(username='bob').exists())
        self.assertTrue(models.UserStatus.objects.filter(user__username='bob').exists())

    def test_token_endpoints_and_typo_fix(self):
        # 1. Obtain token
        obtain_res = self.client.post('/token/', {
            'username': 'alice',
            'password': 'Password123!',
        }, format='json')
        self.assertEqual(obtain_res.status_code, status.HTTP_200_OK)
        refresh_token = obtain_res.data['refresh']

        # 2. Refresh via correct URL
        refresh_res = self.client.post('/token/refresh/', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_res.data)

        # 3. Refresh via legacy typo URL
        legacy_res = self.client.post('/token/refrash', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(legacy_res.status_code, status.HTTP_200_OK)
        self.assertIn('access', legacy_res.data)

    def test_profile_and_user_list(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

        # Profile
        res = self.client.get('/users/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['username'], 'alice')

        # Create another user and search
        User.objects.create_user(username='charlie', password='pwd')
        list_res = self.client.get('/users/?search=char')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertTrue(any(u['username'] == 'charlie' for u in list_res.data))


class MessageAndSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user(username='alice', password='pwd')
        self.bob = User.objects.create_user(username='bob', password='pwd')
        self.room = models.ChatRoom.objects.create(room_name='room1', room_type='private')
        self.room.members.add(self.alice, self.bob)

    def test_message_encryption_and_decrypted_serialization(self):
        # Create message
        msg = models.Message.objects.create(
            chatroom=self.room,
            sender=self.alice,
            content='Secret Project Plan 2026',
        )
        # Content in database is Fernet encrypted
        raw_msg = models.Message.objects.raw("SELECT id, content FROM chatapp_message WHERE id = %s", [msg.id])[0]
        self.assertNotEqual(raw_msg.content, 'Secret Project Plan 2026')
        self.assertTrue(raw_msg.content.startswith('gAAAAA'))

        # Serializer returns decrypted content
        refresh = RefreshToken.for_user(self.alice)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        res = self.client.get(f'/chatrooms/{self.room.id}/messages/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data['results'] if isinstance(res.data, dict) and 'results' in res.data else res.data
        self.assertEqual(items[0]['content'], 'Secret Project Plan 2026')

    def test_message_search_with_encrypted_content(self):
        models.Message.objects.create(
            chatroom=self.room,
            sender=self.alice,
            content='Find me this exact confidential keyword',
        )
        refresh = RefreshToken.for_user(self.bob)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

        # Searching for 'confidential'
        search_res = self.client.get('/messages/search/?q=confidential')
        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(search_res.data), 1)
        self.assertEqual(search_res.data[0]['content'], 'Find me this exact confidential keyword')

    def test_read_receipt_db_marking(self):
        # Alice sends message
        msg1 = models.Message.objects.create(
            chatroom=self.room,
            sender=self.alice,
            content='Hello Bob',
            is_read=False,
        )

        # Mock consumer helper logic for Bob
        from chatapp.consumers import ChatConsumer
        from asgiref.sync import async_to_sync
        consumer = ChatConsumer()
        consumer.user = self.bob
        consumer.room_name_raw = self.room.room_name

        # Invoke _mark_messages_read
        updated = async_to_sync(consumer._mark_messages_read)([msg1.id])
        self.assertEqual(updated, [msg1.id])

        msg1.refresh_from_db()
        self.assertTrue(msg1.is_read)

        # Alice cannot mark her own messages as read by self
        consumer.user = self.alice
        updated_self = async_to_sync(consumer._mark_messages_read)([msg1.id])
        self.assertEqual(updated_self, [])


from chatapp.middleware import JWTAuthMiddleware, _get_user_from_token


class WebSocketJWTAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ws_user', password='pwd')

    def test_jwt_auth_token_resolution(self):
        refresh = RefreshToken.for_user(self.user)
        token_str = str(refresh.access_token)

        # 1. Test underlying user lookup from token
        resolved_user = _get_user_from_token.func(token_str)
        self.assertEqual(resolved_user.username, 'ws_user')

        # 2. Test invalid token returns AnonymousUser
        invalid_user = _get_user_from_token.func('invalid.jwt.token')
        self.assertFalse(invalid_user.is_authenticated)

    async def test_jwt_middleware_query_param(self):
        refresh = RefreshToken.for_user(self.user)
        token_str = str(refresh.access_token)

        inner_called = False
        async def inner_app(scope, receive, send):
            nonlocal inner_called
            inner_called = True
            self.assertEqual(scope['user'].username, 'ws_user')

        middleware = JWTAuthMiddleware(inner_app)
        scope = {
            'type': 'websocket',
            'query_string': f'token={token_str}'.encode(),
            'headers': [],
        }
        await middleware(scope, None, None)
        self.assertTrue(inner_called)


class GroupChatManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user(username='alice', password='Password123!')
        self.bob = User.objects.create_user(username='bob', password='Password123!')
        self.charlie = User.objects.create_user(username='charlie', password='Password123!')
        self.david = User.objects.create_user(username='david', password='Password123!')

        refresh = RefreshToken.for_user(self.alice)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_create_group_chat_with_initial_members(self):
        res = self.client.post('/chatrooms/group/', {
            'room_name': 'Backend Engineering',
            'member_ids': [self.bob.id, self.charlie.id],
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['room_name'], 'Backend Engineering')
        self.assertEqual(res.data['room_type'], 'group')
        self.assertEqual(res.data['created_by'], self.alice.id)
        self.assertEqual(res.data['created_by_username'], 'alice')
        self.assertEqual(res.data['member_count'], 3)
        self.assertIn('alice', res.data['members'])
        self.assertIn('bob', res.data['members'])
        self.assertIn('charlie', res.data['members'])

        room = models.ChatRoom.objects.get(id=res.data['id'])
        self.assertTrue(room.members.filter(id=self.alice.id).exists())
        self.assertTrue(models.ChatRoomSettings.objects.filter(chatroom=room).exists())

    def test_create_group_chat_validation_missing_name(self):
        res = self.client.post('/chatrooms/group/', {
            'room_name': '   ',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invite_users_by_id_and_username(self):
        room = models.ChatRoom.objects.create(
            room_name='Mobile Dev',
            room_type='group',
            created_by=self.alice
        )
        room.members.add(self.alice, self.bob)

        # Alice invites charlie by id and david by username
        res = self.client.post(f'/chatrooms/{room.id}/invite/', {
            'user_ids': [self.charlie.id],
            'usernames': ['david'],
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('charlie', res.data['added_members'])
        self.assertIn('david', res.data['added_members'])
        self.assertEqual(res.data['member_count'], 4)
        self.assertTrue(room.members.filter(id=self.charlie.id).exists())
        self.assertTrue(room.members.filter(id=self.david.id).exists())

    def test_invite_already_member_handling(self):
        room = models.ChatRoom.objects.create(
            room_name='Designers',
            room_type='group',
            created_by=self.alice
        )
        room.members.add(self.alice, self.bob)

        # Re-inviting bob
        res = self.client.post(f'/chatrooms/{room.id}/invite/', {
            'user_id': self.bob.id,
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('bob', res.data['already_members'])

    def test_non_member_cannot_invite(self):
        room = models.ChatRoom.objects.create(
            room_name='Secret Group',
            room_type='group',
            created_by=self.bob
        )
        room.members.add(self.bob, self.charlie)

        # Alice is not a member
        res = self.client.post(f'/chatrooms/{room.id}/invite/', {
            'username': 'david',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_invite_to_private_chat(self):
        private_room = models.ChatRoom.objects.create(
            room_name='private_1',
            room_type='private'
        )
        private_room.members.add(self.alice, self.bob)

        res = self.client.post(f'/chatrooms/{private_room.id}/invite/', {
            'username': 'charlie',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_leave_group_chat_and_deactivation(self):
        room = models.ChatRoom.objects.create(
            room_name='Temporary Project',
            room_type='group',
            created_by=self.alice
        )
        room.members.add(self.alice, self.bob)

        # 1. Alice leaves
        res = self.client.post(f'/chatrooms/{room.id}/leave/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['remaining_members_count'], 1)
        self.assertFalse(room.members.filter(id=self.alice.id).exists())
        room.refresh_from_db()
        self.assertTrue(room.is_active)

        # 2. Bob leaves (last member)
        bob_client = APIClient()
        bob_refresh = RefreshToken.for_user(self.bob)
        bob_client.credentials(HTTP_AUTHORIZATION=f'Bearer {bob_refresh.access_token}')
        bob_res = bob_client.post(f'/chatrooms/{room.id}/leave/')
        self.assertEqual(bob_res.status_code, status.HTTP_200_OK)
        self.assertEqual(bob_res.data['remaining_members_count'], 0)

        room.refresh_from_db()
        self.assertFalse(room.is_active)

    def test_leave_fails_for_non_member(self):
        room = models.ChatRoom.objects.create(
            room_name='Dev Team',
            room_type='group',
            created_by=self.bob
        )
        room.members.add(self.bob)

        # Alice is not a member
        res = self.client.post(f'/chatrooms/{room.id}/leave/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_members_and_creator_remove_member(self):
        room = models.ChatRoom.objects.create(
            room_name='Ops Team',
            room_type='group',
            created_by=self.alice
        )
        room.members.add(self.alice, self.bob, self.charlie)

        # 1. List members
        members_res = self.client.get(f'/chatrooms/{room.id}/members/')
        self.assertEqual(members_res.status_code, status.HTTP_200_OK)
        member_names = [m['username'] for m in members_res.data]
        self.assertIn('alice', member_names)
        self.assertIn('bob', member_names)
        self.assertIn('charlie', member_names)

        # 2. Creator removes member
        rem_res = self.client.post(f'/chatrooms/{room.id}/remove-member/', {
            'username': 'bob',
        }, format='json')
        self.assertEqual(rem_res.status_code, status.HTTP_200_OK)
        self.assertFalse(room.members.filter(id=self.bob.id).exists())


class MessagePaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='alice', password='Password123!')
        self.room = models.ChatRoom.objects.create(room_name='paginated_room', room_type='group')
        self.room.members.add(self.user)

        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

        # Create 25 messages
        for i in range(1, 26):
            models.Message.objects.create(
                chatroom=self.room,
                sender=self.user,
                content=f'Message {i:02d}',
            )

    def test_default_pagination_first_page(self):
        res = self.client.get(f'/chatrooms/{self.room.id}/messages/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn('count', res.data)
        self.assertIn('next', res.data)
        self.assertIn('previous', res.data)
        self.assertIn('results', res.data)

        self.assertEqual(res.data['count'], 25)
        self.assertEqual(res.data['page'], 1)
        self.assertEqual(res.data['total_pages'], 2)
        self.assertEqual(len(res.data['results']), 20)
        self.assertIsNotNone(res.data['next'])
        self.assertIsNone(res.data['previous'])
        self.assertEqual(res.data['results'][0]['content'], 'Message 01')

    def test_custom_page_size(self):
        res = self.client.get(f'/chatrooms/{self.room.id}/messages/?page_size=10')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['results']), 10)
        self.assertEqual(res.data['total_pages'], 3)
        self.assertEqual(res.data['page_size'], 10)

    def test_second_page_navigation(self):
        res = self.client.get(f'/chatrooms/{self.room.id}/messages/?page=2&page_size=10')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['page'], 2)
        self.assertEqual(len(res.data['results']), 10)
        self.assertIsNotNone(res.data['next'])
        self.assertIsNotNone(res.data['previous'])
        # Messages 11 to 20
        self.assertEqual(res.data['results'][0]['content'], 'Message 11')

    def test_unpaginated_fallback_via_param(self):
        res = self.client.get(f'/chatrooms/{self.room.id}/messages/?paginate=false')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)
        self.assertEqual(len(res.data), 25)
        self.assertEqual(res.data[0]['content'], 'Message 01')

