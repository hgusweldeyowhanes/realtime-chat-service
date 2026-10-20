import logging
import os
import re

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import TemplateView
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from chatapp import models
from chatapp.serializers import (
    ArchivedChatSerializer,
    BlockedUserSerializer,
    ChatRoomSerializer,
    ChatRoomSettingSerializer,
    CreateGroupChatSerializer,
    DeletedMessageSerializer,
    FCMDeviceSerializer,
    FileUploadSerializer,
    InviteToGroupChatSerializer,
    MessageReactionSerializer,
    MessageSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
    UserStatusSerializer,
    UserSummarySerializer,
    TypingIndicatorSerializer,
)

logger = logging.getLogger(__name__)


def _broadcast_message_to_room(chatroom, message, request=None):
    """
    Broadcasts a saved Message object to all connected WebSocket clients in the room.
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            safe_room_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", chatroom.room_name)
            group_name = f"chat_{safe_room_name}"

            att_url = ""
            if message.attachment:
                if request:
                    try:
                        att_url = request.build_absolute_uri(message.attachment.url)
                    except Exception:
                        att_url = message.attachment.url
                else:
                    att_url = message.attachment.url

            try:
                content_text = message.decrypt_content() if message.content else ""
            except Exception:
                content_text = message.content or ""

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "chat.message",
                    "message": {
                        "id": message.id,
                        "sender": message.sender.username,
                        "sender_id": message.sender.id,
                        "message": content_text,
                        "message_type": message.message_type,
                        "room_name": chatroom.room_name,
                        "timestamp": message.timestamp.isoformat(),
                        "attachment_url": att_url,
                    },
                },
            )
    except Exception as exc:
        logger.debug("Failed to broadcast message to channel layer: %s", exc)



def CreateRoom(request):

    if request.method == 'POST':
        room = request.POST['room']

        try:
            get_room = models.ChatRoom.objects.get(room_name=room)
            return redirect('room', room_name=room)

        except models.ChatRoom.DoesNotExist:
            new_room = models.ChatRoom(room_name = room)
            new_room.save()
            return redirect('room', room_name=room)

    return render(request, 'index.html')

def Message_room_View(request, room_name):

    get_room ,created= models.ChatRoom.objects.get_or_create(room_name=room_name)

    if request.method == 'POST':
        message = request.POST['message']
        if message: 
            new_message = models.Message(
                chatroom=get_room, 
                sender=request.user, 
                content=message)

    get_messages= models.Message.objects.filter(chatroom=get_room).order_by('timestamp')
    
    context = {
        "messages": get_messages,
        "user": request.user,
        "room_name": room_name,
    }
    return render(request, 'message.html', context)

class AddReactionView(APIView):
    def post(self,request,message_id,emoji_id):
        user = request.user
        try:
            message = models.Message.objects.get(id = message_id)
            emoji = models.Emoji.objects.get(id = emoji_id)
            reaction,created = models.MessageReaction.objects.get_or_create(
                message=message,
                emoji=emoji,
                user=user
                )
            if created:
                return Response({"success:":"reaction added"},status=status.HTTP_201_CREATED)
            else:
                return Response({"info":"reaction already exists"},status=status.HTTP_200_OK)
        except models.Message.DoesNotExist:
            return Response({"errorr":"message not found"},status=status.HTTP_404_NOT_FOUND)
        except models.Emoji.DoesNotExist:
            return Response({"error":"emoji not found"},status=status.HTTP_404_NOT_FOUND)
        
        
class ChatPageView(TemplateView):
    template_name = 'chatpage.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login-user")
        return super().dispatch(request, *args, **kwargs)
    

class UserLoginView(LoginView):
    template_name = "login.html"   
    redirect_authenticated_user = False


    def get_success_url(self):
        return reverse_lazy('chatroom_list')
    
class UserLogoutView(LogoutView):
    next_page = reverse_lazy('login-user')

# --- Step 4: Message Pagination ---


class MessagePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if request.query_params.get('paginate') == 'false':
            return None
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        total_pages = self.page.paginator.num_pages if hasattr(self, 'page') and self.page else 1
        current_page = self.page.number if hasattr(self, 'page') and self.page else 1
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'page': current_page,
            'total_pages': total_pages,
            'page_size': self.get_page_size(self.request),
            'results': data
        })


class ChatRoomListCreateView(APIView):
    """
    List user's active chatrooms or create a new chatroom.
    Renders chatroom_list.html when requested via browser HTML navigation.
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get(self, request):
        accept = request.headers.get('Accept', '')
        # Browser viewing list page
        if 'text/html' in accept and 'application/json' not in accept and request.query_params.get('format') != 'json':
            rooms = models.ChatRoom.objects.all()
            return render(request, 'chatroom_list.html', {'chatrooms': rooms})

        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        rooms = models.ChatRoom.objects.filter(members=request.user, is_active=True).order_by('-created_at')
        serializer = ChatRoomSerializer(rooms, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication credentials were not provided."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        room_name = request.data.get('room_name') or request.data.get('name')
        if not room_name or not str(room_name).strip():
            return Response({"room_name": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        room_type = request.data.get('room_type', 'group')
        room = models.ChatRoom.objects.create(
            room_name=str(room_name).strip(),
            room_type=room_type,
            created_by=request.user,
            is_active=True,
        )
        room.members.add(request.user)

        member_ids = request.data.get('member_ids') or request.data.get('members') or []
        for mid in member_ids:
            if isinstance(mid, int) or (isinstance(mid, str) and mid.isdigit()):
                u = User.objects.filter(pk=int(mid)).first()
                if u:
                    room.members.add(u)
            elif isinstance(mid, str):
                u = User.objects.filter(username__iexact=mid.strip()).first()
                if u:
                    room.members.add(u)

        models.ChatRoomSettings.objects.get_or_create(chatroom=room)
        return Response(ChatRoomSerializer(room).data, status=status.HTTP_201_CREATED)


ChatRoom_listView = ChatRoomListCreateView.as_view()


class ChatRoomDetailView(generics.RetrieveAPIView):
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return models.ChatRoom.objects.filter(members=self.request.user)


class MessageView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MessageSerializer
    pagination_class = MessagePagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        chatroom_id = self.kwargs.get('chatroom_id')
        chatroom = get_object_or_404(models.ChatRoom, id=chatroom_id, members=self.request.user)
        return models.Message.objects.filter(chatroom=chatroom).order_by('timestamp')

    def perform_create(self, serializer):
        chatroom_id = self.kwargs.get('chatroom_id')
        chatroom = get_object_or_404(models.ChatRoom, id=chatroom_id, members=self.request.user)
        instance = serializer.save(sender=self.request.user, chatroom=chatroom)

        if instance.attachment and instance.message_type == 'text':
            fname = instance.attachment.name.lower()
            ext = os.path.splitext(fname)[1]
            if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}:
                instance.message_type = 'image'
            elif ext in {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'}:
                instance.message_type = 'voice'
            elif ext in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
                instance.message_type = 'video'
            else:
                instance.message_type = 'document'
            instance.save(update_fields=['message_type'])

        _broadcast_message_to_room(chatroom, instance, self.request)

        try:
            from chatapp.tasks import send_push_notification_task
            send_push_notification_task.delay(instance.id)
        except Exception as exc:
            logger.debug("Failed to dispatch Celery push notification task: %s", exc)

    
class MessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self,pk,user):
        return get_object_or_404(models.Message, id=pk, chatroom__members=user)

    def get(self,request,pk):
        message = self.get_object(pk,request.user)
        serializer = MessageSerializer(message)
        return Response(serializer.data)
    def patch(self, request, pk):
        message = self.get_object(pk,request.user)

        if message.sender != request.user:
            return Response({"errors":"You can only edit your self message"},status=status.HTTP_403_FORBIDDEN)
        serializer = MessageSerializer(message,data = request.data, partial = True)
        if serializer.is_valid():
            serializer.save(is_edited = True)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self,request,pk):
        message = self.get_object(pk,request.user)
        if message.sender !=request.user:
            return Response({"error":"You can delete your own message"}, status=status.HTTP_403_FORBIDDEN)
        
        message.is_deleted = True
        message.save()
        return Response({"status":"message deleted"}, status=status.HTTP_204_NO_CONTENT)

class MessageSearchView(APIView):
    """
    Search messages in chatrooms the user is a member of.
    Since message content is encrypted with Fernet in the database,
    we retrieve messages in the user's rooms, decrypt them, and match
    the plaintext query and/or attachment name.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query = (request.GET.get('q') or '').strip()
        if not query:
            return Response([])

        chatroom_id = request.GET.get('chatroom_id')

        qs = models.Message.objects.filter(
            chatroom__members=request.user,
            is_deleted=False
        )
        if chatroom_id:
            qs = qs.filter(chatroom_id=chatroom_id)

        # Capped to recent 300 messages to prevent excessive memory decryption
        candidates = list(
            qs.select_related('sender', 'chatroom').order_by('-timestamp')[:300]
        )

        q_lower = query.lower()
        matched = []
        for msg in candidates:
            try:
                decrypted = msg.decrypt_content()
            except Exception:
                decrypted = msg.content or ""

            attachment_name = msg.attachment.name if msg.attachment else ""
            if q_lower in decrypted.lower() or (attachment_name and q_lower in attachment_name.lower()):
                matched.append(msg)
                if len(matched) >= 50:
                    break

        serializer = MessageSerializer(matched, many=True)
        return Response(serializer.data)


# --- Step 2: User Registration & Profile Views ---


class RegisterView(generics.CreateAPIView):
    """Register a new user and return JWT auth tokens."""
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]


class CurrentUserProfileView(generics.RetrieveUpdateAPIView):
    """Get or update current authenticated user profile."""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    """List or search other users to start conversations with."""
    serializer_class = UserSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = User.objects.exclude(id=self.request.user.id)
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)
            )
        return qs.order_by('username')[:50]


class UserStatusView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class  = UserStatusSerializer

    def get_queryset(self):
        return models.UserStatus.objects.all()
    
    def perform_create(self,serializer):
        return serializer.save(user = self.request.user)

class UserStatusUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class  = UserStatusSerializer

    def get_queryset(self):
        return models.UserStatus.objects.filter(user = self.request.user)

    def perform_create(self,serializer):
        return serializer.save(user = self.request.user)
class BlockedUserView(generics.ListCreateAPIView):
    serializer_class = BlockedUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return models.BlockedUser.objects.filter(blocker = self.request.user)
    def perform_create(self, serializer):
        serializer.save(blocker = self.request.user)
class BlockedUserDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = BlockedUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return  models.BlockedUser.objects.filter(blocker = self.request.user)
class TypingIndicatorListView(generics.ListCreateAPIView):
    serializer_class = TypingIndicatorSerializer
    permission_classes = [permissions.IsAuthenticated] 

    def get_queryset(self):
        chatroom_id = self.request.query_params.get('chatroom')
        qs = models.TypingIndicator.objects.all()
        if chatroom_id:
            qs = qs.filter(chatroom_id=chatroom_id)
        return qs
    def perform_create(self, serializer):
        chatroom = serializer.validated_data['chatroom']
        obj, created = models.TypingIndicator.objects.update_or_create(chatroom=chatroom,user = self.request.user,defaults= {"is_typing":serializer.validated_data.get("is_typing",False)})
        return obj

class MessageReactionView(generics.ListCreateAPIView):
    serializer_class = MessageReactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        message_id = self.request.query_params.get('message')
        qs = models.MessageReaction.objects.all()
        if message_id:
            qs = qs.filter(message_id=message_id)
        return qs
    def perform_create(self, serializer):
        message = serializer.validated_data['message']
        reaction = serializer.validated_data.get('reaction','like')
        models.MessageReaction.objects.update_or_create(message =message,user = self.request.user,defaults={"reaction":reaction})

class ChatRoomSettingView(generics.ListCreateAPIView):
    serializer_class = ChatRoomSettingSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'chatroom_id'

    def get_queryset(self):
        return models.ChatRoomSettings.objects.all()
    def perform_update(self, serializer):
        serializer.save()

class ArchievedChatView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ArchivedChatSerializer

    def get_queryset(self):
        chatroom_id = self.request.query_params.get('chatroom')
        qs = models.ArchivedChat.objects.all()
        if chatroom_id:
            qs = qs.filter(chatroom_id=chatroom_id)
        return qs
    def perform_create(self, serializer):
        serializer.save(archived_by = self.request.user)

class DeletedMessageView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DeletedMessageSerializer

    def get_queryset(self):
        message_id = self.request.query_params.get('message')
        qs = models.DeletedMessage.objects.all()
        if message_id:
            qs = qs.filter(message_id=message_id)
        return qs
    def perform_create(self, serializer):
        serializer.save(deleted_by = self.request.user)


# --- Step 3: Group Chat Management Views ---


class GroupChatCreateView(APIView):
    """
    Create a new group chatroom.
    The creator is automatically added as a member.
    Initial members can optionally be passed via `member_ids` or `members`.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateGroupChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        room_name = serializer.validated_data['room_name']
        member_ids = serializer.validated_data.get('member_ids', [])
        raw_members = serializer.validated_data.get('members', [])

        room = models.ChatRoom.objects.create(
            room_name=room_name,
            room_type='group',
            created_by=request.user,
            is_active=True,
        )
        room.members.add(request.user)

        users_to_add = set()
        for mid in member_ids:
            try:
                users_to_add.add(User.objects.get(pk=mid))
            except (User.DoesNotExist, ValueError):
                pass

        for m in raw_members:
            if isinstance(m, int) or (isinstance(m, str) and str(m).isdigit()):
                try:
                    users_to_add.add(User.objects.get(pk=int(m)))
                except User.DoesNotExist:
                    pass
            elif isinstance(m, str):
                try:
                    users_to_add.add(User.objects.get(username__iexact=m.strip()))
                except User.DoesNotExist:
                    pass

        if users_to_add:
            room.members.add(*users_to_add)

        models.ChatRoomSettings.objects.get_or_create(chatroom=room)
        return Response(ChatRoomSerializer(room).data, status=status.HTTP_201_CREATED)


class GroupChatInviteView(APIView):
    """
    Invite one or more users to a group chat.
    Accepts user_id, user_ids, username, usernames, or member_ids.
    Only existing group chat members can invite new users.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None, chatroom_id=None):
        room_id = pk or chatroom_id
        room = get_object_or_404(models.ChatRoom, pk=room_id)

        if not room.is_active:
            return Response(
                {"error": "This chat room is inactive."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if room.room_type != 'group':
            return Response(
                {"error": "Cannot invite users to a private chat. Only group chats support invitations."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not room.members.filter(pk=request.user.pk).exists():
            return Response(
                {"error": "You must be a member of this group chat to invite other users."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = InviteToGroupChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_ids = []
        raw_usernames = []

        data = request.data
        if 'user_id' in data and data['user_id'] is not None:
            raw_ids.append(data['user_id'])
        if 'user_ids' in data and isinstance(data['user_ids'], list):
            raw_ids.extend(data['user_ids'])
        if 'member_ids' in data and isinstance(data['member_ids'], list):
            raw_ids.extend(data['member_ids'])

        if 'username' in data and data['username']:
            raw_usernames.append(data['username'])
        if 'usernames' in data and isinstance(data['usernames'], list):
            raw_usernames.extend(data['usernames'])

        if 'members' in data and isinstance(data['members'], list):
            for item in data['members']:
                if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit()):
                    raw_ids.append(int(item))
                elif isinstance(item, str):
                    raw_usernames.append(item)

        added_users = []
        already_members = []
        not_found = []

        for uid in set(raw_ids):
            try:
                target_user = User.objects.get(pk=uid)
                if room.members.filter(pk=target_user.pk).exists():
                    already_members.append(target_user.username)
                else:
                    room.members.add(target_user)
                    added_users.append(target_user.username)
            except (User.DoesNotExist, ValueError):
                not_found.append(str(uid))

        for uname in set(raw_usernames):
            uname_clean = str(uname).strip()
            if not uname_clean:
                continue
            try:
                target_user = User.objects.get(username__iexact=uname_clean)
                if room.members.filter(pk=target_user.pk).exists():
                    if target_user.username not in already_members:
                        already_members.append(target_user.username)
                else:
                    room.members.add(target_user)
                    if target_user.username not in added_users:
                        added_users.append(target_user.username)
            except User.DoesNotExist:
                not_found.append(uname_clean)

        if not added_users and not already_members and not_found:
            return Response(
                {"error": f"Users not found: {', '.join(not_found)}"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({
            "message": "Invitation processed successfully.",
            "chatroom_id": room.id,
            "room_name": room.room_name,
            "added_members": added_users,
            "already_members": already_members,
            "not_found": not_found,
            "members": [u.username for u in room.members.all()],
            "member_count": room.members.count()
        }, status=status.HTTP_200_OK)


class GroupChatLeaveView(APIView):
    """
    Leave a group chatroom.
    If the leaving user is the last member of the group, marks room is_active=False.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None, chatroom_id=None):
        return self._leave(request, pk or chatroom_id)

    def delete(self, request, pk=None, chatroom_id=None):
        return self._leave(request, pk or chatroom_id)

    def _leave(self, request, room_id):
        room = get_object_or_404(models.ChatRoom, pk=room_id)

        if not room.members.filter(pk=request.user.pk).exists():
            return Response(
                {"error": "You are not a member of this chat room."},
                status=status.HTTP_400_BAD_REQUEST
            )

        room.members.remove(request.user)

        remaining_count = room.members.count()
        if room.room_type == 'group' and remaining_count == 0:
            room.is_active = False
            room.save(update_fields=['is_active'])

        return Response({
            "message": "Successfully left the group chat.",
            "chatroom_id": room.id,
            "room_name": room.room_name,
            "remaining_members_count": remaining_count
        }, status=status.HTTP_200_OK)


class GroupChatMembersView(generics.ListAPIView):
    """List all members of a chat room."""
    serializer_class = UserSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        room_id = self.kwargs.get('pk') or self.kwargs.get('chatroom_id')
        room = get_object_or_404(models.ChatRoom, pk=room_id, members=self.request.user)
        return room.members.all().order_by('username')


class GroupChatRemoveMemberView(APIView):
    """Remove a member from the group chat (admin / creator only)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None, chatroom_id=None):
        return self._remove(request, pk or chatroom_id)

    def delete(self, request, pk=None, chatroom_id=None):
        return self._remove(request, pk or chatroom_id)

    def _remove(self, request, room_id):
        room = get_object_or_404(models.ChatRoom, pk=room_id)

        if room.room_type != 'group':
            return Response(
                {"error": "Only group chats have removable members."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if room.created_by and room.created_by != request.user and not request.user.is_staff:
            return Response(
                {"error": "Only the group creator can remove members."},
                status=status.HTTP_403_FORBIDDEN
            )

        target_user_id = request.data.get('user_id') or request.data.get('member_id')
        target_username = request.data.get('username')

        target_user = None
        if target_user_id:
            target_user = User.objects.filter(pk=target_user_id).first()
        elif target_username:
            target_user = User.objects.filter(username__iexact=target_username).first()

        if not target_user:
            return Response({"error": "Target user not found."}, status=status.HTTP_404_NOT_FOUND)

        if not room.members.filter(pk=target_user.pk).exists():
            return Response({"error": "User is not a member of this group."}, status=status.HTTP_400_BAD_REQUEST)

        room.members.remove(target_user)
        return Response({
            "message": f"User {target_user.username} removed from group chat.",
            "chatroom_id": room.id,
            "members": [u.username for u in room.members.all()],
            "member_count": room.members.count()
        }, status=status.HTTP_200_OK)


class FileUploadView(APIView):
    """
    Step 5: Media / File Upload Endpoint.

    Supports multipart/form-data upload:
      - file (or attachment): The file payload.
      - chatroom (or chatroom_id): ID of the destination chatroom (optional).
      - content (or caption): Optional text message or caption.
      - message_type: Optional (image, voice, video, document). Auto-detected if omitted.
      - parent_id: Optional parent message ID for threaded replies.

    When chatroom is supplied:
      - Validates caller membership in the room (403 if unauthorized).
      - Creates Message with encrypted content and attachment file.
      - Broadcasts message immediately to all room members via Django Channels WebSockets.
      - Dispatches asynchronous FCM push notification via Celery worker.
      - Returns 201 Created with Message representation.

    When chatroom is not supplied:
      - Saves the file to media storage and returns { "file_url", "file_name", "size", "message_type" }.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, chatroom_id=None):
        room_id = chatroom_id or request.data.get('chatroom_id') or request.data.get('chatroom')

        upload_file = request.FILES.get('file') or request.FILES.get('attachment')
        if not upload_file:
            return Response(
                {"error": "No file uploaded. Please supply a 'file' or 'attachment' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data.copy()
        data['file'] = upload_file
        serializer = FileUploadSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        file_obj = validated['file']
        content = validated.get('content', '')
        message_type = validated.get('message_type', 'document')
        parent_id = validated.get('parent_id')

        if room_id:
            try:
                room_id_int = int(room_id)
            except (ValueError, TypeError):
                return Response({"error": "Invalid chatroom_id."}, status=status.HTTP_400_BAD_REQUEST)

            chatroom = get_object_or_404(models.ChatRoom, id=room_id_int)
            if not chatroom.members.filter(id=request.user.id).exists():
                return Response(
                    {"error": "You are not a member of this chatroom."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            parent_msg = None
            if parent_id:
                parent_msg = models.Message.objects.filter(id=parent_id, chatroom=chatroom).first()

            message = models.Message.objects.create(
                chatroom=chatroom,
                sender=request.user,
                content=content,
                message_type=message_type,
                attachment=file_obj,
                parent=parent_msg,
            )

            # Real-time WebSocket fan-out
            _broadcast_message_to_room(chatroom, message, request)

            # Asynchronous Celery push notification
            try:
                from chatapp.tasks import send_push_notification_task
                send_push_notification_task.delay(message.id)
            except Exception as exc:
                logger.debug("Failed to dispatch Celery push task: %s", exc)

            response_serializer = MessageSerializer(message, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        # Standalone upload without chatroom
        from django.core.files.storage import default_storage
        saved_path = default_storage.save(f"uploads/{file_obj.name}", file_obj)
        try:
            file_url = request.build_absolute_uri(default_storage.url(saved_path))
        except Exception:
            file_url = default_storage.url(saved_path)

        return Response({
            "message": "File uploaded successfully.",
            "file_url": file_url,
            "file_name": file_obj.name,
            "size": file_obj.size,
            "message_type": message_type,
        }, status=status.HTTP_201_CREATED)


class FCMDeviceListCreateView(generics.ListCreateAPIView):
    """
    Step 6: Register and list FCM device tokens for push notifications.

    POST /devices/
      {"registration_token": "...", "device_type": "android"|"ios"|"web"}
    GET /devices/
      List all active registered devices for current user
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FCMDeviceSerializer

    def get_queryset(self):
        return models.FCMDevice.objects.filter(user=self.request.user, is_active=True)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        return Response(
            FCMDeviceSerializer(device, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class FCMDeviceDetailView(APIView):
    """
    Step 6: Unregister / deactivate an FCM device token.

    DELETE /devices/<identifier>/  (identifier can be token or primary key)
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, identifier=None, pk=None):
        lookup = identifier if identifier is not None else pk
        if lookup is None:
            lookup = request.data.get('registration_token') or request.data.get('token')

        if not lookup:
            return Response(
                {"error": "Please provide a device identifier or registration_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = None
        if str(lookup).isdigit():
            device = models.FCMDevice.objects.filter(id=int(lookup), user=request.user).first()
        if not device:
            device = models.FCMDevice.objects.filter(registration_token=str(lookup), user=request.user).first()

        if not device:
            return Response({"error": "Device token not found."}, status=status.HTTP_404_NOT_FOUND)

        device.is_active = False
        device.save(update_fields=['is_active'])
        return Response({"message": "Device token unregistered successfully."}, status=status.HTTP_200_OK)



