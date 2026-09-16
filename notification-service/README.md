# Notification Hub

Standalone notification microservice. Any external system can call one HTTP
API to send a notification over **Telegram** (live), **normal SMS**,
**WhatsApp**, **Email**, or **RCS** — regardless of the caller's own stack.

## Why standalone

It has its own FastAPI app, own `requirements.txt`, own `Dockerfile`, and no
import dependency on `backend/` or `frontend/`. Any service in this repo (or
outside it) integrates purely over HTTP.

## Architecture

```
Caller ──POST /api/v1/notifications──▶ API layer
                                          │  1. validate + log
                                          │  2. persist record (status=PENDING per channel)
                                          │  3. publish to queue
                                          ▼
                                   MessageQueue (in-memory today;
                                   swap for RabbitMQ/Kafka later behind
                                   the same publish/consume interface)
                                          │
                          NotificationSubscriber (1 dispatcher thread)
                                          │  polls the queue, hands each
                                          │  message to a ThreadPoolExecutor
                                          ▼
                              NotificationProcessor (runs on a pool thread)
                                          │  for each requested channel:
                                          │  send → update per-channel status
                                          ▼
                         ChannelRegistry → TelegramSender / EmailSender /
                                           WhatsAppSender / SmsSender / RcsSender
```

Every layer is behind a small interface (`MessageQueue`, `NotificationStore`,
`NotificationSender`) so the in-memory pieces can be swapped later (RabbitMQ,
Kafka, Postgres/Mongo, real WhatsApp/RCS providers) without touching callers.

## Channels

| Channel    | Status | Notes |
|---|---|---|
| `telegram` | **Live** | Sends via the Telegram Bot API. Requires `TELEGRAM_BOT_TOKEN` and the recipient's `telegramChatId`. |
| `email`    | Live if SMTP configured, else simulated (logged) | Set `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD`. |
| `normal` (SMS) | Simulated | Logs the outbound message; swap `SmsSender` for a real gateway later. |
| `whatsapp` | Simulated | Same as above. |
| `rcs`      | Simulated | Same as above. |

## Setting up the Telegram bot

1. Message `@BotFather` on Telegram, `/newbot`, follow the prompts to get a bot token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env`.
3. Have the recipient start a chat with the bot, then read `https://api.telegram.org/bot<token>/getUpdates` to find their `chat.id`.
4. Pass that id as `recipient.telegramChatId` in requests.

## Run locally

```powershell
cd notification-service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 4500
```

## API

### `POST /api/v1/notifications`

```json
{
  "channels": ["telegram", "email"],
  "recipient": {
    "name": "Jane",
    "email": "jane@example.com",
    "telegramChatId": "123456789"
  },
  "title": "Order shipped",
  "data": "Your order #4821 has shipped and will arrive in 2 days.",
  "reference": "order-4821",
  "metadata": { "source": "orders-service" }
}
```

Response `202 Accepted`:

```json
{ "notf_req_id": "5b1c...", "status": "ACCEPTED", "accepted_at": "2026-09-16T10:00:00Z" }
```

### `GET /api/v1/notifications/{notf_req_id}`

Returns overall status plus a per-channel breakdown (`PENDING` → `PROCESSING`
→ `SENT`/`FAILED`), so a single `notf_req_id` can track multiple channels
independently.

```json
{
  "notf_req_id": "5b1c...",
  "reference": "order-4821",
  "overall_status": "PARTIALLY_SENT",
  "channels": [
    { "channel": "telegram", "status": "SENT", "provider_message_id": "981", "error": null },
    { "channel": "email", "status": "FAILED", "provider_message_id": null, "error": "recipient.email is required" }
  ],
  "created_at": "2026-09-16T10:00:00Z",
  "updated_at": "2026-09-16T10:00:01Z"
}
```

## Swapping the queue later

Replace `InMemoryQueue` with a `RabbitMqQueue`/`KafkaQueue` implementing
`MessageQueue` (`publish`, `consume`, `size`) and wire it in `app/main.py` —
`NotificationService` and `NotificationSubscriber` don't change.
