"""
ASGI entrypoint — HTTP + WebSocket routing for the real-time chat service.

WebSocket auth stack (innermost → outermost):
  URLRouter              – routes to consumers
  JWTAuthMiddleware      – reads ?token= or Authorization: Bearer <jwt>
                           and sets scope["user"]; falls back to session user
  AuthMiddlewareStack    – populates scope["user"] from Django session cookie
                           (covers browser / template clients)
  AllowedHostsOriginValidator – guards against cross-origin WebSocket abuse
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myprojects.settings")

django_asgi_app = get_asgi_application()

from chatapp import routing  # noqa: E402  (must be after Django setup)
from chatapp.middleware import JWTAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            # AuthMiddlewareStack sets scope["user"] from session cookie.
            # JWTAuthMiddleware then overrides it when a Bearer token is present.
            AuthMiddlewareStack(
                JWTAuthMiddleware(
                    URLRouter(routing.websocket_urlpatterns)
                )
            )
        ),
    }
)
