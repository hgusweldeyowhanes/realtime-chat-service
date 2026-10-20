"""
Celery background tasks for the real-time chat service.

Tasks:
- send_push_notification_task: Dispatches FCM push notifications asynchronously for new messages.
- send_user_notification_task: Dispatches direct push notifications to a specific user.
"""
import logging
from typing import Any, Dict, Optional

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="chatapp.tasks.send_push_notification_task",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def send_push_notification_task(self, message_id: int) -> Dict[str, Any]:
    """
    Celery task to send push notification to chatroom members for a given message.
    """
    from chatapp.fcm import notify_room_members_of_message

    logger.info("Executing send_push_notification_task for message_id=%s", message_id)
    try:
        result = notify_room_members_of_message(message_id)
        logger.info("send_push_notification_task finished: %r", result)
        return result
    except Exception as exc:
        logger.error("Error in send_push_notification_task (message_id=%s): %s", message_id, exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("Max retries exceeded for message_id=%s", message_id)
            return {"error": str(exc), "max_retries_exceeded": True}


@shared_task(name="chatapp.tasks.send_user_notification_task")
def send_user_notification_task(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task to send a push notification directly to all registered devices of a user.
    """
    from chatapp.fcm import send_fcm_notification
    from chatapp.models import FCMDevice

    tokens = list(
        FCMDevice.objects.filter(user_id=user_id, is_active=True).values_list(
            "registration_token", flat=True
        )
    )
    if not tokens:
        return {"info": "no_registered_devices", "user_id": user_id}

    return send_fcm_notification(
        registration_tokens=tokens,
        title=title,
        body=body,
        data=data or {},
    )
