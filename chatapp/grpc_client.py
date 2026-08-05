"""
Thin gRPC client used by the Django web service to talk to the
chat-delivery microservice for low-latency send/fetch/presence.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import grpc

logger = logging.getLogger(__name__)


def _channel():
    host = os.getenv("GRPC_HOST", "localhost")
    port = os.getenv("GRPC_PORT", "50051")
    return grpc.insecure_channel(f"{host}:{port}")


def _stubs():
    # Generated stubs live in grpc_service/
    from grpc_service import chat_pb2, chat_pb2_grpc

    return chat_pb2, chat_pb2_grpc


def send_message(
    room_id: int,
    sender_id: int,
    content: str,
    message_type: str = "text",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Send a chat message through the gRPC delivery service."""
    chat_pb2, chat_pb2_grpc = _stubs()
    try:
        with _channel() as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            resp = stub.SendMessage(
                chat_pb2.SendMessageRequest(
                    room_id=room_id,
                    sender_id=sender_id,
                    content=content,
                    message_type=message_type,
                ),
                timeout=timeout,
            )
            return {
                "ok": resp.ok,
                "message_id": resp.message_id,
                "content": resp.content,
                "timestamp": resp.timestamp,
                "error": resp.error or None,
            }
    except Exception as exc:
        logger.warning("gRPC send_message failed, falling back to local ORM: %s", exc)
        return {"ok": False, "error": str(exc)}


def get_messages(room_id: int, limit: int = 50, timeout: float = 5.0) -> List[Dict[str, Any]]:
    chat_pb2, chat_pb2_grpc = _stubs()
    try:
        with _channel() as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            resp = stub.GetMessages(
                chat_pb2.GetMessagesRequest(room_id=room_id, limit=limit),
                timeout=timeout,
            )
            if resp.error:
                raise RuntimeError(resp.error)
            return [
                {
                    "id": m.id,
                    "room_id": m.room_id,
                    "sender_id": m.sender_id,
                    "sender_username": m.sender_username,
                    "content": m.content,
                    "message_type": m.message_type,
                    "timestamp": m.timestamp,
                    "is_read": m.is_read,
                }
                for m in resp.messages
            ]
    except Exception as exc:
        logger.warning("gRPC get_messages failed: %s", exc)
        return []


def get_presence(user_ids: Optional[List[int]] = None, timeout: float = 5.0) -> List[Dict[str, Any]]:
    chat_pb2, chat_pb2_grpc = _stubs()
    try:
        with _channel() as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            req = chat_pb2.GetPresenceRequest(user_ids=user_ids or [])
            resp = stub.GetPresence(req, timeout=timeout)
            return [
                {
                    "user_id": u.user_id,
                    "username": u.username,
                    "is_online": u.is_online,
                    "last_seen": u.last_seen,
                }
                for u in resp.users
            ]
    except Exception as exc:
        logger.warning("gRPC get_presence failed: %s", exc)
        return []
