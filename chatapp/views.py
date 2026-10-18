from django.shortcuts import get_object_or_404,redirect,render
from chatapp import models
from django.db.models import Q
from django.urls import reverse_lazy
from rest_framework import generics,permissions,status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from chatapp.serializers import (
    ChatRoomSerializer,
    MessageSerializer,
    MessageReactionSerializer,
    UserStatusSerializer,
    BlockedUserSerializer,
    DeletedMessageSerializer,
    ArchivedChatSerializer,
    TypingIndicatorSerializer,
    ChatRoomSettingSerializer,
    UserRegistrationSerializer,
    UserProfileSerializer,
    UserSummarySerializer,
)
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import TemplateView


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

def ChatRoom_listView(request):
    rooms = models.ChatRoom.objects.all()
    context = {'chatrooms':rooms}
    return render(request,'chatroom_list.html',context=context)
class ChatRoomDetailView(generics.RetrieveAPIView):
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        return models.ChatRoom.objects.filter(members = self.request.user)

class MessageView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self,request,chatroom_id):

        chatroom = get_object_or_404(models.ChatRoom,id = chatroom_id, members = request.user)
        messages = models.Message.objects.filter(chatroom=chatroom).order_by('timestamp')
        serializers= MessageSerializer(messages, many = True)
        return Response(serializers.data,status=status.HTTP_200_OK)
    def post(self,request,chatroom_id):

        chatroom = get_object_or_404(models.ChatRoom, id = chatroom_id, members=request.user)
        serializer = MessageSerializer(data = request.data)
        if serializer.is_valid():
            serializer.save(sender=request.user, chatroom=chatroom)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
    
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


