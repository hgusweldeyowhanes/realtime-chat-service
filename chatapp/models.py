from django.db import models
from django.contrib.auth.models import User
import os
from cryptography.fernet import Fernet
from django.conf import settings


class ChatRoom(models.Model):
    ROOM_TYPE = [
        ('private','Private'),
        ('group', 'Group'),
    ]
    room_name = models.CharField(max_length=255)
    room_type = models.CharField(max_length=10,choices=ROOM_TYPE,default='private')
    members = models.ManyToManyField(User,related_name='chatrooms')
    created_by = models.ForeignKey(User, related_name='created_rooms', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        if self.room_type == 'private':
            member_count = self.members.count()
            
            if member_count >= 2:
                first_two_members = self.members.all()[:2]
                member_names = [str(member) for member in first_two_members]
                return f"Private chat between {member_names[0]} and {member_names[1]}"
            elif member_count == 1:
                single_member = self.members.first()
                return f"Private chat with {single_member} (1 member)"
            else:
                return "Private chat (no members)"
        return self.room_name or f"Group Chat {self.id}"
class Emoji(models.Model):
    name = models.CharField(max_length=50)
    image = models.ImageField(upload_to='emojis/')
    is_sticker = models.BooleanField(default=False)

class Message(models.Model):
    FILE_TYPE = [
        ('image','Image'),
        ('voice', 'Voice'),
        ('document',"Document"),
        ('text','Text'),
        ('video','Video')
    ]
    chatroom = models.ForeignKey(ChatRoom,related_name='messages',on_delete=models.CASCADE)
    sender = models.ForeignKey(User ,related_name='sent_messages',on_delete=models.CASCADE)
    content = models.TextField(blank=True, default='')
    message_type = models.CharField(max_length=10,choices=FILE_TYPE,default='text')
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    attachment = models.FileField(upload_to='attachements/',null=True,blank=True)
    emoji_reactions = models.ManyToManyField(Emoji, through='MessageReaction')

    parent = models.ForeignKey('self', null=True, blank=True, 
                              on_delete=models.SET_NULL,
                              related_name='thread_replies')
    is_thread_starter = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp','is_read']),
        ]
    def __str__(self):
        return f"Message from {self.sender.username} in {self.chatroom.room_name} at {self.timestamp}"
    def encrypt_content(self, value):
        """Encrypt plain text content."""
        f = Fernet(settings.ENCRYPTION_KEY)
        return f.encrypt(value.encode()).decode()

    def decrypt_content(self):
        """Decrypt stored content."""
        if not self.content:
            return ""
        f = Fernet(settings.ENCRYPTION_KEY)
        return f.decrypt(self.content.encode()).decode()

    def save(self, *args, **kwargs):
        # Encrypt content before saving if it is not already encrypted
        if self.content:
            try:
                # Try decrypting to see if content is already encrypted
                Fernet(settings.ENCRYPTION_KEY).decrypt(self.content.encode())
            except:
                # If decryption fails, encrypt
                self.content = self.encrypt_content(self.content)
        super().save(*args, **kwargs)
    
class UserStatus(models.Model):
    user = models.OneToOneField(User, related_name='status',on_delete=models.CASCADE)
    is_online = models.BooleanField(default=False)
    is_typing = models.BooleanField(default=False)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {'online' if self.is_online else 'offline'}"
class BlockedUser(models.Model):
    blocker = models.ForeignKey(User,related_name='blocking',on_delete=models.CASCADE)
    blocked = models.ForeignKey(User,related_name='blocked_by',on_delete=models.CASCADE)
    blocked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"
class TypingIndicator(models.Model):
    chatroom = models.ForeignKey(ChatRoom,related_name='typing_indicators',on_delete=models.CASCADE)
    user = models.ForeignKey(User,related_name='tying_status',on_delete=models.CASCADE)
    is_typing = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} is {'typing' if self.is_typing else 'not typing'} in {self.chatroom.room_name}"

class MessageReaction(models.Model):
    REACTION_CHOICES = [
        ('like', 'Like'),
        ('love', 'Love'),
        ('laugh', 'Laugh'),
        ('sad', 'Sad'),
        ('angry', 'Angry'),
        ('wow', 'Wow')
    ]
    message  = models.ForeignKey(Message, related_name='reactions', on_delete=models.CASCADE)
    user = models.ForeignKey(User, related_name='message_reactions', on_delete=models.CASCADE)
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES,default='like')
    reacted_at = models.DateTimeField(auto_now_add=True)
    emoji = models.ForeignKey(Emoji,on_delete=models.CASCADE,null=True,blank=True) 

    def __str__(self):
        return f"{self.user.username} reacted {self.reaction} to message {self.message.id}"
    

class ChatRoomSettings(models.Model):
    chatroom = models.OneToOneField(ChatRoom, related_name= 'settings', on_delete=models.CASCADE)
    mute_notifications = models.BooleanField(default=False)
    pin_chat = models.BooleanField(default=False)
    custom_nickname = models.CharField(max_length=50, null =True, blank = True)
    dark_mode = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.chatroom.room_name} settings"
    

class ArchivedChat(models.Model):
    chatroom = models.ForeignKey(ChatRoom, related_name='archived_chats', on_delete=models.CASCADE)
    archived_by = models.ForeignKey(User, related_name='archieved_chats',on_delete=models.CASCADE)
    archieved_at = models.DateTimeField(auto_now_add=True)
    is_unarchieved = models.BooleanField(default=False)
    un_archievd_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f"{self.chatroom.room_name} archieved by {self.archived_by.username}"
    
class DeletedMessage(models.Model):
    message = models.ForeignKey(Message, related_name='deletions', on_delete=models.CASCADE)
    deleted_by = models.ForeignKey(User, related_name='deleted_messages',on_delete=models.CASCADE)
    deleted_at = models.DateTimeField(auto_now_add=True)
    is_permanent = models.BooleanField(default=False)
    permanent_deletion_at = models.DateTimeField(null=True,blank=True)
    def __str__(self):
        return f"{self.message.id} deleted by {self.deleted_by.username}"


class FCMDevice(models.Model):
    DEVICE_TYPES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web'),
    ]
    user = models.ForeignKey(User, related_name='fcm_devices', on_delete=models.CASCADE)
    registration_token = models.CharField(max_length=255, unique=True)
    device_type = models.CharField(max_length=10, choices=DEVICE_TYPES, default='android')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} ({self.device_type}) - {self.registration_token[:16]}..."


    


            
    