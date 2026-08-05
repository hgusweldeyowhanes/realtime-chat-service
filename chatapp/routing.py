from django.urls import path, re_path

from chatapp.consumers import ChatConsumer, PresenceConsumer

websocket_urlpatterns = [
    # Real-time one-to-one / group chat room
    path("ws/chat/<str:room_name>/", ChatConsumer.as_asgi()),
    # Backwards-compatible path used by existing templates
    path("ws/notification/<str:room_name>/", ChatConsumer.as_asgi()),
    # Global presence tracking
    re_path(r"^ws/presence/$", PresenceConsumer.as_asgi()),
]
