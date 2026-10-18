"""
JWT WebSocket Authentication Middleware.

Standard Django session auth does NOT work for WebSocket clients that use
JWT Bearer tokens (React, mobile apps, etc.). This middleware reads the token
from:

  1. The `token` query-string parameter:  ws://host/ws/chat/room/?token=<jwt>
  2. The `Authorization` header (when the upgrade request carries it):
     Authorization: Bearer <jwt>

It then resolves the user and injects it into `scope["user"]`, so the existing
`scope["user"].is_authenticated` checks in ChatConsumer and PresenceConsumer
work transparently for both session-auth and JWT-auth clients.

Usage in asgi.py:
    from chatapp.middleware import JWTAuthMiddleware
    application = ProtocolTypeRouter({
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddleware(URLRouter(routing.websocket_urlpatterns))
        ),
    })
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


@database_sync_to_async
def _get_user_from_token(token_str: str):
    """
    Validate the JWT access token and return the corresponding User.
    Returns AnonymousUser on any validation failure so the consumer can
    close with code 4001 cleanly.
    """
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth import get_user_model

        User = get_user_model()
        token = AccessToken(token_str)
        user_id = token["user_id"]
        return User.objects.get(pk=user_id)
    except Exception as exc:
        logger.debug("JWT WS auth failed: %s", exc)
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    ASGI middleware that authenticates WebSocket connections via JWT.

    Falls back to Django's session/cookie user if no token is provided,
    so session-auth browser clients continue to work alongside API clients.
    """

    async def __call__(self, scope, receive, send):
        # Only process WebSocket scopes
        if scope["type"] != "websocket":
            return await super().__call__(scope, receive, send)

        # --- 1. Try query-string token first ---
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token_list = params.get("token", [])

        if token_list:
            scope["user"] = await _get_user_from_token(token_list[0])
            return await super().__call__(scope, receive, send)

        # --- 2. Try Authorization header ---
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.lower().startswith("bearer "):
            token_str = auth_header.split(" ", 1)[1].strip()
            scope["user"] = await _get_user_from_token(token_str)
            return await super().__call__(scope, receive, send)

        # --- 3. Fall back to existing session user (set by AuthMiddlewareStack) ---
        # scope["user"] is already populated by channels' AuthMiddlewareStack
        # if it was wrapping this middleware. If not set, default to Anonymous.
        if "user" not in scope:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
