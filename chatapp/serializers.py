import os
from rest_framework import serializers
from django.contrib.auth.models import User
from chatapp import models
from cryptography.fernet import Fernet
from django.conf import settings



class ChatRoomSerializer(serializers.ModelSerializer):
    members = serializers.StringRelatedField(many=True, read_only=True)
    name = serializers.CharField(source='room_name', read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    member_count = serializers.IntegerField(source='members.count', read_only=True)

    class Meta:
        model = models.ChatRoom
        fields = [
            'id',
            'room_name',
            'name',
            'room_type',
            'members',
            'member_count',
            'created_by',
            'created_by_username',
            'created_at',
            'is_active',
        ]


class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    content = serializers.CharField(required=False, allow_blank=True, default='')
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = models.Message
        fields = [
            'id',
            'chatroom',
            'sender',
            'sender_username',
            'content',
            'message_type',
            'timestamp',
            'is_read',
            'is_edited',
            'is_deleted',
            'attachment',
            'attachment_url',
        ]
        read_only_fields = ['id', 'chatroom', 'timestamp', 'is_read', 'is_edited', 'is_deleted', 'sender']


    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get('request')
        if request:
            try:
                return request.build_absolute_uri(obj.attachment.url)
            except Exception:
                pass
        return getattr(obj.attachment, 'url', None)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        try:
            ret['content'] = instance.decrypt_content()
        except Exception:
            pass
        return ret



class EmojiSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Emoji
        fields = ['id', 'name', 'image', 'is_sticker']


class UserStatusSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = models.UserStatus
        fields = [
            'id',
            'username',
            'is_online',
            'is_typing',
            'last_seen',
        ]

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().update(instance, validated_data)


class BlockedUserSerializer(serializers.ModelSerializer):
    blocker_username = serializers.CharField(source='blocker.username', read_only=True)
    blocked_username = serializers.CharField(source='blocked.username', read_only=True)
    blocker = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.BlockedUser
        fields = [
            'blocker',
            'blocker_username',
            'blocked',
            'blocked_username',
            'blocked_at',
        ]


class TypingIndicatorSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    chatroom_username = serializers.CharField(source='chatroom.room_name', read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.TypingIndicator
        fields = [
            'id',
            'chatroom_username',
            'chatroom',
            'user',
            'username',
            'is_typing',
            'updated_at',
        ]
        read_only_fields = ['username', 'chatroom_username', 'updated_at', 'user']


class MessageReactionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    message_id = serializers.IntegerField(source='message.id', read_only=True)

    class Meta:
        model = models.MessageReaction
        fields = [
            'id',
            'message',
            'message_id',
            'user',
            'username',
            'reaction',
            'reacted_at',
        ]
        read_only_fields = ['id', 'username', 'message_id', 'user', 'reacted_at']


class ChatRoomSettingSerializer(serializers.ModelSerializer):
    chatroom_name = serializers.CharField(source='chatroom.room_name', read_only=True)

    class Meta:
        model = models.ChatRoomSettings
        fields = [
            'id',
            'chatroom',
            'chatroom_name',
            'mute_notifications',
            'dark_mode',
            'pin_chat',
            'custom_nickname',
        ]
        read_only_fields = ['id', 'chatroom_name']


class ArchivedChatSerializer(serializers.ModelSerializer):
    chatroom_name = serializers.CharField(source='chatroom.room_name', read_only=True)
    archived_by_username = serializers.CharField(source='archived_by.username', read_only=True)

    class Meta:
        model = models.ArchivedChat
        fields = [
            'id',
            'chatroom',
            'chatroom_name',
            'archived_by',
            'archived_by_username',
            'archieved_at',
            'is_unarchieved',
            'un_archievd_at',
        ]
        read_only_fields = ['id', 'chatroom_name', 'archived_by', 'archived_by_username', 'archieved_at']


class DeletedMessageSerializer(serializers.ModelSerializer):
    message_id = serializers.CharField(source='message.id', read_only=True)
    deleted_by_username = serializers.CharField(source='deleted_by.username', read_only=True)

    class Meta:
        model = models.DeletedMessage
        fields = [
            'id',
            'message',
            'message_id',
            'deleted_by',
            'deleted_by_username',
            'deleted_at',
            'is_permanent',
            'permanent_deletion_at',
        ]
        read_only_fields = ['id', 'message_id', 'deleted_by_username', 'deleted_at', 'deleted_by']


# --- Step 2: User Registration & Profile Serializers ---


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, style={'input_type': 'password'})
    tokens = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'first_name', 'last_name', 'tokens']

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def get_tokens(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        models.UserStatus.objects.get_or_create(user=user, defaults={'is_online': False})
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    is_online = serializers.BooleanField(source='status.is_online', read_only=True)
    last_seen = serializers.DateTimeField(source='status.last_seen', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'is_online', 'last_seen']
        read_only_fields = ['id', 'username', 'date_joined', 'is_online', 'last_seen']


class UserSummarySerializer(serializers.ModelSerializer):
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'is_online']

    def get_is_online(self, obj):
        status_obj = getattr(obj, 'status', None)
        return status_obj.is_online if status_obj else False


# --- Step 3: Group Chat Serializers ---


class CreateGroupChatSerializer(serializers.Serializer):
    room_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list
    )
    members = serializers.ListField(
        required=False,
        default=list
    )

    def validate(self, attrs):
        name_val = attrs.get('room_name') or attrs.get('name')
        if not name_val or not str(name_val).strip():
            raise serializers.ValidationError({"room_name": "A valid group room_name is required."})
        attrs['room_name'] = str(name_val).strip()
        return attrs


class InviteToGroupChatSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False)
    user_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    username = serializers.CharField(required=False, allow_blank=True)
    usernames = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    member_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    members = serializers.ListField(required=False, default=list)

    def validate(self, attrs):
        has_any = (
            attrs.get('user_id') is not None or
            bool(attrs.get('user_ids')) or
            bool(attrs.get('username')) or
            bool(attrs.get('usernames')) or
            bool(attrs.get('member_ids')) or
            bool(attrs.get('members'))
        )
        if not has_any:
            raise serializers.ValidationError("At least one user ID or username must be provided to invite.")
        return attrs


class FCMDeviceSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    registration_token = serializers.CharField(max_length=255)

    class Meta:
        model = models.FCMDevice
        fields = [
            'id',
            'user',
            'user_username',
            'registration_token',
            'device_type',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'user_username', 'created_at', 'updated_at']
        extra_kwargs = {
            'registration_token': {'validators': []},
        }


    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user if request and request.user.is_authenticated else validated_data.get('user')
        token = validated_data.get('registration_token')
        device_type = validated_data.get('device_type', 'android')
        device, _ = models.FCMDevice.objects.update_or_create(
            registration_token=token,
            defaults={
                'user': user,
                'device_type': device_type,
                'is_active': True,
            }
        )
        return device


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    content = serializers.CharField(required=False, allow_blank=True, default='')
    caption = serializers.CharField(required=False, allow_blank=True, default='')
    message_type = serializers.CharField(required=False, allow_blank=True, default='')
    parent_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_file(self, value):
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 50 * 1024 * 1024)
        if value.size > max_size:
            raise serializers.ValidationError(
                f"File size ({value.size} bytes) exceeds maximum allowed size ({max_size} bytes)."
            )
        return value

    def validate(self, attrs):
        # Support both 'content' and 'caption' param names
        if not attrs.get('content') and attrs.get('caption'):
            attrs['content'] = attrs['caption']

        file_obj = attrs.get('file')
        msg_type = (attrs.get('message_type') or '').strip().lower()

        # Auto-detect message_type from content type / extension if not provided or valid
        if not msg_type or msg_type not in dict(models.Message.FILE_TYPE):
            content_type = getattr(file_obj, 'content_type', '') or ''
            fname = getattr(file_obj, 'name', '') or ''
            ext = os.path.splitext(fname)[1].lower()

            if content_type.startswith('image/') or ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}:
                msg_type = 'image'
            elif content_type.startswith('audio/') or ext in {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'}:
                msg_type = 'voice'
            elif content_type.startswith('video/') or ext in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
                msg_type = 'video'
            else:
                msg_type = 'document'

        attrs['message_type'] = msg_type
        return attrs

