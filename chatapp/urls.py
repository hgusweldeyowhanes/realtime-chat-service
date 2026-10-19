from django.urls import path
from chatapp import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Auth & Tokens
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('register/', views.RegisterView.as_view(), name='register-alias'),
    path('token/', TokenObtainPairView.as_view(), name='token-obtain-pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('token/refrash', TokenRefreshView.as_view(), name='token-refresh-legacy'),  # backwards compatibility typo
    path('login/', views.UserLoginView.as_view(), name='login-user'),
    path('logout/', views.UserLogoutView.as_view(), name='logout-user'),

    # Users & Profiles
    path('users/me/', views.CurrentUserProfileView.as_view(), name='user-profile-me'),
    path('profile/', views.CurrentUserProfileView.as_view(), name='user-profile'),
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('user-status/', views.UserStatusView.as_view(), name='user-status'),
    path('user-status/<int:pk>/', views.UserStatusUpdateDeleteView.as_view(), name='user-status-detail'),
    path('blocked-user/', views.BlockedUserView.as_view(), name='blocked-user'),
    path('blocked-user/<int:pk>/', views.BlockedUserDetailView.as_view(), name='blocked-user-detail'),

    # Rooms & Messages
    path('', views.CreateRoom, name='create-room'),
    path('room/<str:room_name>/', views.Message_room_View, name='room'),
    path('chatrooms/', views.ChatRoom_listView, name='chatroom_list'),
    path('chatrooms/group/', views.GroupChatCreateView.as_view(), name='group-chat-create'),
    path('chatrooms/groups/', views.GroupChatCreateView.as_view(), name='group-chat-create-alias'),
    path('chatrooms/<int:pk>/', views.ChatRoomDetailView.as_view(), name='chatroom_detail'),
    path('chatrooms/<int:pk>/invite/', views.GroupChatInviteView.as_view(), name='group-chat-invite'),
    path('chatrooms/<int:chatroom_id>/invite/', views.GroupChatInviteView.as_view(), name='group-chat-invite-alias'),
    path('chatrooms/<int:pk>/leave/', views.GroupChatLeaveView.as_view(), name='group-chat-leave'),
    path('chatrooms/<int:chatroom_id>/leave/', views.GroupChatLeaveView.as_view(), name='group-chat-leave-alias'),
    path('chatrooms/<int:pk>/members/', views.GroupChatMembersView.as_view(), name='group-chat-members'),
    path('chatrooms/<int:chatroom_id>/members/', views.GroupChatMembersView.as_view(), name='group-chat-members-alias'),
    path('chatrooms/<int:pk>/remove-member/', views.GroupChatRemoveMemberView.as_view(), name='group-chat-remove-member'),
    path('chatrooms/<int:chatroom_id>/remove-member/', views.GroupChatRemoveMemberView.as_view(), name='group-chat-remove-member-alias'),
    path('chatrooms/<int:chatroom_id>/messages/', views.MessageView.as_view(), name='message-list-create'),
    path('messages/<int:pk>/', views.MessageDetailView.as_view(), name='message-detail'),
    path('messages/search/', views.MessageSearchView.as_view(), name='message-search'),

    # Indicators, Settings & Reactions
    path('typing-indicator/', views.TypingIndicatorListView.as_view(), name='typing-indicator'),
    path('message-reaction/', views.MessageReactionView.as_view(), name='message-reaction'),
    path('chatroom-settings/<int:chatroom_id>/', views.ChatRoomSettingView.as_view(), name='chatroom-settings'),
    path('archived-chat/', views.ArchievedChatView.as_view(), name='archived-chat'),
    path('deleted-message/', views.DeletedMessageView.as_view(), name='deleted-message'),
    path('messages/<int:message_id>/react/<int:emoji_id>/', views.AddReactionView.as_view(), name='add-reaction'),
]
