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
        self.assertEqual(res.data[0]['content'], 'Secret Project Plan 2026')

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

