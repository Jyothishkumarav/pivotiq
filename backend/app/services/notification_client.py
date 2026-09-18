"""Fires trade-setup-triggered alerts to the standalone notification-service.

Calls out over plain HTTP (`POST /api/v1/notifications`) — no import
dependency on the notification-service code, same as any external caller.
A shared Redis-backed cache (see `app.services.cache`) stops the same
breakout from re-notifying on every watchlist/details poll (the intraday
endpoints are polled every few seconds) by remembering that a symbol+action
was already triggered for a fixed TTL window.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

import requests

from app.config import get_settings
from app.schemas.stock import IntradaySnapshot
from app.services.cache import get_cache_client

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_TRIGGER_CACHE_TTL_SECONDS = 8 * 60 * 60  # 8h: roughly one trading session


def _trigger_cache_key(symbol: str, action: str) -> str:
    return f"notif:trigger:{symbol.upper()}:{action}"


def _format_message(snapshot: IntradaySnapshot) -> tuple[str, str]:
    """Builds a Telegram-HTML-formatted body (bold/code/emoji render nicely
    in the live channel; other channels just display it as plain text)."""
    setup = snapshot.tradeSetup
    sl_distance = abs(snapshot.currentPrice - setup.stopLoss)
    sl_distance_pct = round((sl_distance / setup.stopLoss) * 100, 2) if setup.stopLoss else 0.0
    action_emoji = "🟢" if setup.action == "buy" else "🔴"

    title = f"{action_emoji} {snapshot.symbol} · {setup.action.upper()} setup triggered"
    triggered_at_ist = setup.triggeredAt.astimezone(_IST).strftime("%d %b %Y, %H:%M:%S IST") if setup.triggeredAt else "—"
    lines = [
        f"<b>{setup.bias.upper()}</b> setup on <b>{snapshot.symbol}</b>",
        "━━━━━━━━━━━━━━━",
        f"💰 Price: <b>₹{snapshot.currentPrice:,.2f}</b>",
        f"📍 Entry: <code>₹{setup.entry:,.2f}</code>",
        f"🛑 Stop-Loss: <code>₹{setup.stopLoss:,.2f}</code> (Δ ₹{sl_distance:,.2f} · {sl_distance_pct:.2f}% away)",
        f"🏁 Target: <code>₹{setup.target:,.2f}</code>",
        f"⚖️ Risk:Reward: <b>{setup.riskRewardRatio}</b>",
        f"🕒 Triggered at: <b>{triggered_at_ist}</b>",
    ]
    return title, "\n".join(lines)


def _format_sl_hit_message(snapshot: IntradaySnapshot) -> tuple[str, str]:
    setup = snapshot.tradeSetup
    title = f"🛑 {snapshot.symbol} · Stop-loss hit — trade failed"
    triggered_at_ist = setup.triggeredAt.astimezone(_IST).strftime("%d %b %Y, %H:%M:%S IST") if setup.triggeredAt else "—"
    sl_hit_at_ist = setup.slHitAt.astimezone(_IST).strftime("%d %b %Y, %H:%M:%S IST") if setup.slHitAt else "—"
    lines = [
        f"<b>{setup.action.upper()}</b> setup on <b>{snapshot.symbol}</b> hit its stop-loss.",
        "━━━━━━━━━━━━━━━",
        f"📍 Entry: <code>₹{setup.entry:,.2f}</code>",
        f"🛑 Stop-Loss: <code>₹{setup.stopLoss:,.2f}</code>",
        f"💰 Price now: <b>₹{snapshot.currentPrice:,.2f}</b>",
        f"🕒 Triggered at: {triggered_at_ist}",
        f"🕒 Stop-loss hit at: <b>{sl_hit_at_ist}</b>",
        "❌ <b>Trade failed.</b>",
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

    cache = get_cache_client()
    cache_key = _trigger_cache_key(snapshot.symbol, setup.action)
    if cache.exists(cache_key):
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
            return
    except requests.RequestException:
        logger.exception("failed to reach notification-service for %s trigger alert", snapshot.symbol)
        return

    # Only cache after a confirmed send, so a failed/rejected request can retry on the next poll.
    cache.set_json(
        cache_key,
        {
            "symbol": snapshot.symbol.upper(),
            "action": setup.action,
            "status": "triggered",
            "entry": setup.entry,
            "stopLoss": setup.stopLoss,
            "target": setup.target,
            "triggeredAt": setup.triggeredAt.isoformat(),
        },
        ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS,
    )


def _sl_hit_cache_key(symbol: str, action: str) -> str:
    return f"notif:slhit:{symbol.upper()}:{action}"


def notify_stop_loss_hit(snapshot: IntradaySnapshot) -> None:
    """Best-effort notify when a previously-triggered setup's stop-loss is
    breached. Never raises — mirrors `notify_trade_setup_triggered`."""
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup is None or setup.slHitAt is None or setup.action not in ("buy", "sell"):
        return

    cache = get_cache_client()
    cache_key = _sl_hit_cache_key(snapshot.symbol, setup.action)
    if cache.exists(cache_key):
        return

    title, message = _format_sl_hit_message(snapshot)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": settings.notification_telegram_chat_id},
        "title": title,
        "data": message,
        "reference": f"slhit-{snapshot.symbol}-{setup.slHitAt.date().isoformat()}",
        "metadata": {"source": "pivotiq-backend", "symbol": snapshot.symbol, "action": setup.action, "event": "sl_hit"},
    }

    try:
        response = requests.post(
            f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications",
            json=payload,
            timeout=5,
        )
        if not response.ok:
            logger.warning(
                "notification-service rejected SL-hit alert for %s: HTTP %s %s",
                snapshot.symbol, response.status_code, response.text,
            )
            return
    except requests.RequestException:
        logger.exception("failed to reach notification-service for %s SL-hit alert", snapshot.symbol)
        return

    cache.set_json(
        cache_key,
        {
            "symbol": snapshot.symbol.upper(),
            "action": setup.action,
            "status": "sl_hit",
            "stopLoss": setup.stopLoss,
            "slHitAt": setup.slHitAt.isoformat(),
        },
        ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS,
    )

