"""Fires trade-setup-triggered alerts to the standalone notification-service.

Calls out over plain HTTP (`POST /api/v1/notifications`) — no import
dependency on the notification-service code, same as any external caller.
A shared Redis-backed cache (see `app.services.cache`) stops the same
breakout from re-notifying on every watchlist/details poll by remembering that
a symbol+strategy+date+action was already triggered for a fixed TTL window.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.config import get_settings
from app.schemas.stock import IntradaySnapshot
from app.schemas.strategy import STRATEGY_SHORT_NAMES, StrategyName
from app.services.cache import get_cache_client

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_TRIGGER_CACHE_TTL_SECONDS = 8 * 60 * 60  # 8h: roughly one trading session


def _trigger_cache_key(symbol: str, strategy: str, action: str, date_str: str, entry_mode: str = "close") -> str:
    return f"notif:trigger:{symbol.upper()}:{strategy}:{date_str}:{action}:{entry_mode}"


def _sl_hit_cache_key(symbol: str, strategy: str, action: str, date_str: str, entry_mode: str = "close") -> str:
    return f"notif:slhit:{symbol.upper()}:{strategy}:{date_str}:{action}:{entry_mode}"


def _tradingview_link(symbol: str) -> str:
    return f'<a href="https://www.tradingview.com/chart/?symbol=NSE:{symbol.upper()}">View chart on TradingView</a>'


def get_user_enabled_strategies(user_id: Any | None = None) -> set[str]:
    """Return the set of enabled strategies for notifications.
    If user_id is provided, looks in MongoDB user_settings.
    Falls back to settings.notification_enabled_strategies."""
    settings = get_settings()
    if not user_id:
        return set(settings.notification_enabled_strategies)

    try:
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        doc = db.user_settings.find_one({"userId": str(user_id), "type": "strategy_notifications"})
        if doc and "enabledStrategies" in doc:
            return set(doc["enabledStrategies"])
    except Exception as exc:
        logger.warning("Could not read user strategy notifications setting: %s", exc)
    return set(settings.notification_enabled_strategies)


def _format_index_line(name: str, snap: IntradaySnapshot) -> str:
    setup = snap.tradeSetup
    ltp_str = f"₹{snap.currentPrice:,.2f}"
    chg_str = f" ({snap.changePercent:+.2f}%)" if snap.changePercent is not None else ""
    vwap_str = f" | {'Above' if snap.currentPrice >= snap.vwap else 'Below'} VWAP ₹{snap.vwap:,.2f}" if snap.vwap else ""

    if setup is None:
        return f"• <b>{name}</b>  ·  LTP {ltp_str}{chg_str}{vwap_str}"

    if setup.status == "triggered":
        action_emoji = "🟢" if setup.action == "buy" else "🔴"
        bo_level = setup.entry
        trig_time = setup.triggeredAt.astimezone(_IST).strftime("%H:%M") if setup.triggeredAt else ""
        time_part = f" at {trig_time}" if trig_time else ""
        return f"• <b>{name}</b>  ·  {action_emoji} <b>{setup.action.upper()} Breakout</b> at <code>₹{bo_level:,.2f}</code>{time_part}  |  LTP {ltp_str}{chg_str}{vwap_str}"

    if setup.status == "pending_entry":
        bo_level = setup.entry
        return f"• <b>{name}</b>  ·  🟡 Broke <code>₹{bo_level:,.2f}</code> · Pullback pending  |  LTP {ltp_str}{chg_str}{vwap_str}"

    if setup.status == "sl_hit":
        return f"• <b>{name}</b>  ·  🛑 {setup.action.upper()} SL Hit  |  LTP {ltp_str}{chg_str}{vwap_str}"

    orb_h = snap.openingRangeHigh
    orb_l = snap.openingRangeLow
    if orb_h and orb_l:
        return f"• <b>{name}</b>  ·  ⚪ Inside ORB (₹{orb_l:,.2f}–₹{orb_h:,.2f}) · Waiting  |  LTP {ltp_str}{chg_str}{vwap_str}"
    return f"• <b>{name}</b>  ·  ⚪ Range forming · Waiting  |  LTP {ltp_str}{chg_str}{vwap_str}"


def _format_index_section(index_snapshots: dict[str, IntradaySnapshot] | None) -> list[str]:
    if not index_snapshots:
        return []

    nifty_snap = index_snapshots.get("NIFTY 50") or index_snapshots.get("NIFTY50")
    banknifty_snap = index_snapshots.get("BANK NIFTY") or index_snapshots.get("BANKNIFTY")

    if nifty_snap is None and banknifty_snap is None:
        return []

    lines = [
        "📊 <b>Index Setups & Breakouts</b>",
    ]
    if nifty_snap is not None:
        lines.append(_format_index_line("NIFTY 50", nifty_snap))
    if banknifty_snap is not None:
        lines.append(_format_index_line("BANK NIFTY", banknifty_snap))
    lines.append("")
    return lines


def _format_message(
    snapshot: IntradaySnapshot,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> tuple[str, str]:
    """Telegram-HTML alert. Emojis only in headers to avoid line-height inflation on data rows."""
    setup = snapshot.tradeSetup
    strategy_label = STRATEGY_SHORT_NAMES.get(setup.strategy, setup.strategy.upper())
    action_emoji = "🟢" if setup.action == "buy" else "🔴"
    bias_label = (setup.bias or "neutral").capitalize()

    # Actual trade entry price: for strategies with a triggerPrice (e.g. pullback, pullback_support),
    # setup.triggerPrice is the actual fill/entry level, while setup.entry is the initial breakout level.
    trade_entry = setup.triggerPrice if setup.triggerPrice is not None else setup.entry
    breakout_level = setup.entry if (setup.triggerPrice is not None and setup.triggerPrice != setup.entry) else None

    entry_sl   = abs(trade_entry - setup.stopLoss)
    entry_sl_p = round((entry_sl / setup.stopLoss) * 100, 2) if setup.stopLoss else 0.0
    tgt_delta  = abs(setup.target - trade_entry)
    tgt_delta_p = round((tgt_delta / trade_entry) * 100, 2) if trade_entry else 0.0
    ltp_sl     = abs(snapshot.currentPrice - setup.stopLoss)
    ltp_sl_p   = round((ltp_sl / setup.stopLoss) * 100, 2) if setup.stopLoss else 0.0

    # Institutional VWAP proximity & evaluation
    vwap_val = snapshot.vwap
    vwap_diff = trade_entry - vwap_val
    vwap_diff_pct = (vwap_diff / vwap_val) * 100 if vwap_val > 0 else 0.0
    if setup.action == "buy":
        if vwap_diff < 0:
            vwap_badge = "⚠️"
            vwap_note = "Below VWAP"
        elif vwap_diff_pct <= 0.40:
            vwap_badge = "🟢"
            vwap_note = "Prime Entry (Near VWAP)"
        elif vwap_diff_pct <= 0.80:
            vwap_badge = "🟡"
            vwap_note = "Moderate Extension"
        else:
            vwap_badge = "⚠️"
            vwap_note = "Extended from VWAP"
    else:
        if vwap_diff > 0:
            vwap_badge = "⚠️"
            vwap_note = "Above VWAP"
        elif abs(vwap_diff_pct) <= 0.40:
            vwap_badge = "🟢"
            vwap_note = "Prime Entry (Near VWAP)"
        elif abs(vwap_diff_pct) <= 0.80:
            vwap_badge = "🟡"
            vwap_note = "Moderate Extension"
        else:
            vwap_badge = "⚠️"
            vwap_note = "Extended from VWAP"

    has_wide_sl = setup.slWide is not None
    wide_diff   = abs(trade_entry - setup.slWide) if has_wide_sl and setup.slWide else 0.0
    wide_diff_p = round((wide_diff / setup.slWide) * 100, 2) if has_wide_sl and setup.slWide else 0.0
    ltp_msl     = abs(snapshot.currentPrice - setup.slWide) if has_wide_sl and setup.slWide else 0.0
    ltp_msl_p   = round((ltp_msl / setup.slWide) * 100, 2) if has_wide_sl and setup.slWide else 0.0

    triggered_at = (
        setup.triggeredAt.astimezone(_IST).strftime("%d %b %Y, %H:%M IST")
        if setup.triggeredAt else "—"
    )

    mode_tag = " (3m Close)" if getattr(setup, "entryMode", None) == "close" else (" (LTP Break)" if getattr(setup, "entryMode", None) == "touch" else "")
    title = f"{action_emoji} {snapshot.symbol} · {setup.action.upper()} · {strategy_label}{mode_tag}"

    lines = [
        # ── Header (emojis allowed here) ──────────────────────────────────
        f"{action_emoji} <b>{setup.action.upper()} — {snapshot.symbol}</b>",
        f"Strategy  ·  <b>{strategy_label}{mode_tag}</b>  |  {bias_label} bias",
        "",
        # ── Price levels (plain-label rows) ──────────────────────────────
        f"LTP        ·  <b>₹{snapshot.currentPrice:,.2f}</b>",
        f"Entry      ·  <code>₹{trade_entry:,.2f}</code>",
    ]

    if breakout_level is not None:
        lines.append(f"BO Price   ·  <code>₹{breakout_level:,.2f}</code>")

    vwap_sign = "+" if vwap_diff >= 0 else "−"
    lines.append(f"VWAP       ·  <code>₹{vwap_val:,.2f}</code>  <i>({vwap_badge} {vwap_note} · Δ{vwap_sign}₹{abs(vwap_diff):,.2f} / {vwap_diff_pct:+.2f}%)</i>")
    lines.append(f"Target     ·  <code>₹{setup.target:,.2f}</code>  <i>(+₹{tgt_delta:,.2f} / +{tgt_delta_p:.2f}%)</i>")
    lines.append(f"Stop-Loss  ·  <code>₹{setup.stopLoss:,.2f}</code>  <i>(Δ₹{entry_sl:,.2f} / −{entry_sl_p:.2f}%)</i>")

    if has_wide_sl and setup.slWide:
        lines.append(f"Main Stop  ·  <code>₹{setup.slWide:,.2f}</code>  <i>(MΔ₹{wide_diff:,.2f} / −{wide_diff_p:.2f}%)</i>")

    vwap_pos_label = (
        "Above VWAP (Institutional Bullish Support 🟢)"
        if snapshot.currentPrice >= vwap_val
        else "Below VWAP (Institutional Bearish Pressure 🔴)"
    )

    lines.extend([
        "",
        # ── Risk stats ────────────────────────────────────────────────────
        f"Risk:Reward   ·  <b>1 : {setup.riskRewardRatio}</b>",
        f"SL from LTP   ·  ₹{ltp_sl:,.2f}  ({ltp_sl_p:.2f}%)",
        f"VWAP Bias     ·  {vwap_pos_label}",
    ])

    if has_wide_sl and setup.slWide:
        lines.append(f"MSL from LTP  ·  ₹{ltp_msl:,.2f}  ({ltp_msl_p:.2f}%)")

    index_lines = _format_index_section(index_snapshots)

    lines.extend([
        "",
        # ── Timing ────────────────────────────────────────────────────────
        f"Triggered  ·  <b>{triggered_at}</b>",
        "",
        *index_lines,
        # ── Footer (emoji ok, single line) ───────────────────────────────
        f"🔗 {_tradingview_link(snapshot.symbol)}",
    ])

    body = "\n".join(lines)
    return title, body


def _format_sl_hit_message(
    snapshot: IntradaySnapshot,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> tuple[str, str]:
    """Telegram-HTML SL-hit alert. Emojis only in headers to avoid line-height inflation."""
    setup = snapshot.tradeSetup
    strategy_label = STRATEGY_SHORT_NAMES.get(setup.strategy, setup.strategy.upper())
    action_emoji = "🟢" if setup.action == "buy" else "🔴"

    trade_entry = setup.triggerPrice if setup.triggerPrice is not None else setup.entry
    breakout_level = setup.entry if (setup.triggerPrice is not None and setup.triggerPrice != setup.entry) else None
    entry_sl   = abs(trade_entry - setup.stopLoss)
    entry_sl_p = round((entry_sl / setup.stopLoss) * 100, 2) if setup.stopLoss else 0.0

    has_wide_sl = setup.slWide is not None
    wide_diff   = abs(trade_entry - setup.slWide) if has_wide_sl and setup.slWide else 0.0
    wide_diff_p = round((wide_diff / setup.slWide) * 100, 2) if has_wide_sl and setup.slWide else 0.0

    pnl        = snapshot.currentPrice - trade_entry
    pnl_abs    = abs(pnl)
    pnl_pct    = abs(round((pnl / trade_entry) * 100, 2)) if trade_entry else 0.0
    pnl_sign   = "+" if pnl >= 0 else "−"

    triggered_at = (
        setup.triggeredAt.astimezone(_IST).strftime("%d %b %Y, %H:%M IST")
        if setup.triggeredAt else "—"
    )
    sl_hit_at = (
        setup.slHitAt.astimezone(_IST).strftime("%d %b %Y, %H:%M IST")
        if setup.slHitAt else "—"
    )

    title = f"🛑 {snapshot.symbol} · Stop-Loss Hit · {strategy_label}"

    lines = [
        # ── Header (emojis allowed here) ──────────────────────────────────
        f"🛑 <b>STOP-LOSS HIT — {snapshot.symbol}</b>",
        f"Strategy  ·  <b>{strategy_label}</b>  |  {setup.action.upper()} trade closed",
        "",
        # ── Trade levels (plain-label rows) ──────────────────────────────
        f"Entry      ·  {action_emoji} <code>₹{trade_entry:,.2f}</code>",
    ]

    if breakout_level is not None:
        lines.append(f"BO Price   ·  <code>₹{breakout_level:,.2f}</code>")

    lines.append(f"VWAP       ·  <code>₹{snapshot.vwap:,.2f}</code>")
    lines.append(f"Stop-Loss  ·  <code>₹{setup.stopLoss:,.2f}</code>  <i>(Δ₹{entry_sl:,.2f} / −{entry_sl_p:.2f}%)</i>")

    if has_wide_sl and setup.slWide:
        lines.append(f"Main Stop  ·  <code>₹{setup.slWide:,.2f}</code>  <i>(MΔ₹{wide_diff:,.2f} / −{wide_diff_p:.2f}%)</i>")

    index_lines = _format_index_section(index_snapshots)

    lines.extend([
        f"Exit       ·  <b>₹{snapshot.currentPrice:,.2f}</b>  <i>({pnl_sign}₹{pnl_abs:,.2f} / {pnl_sign}{pnl_pct:.2f}%)</i>",
        "",
        # ── Timeline ──────────────────────────────────────────────────────
        f"Entered   ·  {triggered_at}",
        f"SL hit    ·  <b>{sl_hit_at}</b>",
        "",
        *index_lines,
        # ── Result (emoji ok, single line) ───────────────────────────────
        f"❌ <b>Trade closed at stop-loss. Max loss realised.</b>",
        "",
        # ── Footer ────────────────────────────────────────────────────────
        f"🔗 {_tradingview_link(snapshot.symbol)}",
    ])

    body = "\n".join(lines)
    return title, body


def notify_trade_setup_triggered(
    snapshot: IntradaySnapshot,
    user_id: Any | None = None,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> None:
    """Best-effort notify. Never raises — a notification-service outage must
    not break watchlist polling for the caller."""
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup is None or setup.triggeredAt is None or setup.action not in ("buy", "sell"):
        return

    enabled_strategies = get_user_enabled_strategies(user_id)
    if setup.strategy not in enabled_strategies:
        return

    date_str = (setup.triggeredAt.astimezone(_IST) if setup.triggeredAt else datetime.now(_IST)).date().isoformat()
    entry_mode = getattr(setup, "entryMode", "close") or "close"
    cache = get_cache_client()
    cache_key = _trigger_cache_key(snapshot.symbol, setup.strategy, setup.action, date_str, entry_mode)
    if cache.exists(cache_key):
        return

    if not index_snapshots:
        try:
            from app.services.intraday_analysis import get_cached_index_snapshots
            index_snapshots = get_cached_index_snapshots(setup.strategy, entry_mode)
        except Exception:
            index_snapshots = None

    title, message = _format_message(snapshot, index_snapshots=index_snapshots)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": settings.notification_telegram_chat_id},
        "title": title,
        "data": message,
        "reference": f"trigger-{snapshot.symbol}-{setup.strategy}-{entry_mode}-{date_str}",
        "metadata": {
            "source": "pivotiq-backend",
            "symbol": snapshot.symbol,
            "action": setup.action,
            "strategy": setup.strategy,
            "entryMode": entry_mode,
        },
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

    trade_entry = setup.triggerPrice if setup.triggerPrice is not None else setup.entry
    # Only cache after a confirmed send, so a failed/rejected request can retry on the next poll.
    cache.set_json(
        cache_key,
        {
            "symbol": snapshot.symbol.upper(),
            "strategy": setup.strategy,
            "action": setup.action,
            "status": "triggered",
            "entry": trade_entry,
            "breakoutPrice": setup.entry if trade_entry != setup.entry else None,
            "stopLoss": setup.stopLoss,
            "slWide": setup.slWide,
            "target": setup.target,
            "triggeredAt": setup.triggeredAt.isoformat(),
        },
        ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS,
    )


def notify_stop_loss_hit(
    snapshot: IntradaySnapshot,
    user_id: Any | None = None,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> None:
    """Best-effort notify when a previously-triggered setup's stop-loss is breached."""
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup is None or setup.slHitAt is None or setup.action not in ("buy", "sell"):
        return

    enabled_strategies = get_user_enabled_strategies(user_id)
    if setup.strategy not in enabled_strategies:
        return

    date_str = (setup.slHitAt.astimezone(_IST) if setup.slHitAt else datetime.now(_IST)).date().isoformat()
    entry_mode = getattr(setup, "entryMode", "close") or "close"
    cache = get_cache_client()
    cache_key = _sl_hit_cache_key(snapshot.symbol, setup.strategy, setup.action, date_str, entry_mode)
    if cache.exists(cache_key):
        return

    if not index_snapshots:
        try:
            from app.services.intraday_analysis import get_cached_index_snapshots
            index_snapshots = get_cached_index_snapshots(setup.strategy, entry_mode)
        except Exception:
            index_snapshots = None

    title, message = _format_sl_hit_message(snapshot, index_snapshots=index_snapshots)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": settings.notification_telegram_chat_id},
        "title": title,
        "data": message,
        "reference": f"slhit-{snapshot.symbol}-{setup.strategy}-{entry_mode}-{date_str}",
        "metadata": {
            "source": "pivotiq-backend",
            "symbol": snapshot.symbol,
            "action": setup.action,
            "strategy": setup.strategy,
            "entryMode": entry_mode,
            "event": "sl_hit",
        },
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
            "strategy": setup.strategy,
            "action": setup.action,
            "status": "sl_hit",
            "stopLoss": setup.stopLoss,
            "slHitAt": setup.slHitAt.isoformat(),
        },
        ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS,
    )
