"""Fires trade-setup-triggered alerts to the standalone notification-service.

Calls out over plain HTTP (`POST /api/v1/notifications`) — no import
dependency on the notification-service code, same as any external caller.
A single in-process dedup cache stops the same breakout from re-notifying on
every watchlist poll (the intraday endpoints are polled every few seconds).
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from app.config import get_settings
from app.schemas.stock import IntradaySnapshot

logger = logging.getLogger(__name__)

_DEDUP_TTL_SECONDS = 24 * 60 * 60  # one trigger notification per symbol per calendar day


class _DedupCache:
    """Tracks which (symbol, trigger-day) pairs have already been notified."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_notify(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < _DEDUP_TTL_SECONDS:
                return False
            self._seen[key] = now
            return True


_dedup = _DedupCache()


def _format_message(snapshot: IntradaySnapshot) -> tuple[str, str]:
    """Builds a Telegram-HTML-formatted body (bold/code/emoji render nicely
    in the live channel; other channels just display it as plain text)."""
    setup = snapshot.tradeSetup
    sl_distance = abs(snapshot.currentPrice - setup.stopLoss)
    sl_distance_pct = round((sl_distance / setup.stopLoss) * 100, 2) if setup.stopLoss else 0.0
    action_emoji = "🟢" if setup.action == "buy" else "🔴"

    title = f"{action_emoji} {snapshot.symbol} · {setup.action.upper()} setup triggered"
    lines = [
        f"<b>{setup.bias.upper()}</b> setup on <b>{snapshot.symbol}</b>",
        "━━━━━━━━━━━━━━━",
        f"💰 Price: <b>₹{snapshot.currentPrice:,.2f}</b>",
        f"📍 Entry: <code>₹{setup.entry:,.2f}</code>",
        f"🛑 Stop-Loss: <code>₹{setup.stopLoss:,.2f}</code> (Δ ₹{sl_distance:,.2f} · {sl_distance_pct:.2f}% away)",
        f"🏁 Target: <code>₹{setup.target:,.2f}</code>",
        f"⚖️ Risk:Reward: <b>{setup.riskRewardRatio}</b>",
    ]
    return title, "\n".join(lines)


def notify_trade_setup_triggered(snapshot: IntradaySnapshot) -> None:
    """Best-effort notify. Never raises — a notification-service outage must
    not break watchlist polling for the caller."""
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup.triggeredAt is None or setup.action not in ("buy", "sell"):
        return

    dedup_key = f"{snapshot.symbol}:{setup.action}:{setup.triggeredAt.date().isoformat()}"
    if not _dedup.should_notify(dedup_key):
        return

    title, message = _format_message(snapshot)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": settings.notification_telegram_chat_id},
        "title": title,
        "data": message,
        "reference": f"trigger-{snapshot.symbol}-{setup.triggeredAt.date().isoformat()}",
        "metadata": {"source": "pivotiq-backend", "symbol": snapshot.symbol, "action": setup.action},
    }

    try:
        response = requests.post(
            f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications",
            json=payload,
            timeout=5,
        )
        if not response.ok:
            logger.warning(
                "notification-service rejected trigger alert for %s: HTTP %s %s",
                snapshot.symbol, response.status_code, response.text,
            )
    except requests.RequestException:
        logger.exception("failed to reach notification-service for %s trigger alert", snapshot.symbol)
