"""
WebSocket consumers for real-time messaging and presence tracking.

- ChatConsumer: one-to-one & group rooms (persist to PostgreSQL, optional gRPC)
- PresenceConsumer: online/offline + last_seen broadcasts
"""
from __future__ import annotations

import json
import logging
import re

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from chatapp import models

logger = logging.getLogger(__name__)
PRESENCE_GROUP = "presence_global"


class ChatConsumer(AsyncWebsocketConsumer):
    """
    Real-time chat over WebSockets.
    Clients join a room group and send JSON:
      {"type": "chat.message", "message": "...", "message_type": "text"}
      {"type": "typing", "is_typing": true}
    """

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        room_name_raw = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_name_raw = room_name_raw
        safe_room_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", room_name_raw)
        self.room_group_name = f"chat_{safe_room_name}"

        member_ok = await self._user_is_member(room_name_raw, self.user.id)
        if not member_ok:
            # Allow auto-join for private rooms named with both users later; for now close
            room = await self._get_or_create_room(room_name_raw)
            await self._ensure_membership(room.id, self.user.id)

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info("WS connect user=%s room=%s", self.user.username, room_name_raw)

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "invalid_json"}))
            return

        event_type = payload.get("type", "chat.message")

        if event_type == "typing":
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat.typing",
                    "user_id": self.user.id,
                    "username": self.user.username,
                    "is_typing": bool(payload.get("is_typing", True)),
                },
            )
            await self._set_typing(bool(payload.get("is_typing", True)))
            return

        # ── Read-receipt ──────────────────────────────────────────────────
        # Client sends: {"type": "read_receipt", "message_ids": [1, 2, 3]}
        # Server marks those messages read in DB and broadcasts so the
        # sender's UI can flip their ticks to "seen".
        if event_type == "read_receipt":
            message_ids = payload.get("message_ids", [])
            if not isinstance(message_ids, list) or not message_ids:
                await self.send(text_data=json.dumps({"error": "read_receipt requires non-empty message_ids list"}))
                return

            # Only mark as read if the current user is NOT the sender
            marked_ids = await self._mark_messages_read(message_ids)

            if marked_ids:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat.read",
                        "reader_id": self.user.id,
                        "reader_username": self.user.username,
                        "message_ids": marked_ids,
                    },
                )
            return

        message_text = (payload.get("message") or "").strip()
        if not message_text:
            return

        message_type = payload.get("message_type", "text")
        saved = await self._persist_message(message_text, message_type)
        if not saved:
            await self.send(text_data=json.dumps({"error": "save_failed"}))
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat.message",
                "message": {
                    "id": saved["id"],
                    "sender": self.user.username,
                    "sender_id": self.user.id,
                    "message": saved["content"],
                    "message_type": message_type,
                    "room_name": self.room_name_raw,
                    "timestamp": saved["timestamp"],
                },
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({"type": "chat.message", "message": event["message"]}))

    async def chat_typing(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "typing",
                    "user_id": event["user_id"],
                    "username": event["username"],
                    "is_typing": event["is_typing"],
                }
            )
        )

    async def chat_read(self, event):
        """
        Broadcast read-receipt to all members of the room.
        Clients use this to flip single/double-tick → blue-tick (seen) indicators.
        Payload sent to each WebSocket client:
          {
            "type": "read_receipt",
            "reader_id": <int>,
            "reader_username": "<str>",
            "message_ids": [<int>, ...]
          }
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "read_receipt",
                    "reader_id": event["reader_id"],
                    "reader_username": event["reader_username"],
                    "message_ids": event["message_ids"],
                }
            )
        )

    # ------------------------------------------------------------------ DB
    @database_sync_to_async
    def _user_is_member(self, room_name, user_id):
        try:
            room = models.ChatRoom.objects.get(room_name=room_name, is_active=True)
            return room.members.filter(pk=user_id).exists()
        except models.ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def _get_or_create_room(self, room_name):
        room, _ = models.ChatRoom.objects.get_or_create(
            room_name=room_name,
            defaults={"room_type": "group"},
        )
        return room

    @database_sync_to_async
    def _ensure_membership(self, room_id, user_id):
        room = models.ChatRoom.objects.get(pk=room_id)
        room.members.add(user_id)

    @database_sync_to_async
    def _set_typing(self, is_typing: bool):
        try:
            room = models.ChatRoom.objects.get(room_name=self.room_name_raw)
            models.TypingIndicator.objects.update_or_create(
                chatroom=room,
                user_id=self.user.id,
                defaults={"is_typing": is_typing},
            )
        except models.ChatRoom.DoesNotExist:
            pass

    @database_sync_to_async
    def _mark_messages_read(self, message_ids: list) -> list:
        """
        Mark a list of messages as is_read=True for the current reader.

        Only messages:
          - Belonging to this chatroom
          - NOT sent by the current user (you can't mark your own as "read by you")
          - Not already marked as read

        Returns the IDs that were actually updated so the broadcast is accurate.
        """
        try:
            room = models.ChatRoom.objects.get(room_name=self.room_name_raw)
        except models.ChatRoom.DoesNotExist:
            return []

        # Filter to safe, valid IDs in this room that are unread and not from this user
        qs = models.Message.objects.filter(
            id__in=message_ids,
            chatroom=room,
            is_read=False,
        ).exclude(sender_id=self.user.id)

        updated_ids = list(qs.values_list("id", flat=True))
        if updated_ids:
            qs.update(is_read=True)

        return updated_ids

    @database_sync_to_async
    def _persist_message(self, content: str, message_type: str = "text") -> dict:
        """
        Prefer gRPC microservice for delivery; fall back to local ORM
        so WebSockets still work if the gRPC service is down.
        """
        try:
            room = models.ChatRoom.objects.get(room_name=self.room_name_raw)
        except models.ChatRoom.DoesNotExist:
            return None

        # Try gRPC first (low-latency microservice path)
        try:
            from chatapp.grpc_client import send_message as grpc_send

            result = grpc_send(
                room_id=room.id,
                sender_id=self.user.id,
                content=content,
                message_type=message_type,
            )
            if result.get("ok"):
                return {
                    "id": result["message_id"],
                    "content": result.get("content") or content,
                    "timestamp": result.get("timestamp") or timezone.now().isoformat(),
                }
        except Exception as exc:
            logger.debug("gRPC path unavailable: %s", exc)

        # Local PostgreSQL persistence fallback
        msg = models.Message.objects.create(
            chatroom=room,
            sender_id=self.user.id,
            content=content,
            message_type=message_type or "text",
        )
        try:
            plain = msg.decrypt_content()
        except Exception:
            plain = content
        return {
            "id": msg.id,
            "content": plain,
            "timestamp": msg.timestamp.isoformat(),
        }


class PresenceConsumer(AsyncWebsocketConsumer):
    """
    Global presence channel.
    - On connect: mark user online, broadcast to presence_global
    - On disconnect: mark user offline, broadcast last_seen
    """

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(PRESENCE_GROUP, self.channel_name)
        await self.accept()
        await self._set_online(True)
        await self.channel_layer.group_send(
            PRESENCE_GROUP,
            {
                "type": "presence.update",
                "user_id": self.user.id,
                "username": self.user.username,
                "is_online": True,
                "last_seen": timezone.now().isoformat(),
            },
        )

    async def disconnect(self, close_code):
        if not hasattr(self, "user") or not getattr(self.user, "is_authenticated", False):
            return
        await self._set_online(False)
        last_seen = timezone.now().isoformat()
        await self.channel_layer.group_send(
            PRESENCE_GROUP,
            {
                "type": "presence.update",
                "user_id": self.user.id,
                "username": self.user.username,
                "is_online": False,
                "last_seen": last_seen,
            },
        )
        await self.channel_layer.group_discard(PRESENCE_GROUP, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Optional heartbeat / typing-style pings from client."""
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if payload.get("type") == "heartbeat":
            await self._set_online(True)
            await self.send(text_data=json.dumps({"type": "heartbeat.ack"}))

    async def presence_update(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "presence",
                    "user_id": event["user_id"],
                    "username": event["username"],
                    "is_online": event["is_online"],
                    "last_seen": event["last_seen"],
                }
            )
        )

    @database_sync_to_async
    def _set_online(self, online: bool):
        models.UserStatus.objects.update_or_create(
            user_id=self.user.id,
            defaults={
                "is_online": online,
                "last_seen": timezone.now(),
            },
        )
