# Real-Time Chat Service

A real-time messaging backend supporting **one-to-one** and **group** chats with
**WebSockets** and **gRPC** for low-latency delivery. Features presence tracking,
message persistence in **PostgreSQL**, and containerized microservices.

| Layer | Technology |
|-------|------------|
| API & auth | Django + DRF + JWT |
| Real-time | Django Channels WebSockets |
| Low-latency path | gRPC microservice |
| Persistence | PostgreSQL |
| Channel layer | Redis |
| Packaging | Docker Compose |

---

## Architecture

```
┌──────────────┐     WebSocket      ┌─────────────────────┐
│   Clients    │ ────────────────── │  web (Daphne+Django) │
└──────────────┘                    │  REST + WS + presence│
                                    └──────────┬──────────┘
                                               │ gRPC
                                    ┌──────────▼──────────┐
                                    │  grpc ChatService    │
                                    │  Send / Get / Stream │
                                    └──────────┬──────────┘
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         │                     │                     │
                    ┌────▼────┐           ┌────▼────┐
                    │ Postgres│           │  Redis  │
                    │ messages│           │ channels│
                    └─────────┘           └─────────┘
```

### Services (Docker Compose)

| Service | Port | Role |
|---------|------|------|
| `web` | 8000 | Django REST + Daphne WebSockets |
| `grpc` | 50051 | gRPC message delivery microservice |
| `db` | 5432 | PostgreSQL persistence |
| `redis` | 6379 | Channels channel layer |

---

## Features

- **One-to-one & group chat rooms** (`ChatRoom.room_type`: `private` | `group`)
- **WebSockets** for live fan-out (`ws/chat/<room>/`, `ws/presence/`)
- **gRPC** unary + streaming RPCs for low-latency send/get/presence
- **Presence tracking** (online / offline / last_seen via `UserStatus`)
- **Encrypted message storage** (Fernet) in PostgreSQL
- **Typing indicators**, reactions, soft-delete, archive

---

## Quick start with Docker

```bash
# 1. Copy env template
cp .env.example .env

# 2. Build and start all microservices
docker compose up --build

# 3. Create a superuser (optional)
docker compose exec web python manage.py createsuperuser
```

- HTTP / WebSocket: http://localhost:8000  
- gRPC: localhost:50051  

---

## Local development (without Docker)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt

# Generate gRPC stubs
python -m grpc_service.generate_stubs

# SQLite mode: leave POSTGRES_HOST empty in .env
# Or run Postgres/Redis and set vars from .env.example

python manage.py migrate
daphne -b 0.0.0.0 -p 8000 myprojects.asgi:application

# In another terminal — gRPC service
python -m grpc_service.server
```

---

## WebSocket API

### Chat room

```
ws://localhost:8000/ws/chat/<room_name>/
```

**Send message**
```json
{"type": "chat.message", "message": "hello", "message_type": "text"}
```

**Typing**
```json
{"type": "typing", "is_typing": true}
```

**Receive**
```json
{
  "type": "chat.message",
  "message": {
    "id": 1,
    "sender": "alice",
    "sender_id": 2,
    "message": "hello",
    "timestamp": "2026-08-05T12:00:00+00:00"
  }
}
```

### Presence

```
ws://localhost:8000/ws/presence/
```

Broadcast event:
```json
{
  "type": "presence",
  "user_id": 2,
  "username": "alice",
  "is_online": true,
  "last_seen": "2026-08-05T12:00:00+00:00"
}
```

Heartbeat:
```json
{"type": "heartbeat"}
```

---

## gRPC API

Proto: `grpc_service/proto/chat.proto`

| RPC | Purpose |
|-----|---------|
| `SendMessage` | Persist + return message |
| `GetMessages` | Recent messages for a room |
| `GetPresence` | Online status for user IDs |
| `StreamRoom` | Server-stream new room events |

Regenerate stubs after editing the proto:

```bash
python -m grpc_service.generate_stubs
```

The Django web service calls gRPC via `chatapp/grpc_client.py` and falls back to
the local ORM if the gRPC service is unreachable.

---

## REST highlights

| Method | Path | Description |
|--------|------|-------------|
| POST | `/token/` | JWT obtain |
| GET/POST | `/chatrooms/` | List / create rooms |
| GET/POST | `/chatrooms/<id>/messages/` | Messages |
| GET/PATCH | `/user-status/` | Presence records |

---

## Project layout

```
realtime-chat-service/
├── chatapp/                 # Django app (models, WS consumers, REST)
│   ├── consumers.py         # WebSocket chat + presence
│   ├── grpc_client.py       # Client to gRPC microservice
│   └── models.py            # ChatRoom, Message, UserStatus, ...
├── grpc_service/            # gRPC microservice
│   ├── proto/chat.proto
│   ├── server.py
│   └── generate_stubs.py
├── myprojects/              # Django project settings / ASGI
├── docker-compose.yml       # web + grpc + postgres + redis
├── Dockerfile
└── requirements.txt
```

---

## Security notes

- Messages are encrypted at rest with Fernet (`ENCRYPTION_KEY`)
- Change `SECRET_KEY` and DB passwords before production
- Prefer Redis + PostgreSQL (not SQLite / InMemory channel layer) in production
