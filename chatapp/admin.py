from django.contrib import admin
from chatapp import models


@admin.register(models.ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('id', 'room_name', 'room_type', 'created_at', 'is_active')
    filter_horizontal = ('members',)

@admin.register(models.Message)  
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id','timestamp', 'sender', 'chatroom', 'message_type')
@admin.register(models.ChatRoomSettings)
class ChatRoomSettingsAdmin(admin.ModelAdmin):
    list_display = ('chatroom', 'mute_notifications', 'pin_chat', 'custom_nickname', 'dark_mode')
    list_filter = ('mute_notifications', 'pin_chat', 'dark_mode')
    search_fields = ('chatroom__name', 'custom_nickname')

@admin.register(models.ArchivedChat)
class ArchivedChatAdmin(admin.ModelAdmin):
    list_display = ('chatroom', 'archived_by', 'archieved_at', 'is_unarchieved', 'un_archievd_at')
    list_filter = ('is_unarchieved',)
    search_fields = ('chatroom__name', 'archived_by__username')

@admin.register(models.DeletedMessage)
class DeletedMessageAdmin(admin.ModelAdmin):
    list_display = ('message', 'deleted_by', 'deleted_at', 'is_permanent', 'permanent_deletion_at')
    list_filter = ('is_permanent',)
    search_fields = ('message__text', 'deleted_by__username')

admin.site.register(models.MessageReaction)
admin.site.register(models.UserStatus)
admin.site.register(models.BlockedUser)
admin.site.register(models.TypingIndicator)
admin.site.register(models.Emoji)

@admin.register(models.FCMDevice)
class FCMDeviceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'device_type', 'registration_token', 'is_active', 'updated_at')
    list_filter = ('device_type', 'is_active')
    search_fields = ('user__username', 'registration_token')

