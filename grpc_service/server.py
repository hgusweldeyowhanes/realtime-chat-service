"""
gRPC Chat microservice.

Persists messages in PostgreSQL (via Django ORM) and serves low-latency
unary + streaming RPCs for SendMessage, GetMessages, and GetPresence.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from concurrent import futures
from pathlib import Path

import django
import grpc

# ---------------------------------------------------------------------------
# Bootstrap Django so the ORM works inside this process
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myprojects.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from chatapp import models  # noqa: E402
from grpc_service import chat_pb2, chat_pb2_grpc  # noqa: E402

logger = logging.getLogger("grpc.chat")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _decrypt_or_plain(message: models.Message) -> str:
    try:
        return message.decrypt_content()
    except Exception:
        return message.content or ""


class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    def SendMessage(self, request, context):
        try:
            room = models.ChatRoom.objects.get(pk=request.room_id, is_active=True)
            sender = User.objects.get(pk=request.sender_id)

            if not room.members.filter(pk=sender.pk).exists():
                return chat_pb2.SendMessageResponse(
                    ok=False, error="Sender is not a member of this room"
                )

            msg_type = request.message_type or "text"
            message = models.Message.objects.create(
                chatroom=room,
                sender=sender,
                content=request.content,
                message_type=msg_type,
            )
            plain = _decrypt_or_plain(message)

            logger.info(
                "SendMessage room=%s sender=%s id=%s",
                room.id,
                sender.username,
                message.id,
            )
            return chat_pb2.SendMessageResponse(
                ok=True,
                message_id=message.id,
                content=plain,
                timestamp=message.timestamp.isoformat(),
            )
        except models.ChatRoom.DoesNotExist:
            return chat_pb2.SendMessageResponse(ok=False, error="Room not found")
        except User.DoesNotExist:
            return chat_pb2.SendMessageResponse(ok=False, error="Sender not found")
        except Exception as exc:
            logger.exception("SendMessage failed")
            return chat_pb2.SendMessageResponse(ok=False, error=str(exc))

    def GetMessages(self, request, context):
        try:
            limit = request.limit if request.limit and request.limit > 0 else 50
            qs = (
                models.Message.objects.filter(
                    chatroom_id=request.room_id, is_deleted=False
                )
                .select_related("sender")
                .order_by("-timestamp")[:limit]
            )
            items = []
            for m in reversed(list(qs)):
                items.append(
                    chat_pb2.MessageItem(
                        id=m.id,
                        room_id=m.chatroom_id,
                        sender_id=m.sender_id,
                        sender_username=m.sender.username,
                        content=_decrypt_or_plain(m),
                        message_type=m.message_type,
                        timestamp=m.timestamp.isoformat(),
                        is_read=m.is_read,
                    )
                )
            return chat_pb2.GetMessagesResponse(messages=items)
        except Exception as exc:
            logger.exception("GetMessages failed")
            return chat_pb2.GetMessagesResponse(error=str(exc))

    def GetPresence(self, request, context):
        try:
            user_ids = list(request.user_ids) or []
            qs = models.UserStatus.objects.select_related("user")
            if user_ids:
                qs = qs.filter(user_id__in=user_ids)

            items = []
            for status in qs[:200]:
                items.append(
                    chat_pb2.PresenceItem(
                        user_id=status.user_id,
                        username=status.user.username,
                        is_online=status.is_online,
                        last_seen=status.last_seen.isoformat() if status.last_seen else "",
                    )
                )
            return chat_pb2.GetPresenceResponse(users=items)
        except Exception as exc:
            logger.exception("GetPresence failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return chat_pb2.GetPresenceResponse()

    def StreamRoom(self, request, context):
        """
        Lightweight polling stream of new messages for a room.
        Clients receive RoomEvent updates every second while connected.
        """
        last_id = 0
        while context.is_active():
            qs = (
                models.Message.objects.filter(
                    chatroom_id=request.room_id, is_deleted=False, id__gt=last_id
                )
                .select_related("sender")
                .order_by("id")[:50]
            )
            for m in qs:
                last_id = m.id
                yield chat_pb2.RoomEvent(
                    event_type="message",
                    message=chat_pb2.MessageItem(
                        id=m.id,
                        room_id=m.chatroom_id,
                        sender_id=m.sender_id,
                        sender_username=m.sender.username,
                        content=_decrypt_or_plain(m),
                        message_type=m.message_type,
                        timestamp=m.timestamp.isoformat(),
                        is_read=m.is_read,
                    ),
                )
            time.sleep(1.0)


def serve() -> None:
    port = os.getenv("GRPC_PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("gRPC ChatService listening on :%s", port)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
