"""Live Telegram channel — sends via the Telegram Bot HTTP API.

Requires `TELEGRAM_BOT_TOKEN` (create a bot with @BotFather) and the
recipient's `telegramChatId` (the chat id the bot is allowed to message —
obtained by having the user DM the bot and reading `getUpdates`, or via a
deep link/start payload).

Uses Telegram's HTML `parse_mode` — `title`/`data` may contain Telegram's
supported tags (`<b>`, `<i>`, `<code>`, `<blockquote>`, emoji, ...) for a
richer layout than plain Markdown allows. Callers passing plain text still
render fine since untagged text is just displayed as-is.
"""

import logging

import requests

from app.channels.base import NotificationSender, SendResult
from app.models.notification import Recipient

logger = logging.getLogger(__name__)


class TelegramSender(NotificationSender):
    def __init__(self, bot_token: str, api_base_url: str) -> None:
        self._bot_token = bot_token
        self._api_base_url = api_base_url.rstrip("/")

    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        if not self._bot_token:
            return SendResult(success=False, error="TELEGRAM_BOT_TOKEN is not configured")
        if not recipient.telegram_chat_id:
            return SendResult(success=False, error="recipient.telegramChatId is required for the telegram channel")

        text = f"<b>{title}</b>\n{data}\n\n<i>ref: {reference}</i>"
        url = f"{self._api_base_url}/bot{self._bot_token}/sendMessage"

        try:
            response = requests.post(
                url,
                json={
                    "chat_id": recipient.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            payload = response.json()
        except requests.RequestException as exc:
            logger.exception("telegram send failed for ref=%s", reference)
            return SendResult(success=False, error=str(exc))

        if not response.ok or not payload.get("ok"):
            error = payload.get("description", f"HTTP {response.status_code}")
            logger.warning("telegram API rejected message for ref=%s: %s", reference, error)
            return SendResult(success=False, error=error)

        message_id = str(payload["result"]["message_id"])
        return SendResult(success=True, provider_message_id=message_id)
