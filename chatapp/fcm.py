"""
Firebase Cloud Messaging (FCM) push notification service.

Supports:
- Multicast push notifications to Android, iOS, and Web devices.
- Automatic deactivation of invalid/unregistered tokens.
- Mute settings and blocked user filtering.
- Dry-run / mock fallback when FCM credentials are not configured (local dev & testing).
"""
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q

logger = logging.getLogger(__name__)

FCM_SEND_URL = "https://fcm.googleapis.com/fcm/send"


def send_fcm_notification(
    registration_tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send an FCM push notification to a list of device registration tokens.
    """
    if not registration_tokens:
        return {"success": 0, "failure": 0, "results": []}

    tokens = list(dict.fromkeys(registration_tokens))  # deduplicate preserving order
    server_key = getattr(settings, "FCM_SERVER_KEY", "") or ""

    if not server_key:
        logger.info(
            "FCM [Dry Run / Not Configured]: title=%r, body=%r, tokens=%d, data=%r",
            title,
            body,
            len(tokens),
            data,
        )
        return {
            "success": len(tokens),
            "failure": 0,
            "multicast_id": 0,
            "results": [{"message_id": f"mock-{i}"} for i in range(len(tokens))],
            "dry_run": True,
        }

    headers = {
        "Authorization": f"key={server_key}",
        "Content-Type": "application/json",
    }
    # Strings in data payload for FCM compatibility
    safe_data = {str(k): str(v) for k, v in (data or {}).items()}

    payload = {
        "registration_ids": tokens,
        "notification": {
            "title": title,
            "body": body,
            "sound": "default",
        },
        "data": safe_data,
        "priority": "high",
    }

    try:
        response = requests.post(FCM_SEND_URL, json=payload, headers=headers, timeout=10)
        res_json = response.json() if response.status_code == 200 else {}

        # Deactivate invalid or unregistered tokens if returned by FCM
        if response.status_code == 200 and "results" in res_json:
            _handle_fcm_results(tokens, res_json.get("results", []))

        return res_json or {"status_code": response.status_code, "text": response.text}
    except Exception as exc:
        logger.error("Failed to send FCM push notification: %s", exc)
        return {"error": str(exc), "success": 0, "failure": len(tokens)}


def _handle_fcm_results(tokens: List[str], results: List[Dict[str, Any]]) -> None:
    """
    Inspect FCM response and deactivate invalid/expired tokens.
    """
    from chatapp.models import FCMDevice

    invalid_tokens = []
    for idx, result in enumerate(results):
        err = result.get("error")
        if err in {"NotRegistered", "InvalidRegistration", "MismatchSenderId"}:
            if idx < len(tokens):
                invalid_tokens.append(tokens[idx])

    if invalid_tokens:
        logger.info("Deactivating %d invalid FCM tokens", len(invalid_tokens))
        FCMDevice.objects.filter(registration_token__in=invalid_tokens).update(is_active=False)


def notify_room_members_of_message(message_id: int) -> Dict[str, Any]:
    """
    Prepare and send push notifications to eligible members of a chatroom
    when a new message is posted.

    Excludes:
    - The message sender
    - Users who blocked the sender (or whom sender blocked)
    - Users who muted notifications for this chatroom
    - Deactivated/inactive device tokens
    """
    from chatapp.models import BlockedUser, ChatRoomSettings, FCMDevice, Message

    try:
        message = (
            Message.objects.select_related("sender", "chatroom")
            .prefetch_related("chatroom__members")
            .get(id=message_id)
        )
    except Message.DoesNotExist:
        logger.warning("Message %s not found for push notification", message_id)
        return {"error": "message_not_found"}

    if message.is_deleted:
        return {"info": "message_is_deleted"}

    chatroom = message.chatroom
    sender = message.sender

    # Eligible members (excluding sender)
    candidate_users = list(chatroom.members.exclude(id=sender.id))
    if not candidate_users:
        return {"info": "no_other_members", "recipient_count": 0}

    # Filter out users with mutual blocks
    blocked_user_ids = set(
        BlockedUser.objects.filter(
            Q(blocker=sender, blocked__in=candidate_users)
            | Q(blocker__in=candidate_users, blocked=sender)
        ).values_list("blocker_id", "blocked_id")
    )
    excluded_by_block = set()
    for b_er, b_ed in blocked_user_ids:
        if b_er == sender.id:
            excluded_by_block.add(b_ed)
        else:
            excluded_by_block.add(b_er)

    # Filter out users who muted this room
    muted_user_ids = set()
    try:
        room_settings = ChatRoomSettings.objects.filter(chatroom=chatroom, mute_notifications=True)
        if room_settings.exists():
            # In ChatRoomSettings, oneToOne relates chatroom to settings
            # If muted, all members of that chatroom have muted notifications
            muted_user_ids = {u.id for u in candidate_users}
    except Exception:
        pass

    recipients = [
        u
        for u in candidate_users
        if u.id not in excluded_by_block and u.id not in muted_user_ids
    ]
    if not recipients:
        return {"info": "all_recipients_muted_or_blocked", "recipient_count": 0}

    # Decrypt message content
    try:
        decrypted = message.decrypt_content() or ""
    except Exception:
        decrypted = ""

    # Build title and body
    if chatroom.room_type == "group":
        title = f"{sender.username} in {chatroom.room_name or 'Group'}"
    else:
        title = sender.username

    if decrypted:
        body = decrypted[:120]
        if message.attachment:
            body += " [Attachment]"
    elif message.attachment:
        filename = os.path.basename(message.attachment.name)
        body = f"Sent a {message.message_type}: {filename}"
    else:
        body = f"Sent a {message.message_type}"

    # Build data payload
    data_payload = {
        "chatroom_id": str(chatroom.id),
        "room_name": str(chatroom.room_name),
        "message_id": str(message.id),
        "sender_id": str(sender.id),
        "sender_username": sender.username,
        "message_type": str(message.message_type),
        "timestamp": message.timestamp.isoformat(),
        "attachment_url": message.attachment.url if message.attachment else "",
    }

    # Fetch active device tokens
    tokens = list(
        FCMDevice.objects.filter(user__in=recipients, is_active=True).values_list(
            "registration_token", flat=True
        )
    )

    if not tokens:
        return {"info": "no_registered_devices", "recipient_count": len(recipients)}

    result = send_fcm_notification(
        registration_tokens=tokens,
        title=title,
        body=body,
        data=data_payload,
    )
    return {
        "success": True,
        "recipient_count": len(recipients),
        "tokens_count": len(tokens),
        "fcm_result": result,
    }
