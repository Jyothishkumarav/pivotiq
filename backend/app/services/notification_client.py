"""Fires trade-setup-triggered alerts to the standalone notification-service.

Calls out over plain HTTP (`POST /api/v1/notifications`) — no import
dependency on the notification-service code, same as any external caller.
A shared Redis-backed cache (see `app.services.cache`) stops the same
breakout from re-notifying on every watchlist/details poll by remembering that
a symbol+strategy+date+action was already triggered for a fixed TTL window.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
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


DEFAULT_STRATEGY_CHANNELS: dict[str, str] = {
    "breakout_support": "-1004449069761",
    "orb_pullback_support": "-1004440440854",
    "orb_pullback": "-1004294022390",
}


def get_strategy_telegram_channel(strategy: str, user_id: Any | None = None) -> str:
    """Return the Telegram chat_id to use for this strategy.
    Prefers a per-strategy override stored in user_settings.strategyChannels;
    falls back to DEFAULT_STRATEGY_CHANNELS, then to global NOTIFICATION_TELEGRAM_CHAT_ID."""
    settings = get_settings()
    fallback_chat_id = DEFAULT_STRATEGY_CHANNELS.get(strategy) or settings.notification_telegram_chat_id

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "strategy_notifications"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "strategy_notifications"})
        if doc and "strategyChannels" in doc and isinstance(doc["strategyChannels"], dict):
            channel = doc["strategyChannels"].get(strategy)
            if channel:
                return channel
    except Exception as exc:
        logger.warning("Could not read per-strategy channel for %s: %s", strategy, exc)

    return fallback_chat_id


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

    if getattr(setup, "indexConfluence", None):
        conf_label = setup.indexConfluence.replace("_", " ").upper()
        conf_emoji = "🎯" if setup.indexConfluence == "aligned" else ("🛡️" if setup.indexConfluence == "relative_strength" else "⚪")
        mult = getattr(setup, "sizingMultiplier", 1.0) or 1.0
        lines.append(f"Index Confl   ·  {conf_emoji} <b>{conf_label}</b> ({mult}R Sizing)")

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
    chat_id = get_strategy_telegram_channel(setup.strategy, user_id)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": chat_id},
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
    chat_id = get_strategy_telegram_channel(setup.strategy, user_id)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": chat_id},
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


def clear_notification_cache(
    *,
    strategy: str | None = None,
    symbols: list[str] | None = None,
) -> int:
    """Evict notification deduplication keys from Redis so triggers/SL-hits can re-fire.
    Used when triggers are reset in the UI or on strategy changes."""
    cache = get_cache_client()
    strat_pat = strategy if strategy else "*"
    deleted = 0
    if symbols:
        for sym in symbols:
            deleted += cache.delete_pattern(f"notif:*:{sym.upper()}:{strat_pat}:*")
    else:
        deleted += cache.delete_pattern(f"notif:*:*:{strat_pat}:*")
    return deleted


def _format_pullback_started_message(
    snapshot: IntradaySnapshot,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> tuple[str, str]:
    setup = snapshot.tradeSetup
    strategy_label = STRATEGY_SHORT_NAMES.get(setup.strategy, setup.strategy.upper())
    action_label = setup.action.upper()
    action_emoji = "🟢" if setup.action == "buy" else "🔴"
    # setup.stopLoss at stage 3 (pb_forming) is always the ORB macro boundary (MSL)
    msl = setup.stopLoss

    title = f"🟡 {snapshot.symbol} · Pullback Started · {strategy_label}"

    lines = [
        f"🟡 <b>PULLBACK STARTED — {snapshot.symbol}</b>",
        f"Strategy  ·  <b>{strategy_label}</b>  |  {action_emoji} {action_label} setup",
        "",
        f"LTP        ·  <b>₹{snapshot.currentPrice:,.2f}</b>",
        f"BO Price   ·  <code>₹{setup.entry:,.2f}</code>",
        f"ORB Range  ·  <code>₹{snapshot.openingRangeLow:,.2f} – ₹{snapshot.openingRangeHigh:,.2f}</code>",
        f"VWAP       ·  <code>₹{snapshot.vwap:,.2f}</code>",
        f"MSL        ·  <code>₹{msl:,.2f}</code>  <i>(Macro Stop · ORB {'Low' if setup.action == 'buy' else 'High'} boundary)</i>",
        "",
        f"ℹ️ <i>Pullback active. Tight SL buffer will be set once support candle forms.</i>",
        "",
        f"🔗 {_tradingview_link(snapshot.symbol)}",
    ]
    return title, "\n".join(lines)


def notify_pullback_started(
    snapshot: IntradaySnapshot,
    user_id: Any | None = None,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> None:
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup is None or setup.action not in ("buy", "sell"):
        return

    enabled_strategies = get_user_enabled_strategies(user_id)
    if setup.strategy not in enabled_strategies:
        return

    date_str = datetime.now(_IST).date().isoformat()
    entry_mode = getattr(setup, "entryMode", "close") or "close"
    cache = get_cache_client()
    # Include entry_mode so close/touch configs track independently
    cache_key = f"notif:stage:pb:{snapshot.symbol.upper()}:{setup.strategy}:{date_str}:{setup.action}:{entry_mode}"
    if cache.exists(cache_key):
        return

    title, message = _format_pullback_started_message(snapshot, index_snapshots=index_snapshots)
    chat_id = get_strategy_telegram_channel(setup.strategy, user_id)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": chat_id},
        "title": title,
        "data": message,
        "reference": f"pb-{snapshot.symbol}-{setup.strategy}-{date_str}",
        "metadata": {
            "source": "pivotiq-backend",
            "symbol": snapshot.symbol,
            "action": setup.action,
            "strategy": setup.strategy,
            "stage": "pb_forming",
        },
    }

    try:
        response = requests.post(
            f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications",
            json=payload,
            timeout=5,
        )
        if response.ok:
            cache.set_json(cache_key, {"sent": True}, ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Could not send pullback started alert for %s: %s", snapshot.symbol, exc)


def _format_support_formed_message(
    snapshot: IntradaySnapshot,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> tuple[str, str]:
    setup = snapshot.tradeSetup
    strategy_label = STRATEGY_SHORT_NAMES.get(setup.strategy, setup.strategy.upper())
    action_label = setup.action.upper()
    action_emoji = "🟢" if setup.action == "buy" else "🔴"
    trigger_level = setup.triggerPrice if setup.triggerPrice is not None else setup.entry
    risk_per_share = abs(trigger_level - setup.stopLoss) if setup.stopLoss else 0.0

    title = f"🔵 {snapshot.symbol} · Support Formed (Armed) · {strategy_label}"

    lines = [
        f"🔵 <b>SETUP ARMED — {snapshot.symbol}</b>",
        f"Strategy  ·  <b>{strategy_label}</b>  |  {action_emoji} {action_label} setup",
        "",
        f"Trigger    ·  <b>₹{trigger_level:,.2f}</b>  <i>({'Green High' if setup.action == 'buy' else 'Red Low'})</i>",
        f"BO Price   ·  <code>₹{setup.entry:,.2f}</code>",
        f"LTP        ·  <code>₹{snapshot.currentPrice:,.2f}</code>",
        f"Tight SL   ·  <code>₹{setup.stopLoss:,.2f}</code>  <i>(Buffered · Risk: ₹{risk_per_share:,.2f}/sh)</i>",
        f"VWAP       ·  <code>₹{snapshot.vwap:,.2f}</code>",
        "",
        f"🎯 <b>Ready for entry. Order will trigger when price breaks ₹{trigger_level:,.2f}.</b>",
        "",
        f"🔗 {_tradingview_link(snapshot.symbol)}",
    ]
    return title, "\n".join(lines)


def notify_support_candle_formed(
    snapshot: IntradaySnapshot,
    user_id: Any | None = None,
    index_snapshots: dict[str, IntradaySnapshot] | None = None,
) -> None:
    settings = get_settings()
    if not settings.notification_service_enabled:
        return

    setup = snapshot.tradeSetup
    if setup is None or setup.action not in ("buy", "sell"):
        return

    enabled_strategies = get_user_enabled_strategies(user_id)
    if setup.strategy not in enabled_strategies:
        return

    date_str = datetime.now(_IST).date().isoformat()
    trigger_level = setup.triggerPrice if setup.triggerPrice is not None else setup.entry
    entry_mode = getattr(setup, "entryMode", "close") or "close"
    cache = get_cache_client()
    # Include entry_mode so close/touch configs track independently; trigger_level
    # ensures a new support candle at a different level fires a fresh notification
    cache_key = f"notif:stage:sup:{snapshot.symbol.upper()}:{setup.strategy}:{date_str}:{setup.action}:{entry_mode}:{trigger_level:.2f}"
    if cache.exists(cache_key):
        return

    title, message = _format_support_formed_message(snapshot, index_snapshots=index_snapshots)
    chat_id = get_strategy_telegram_channel(setup.strategy, user_id)
    payload = {
        "channels": settings.notification_channels,
        "recipient": {"telegramChatId": chat_id},
        "title": title,
        "data": message,
        "reference": f"sup-{snapshot.symbol}-{setup.strategy}-{trigger_level:.2f}-{date_str}",
        "metadata": {
            "source": "pivotiq-backend",
            "symbol": snapshot.symbol,
            "action": setup.action,
            "strategy": setup.strategy,
            "stage": "support_formed",
        },
    }

    try:
        response = requests.post(
            f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications",
            json=payload,
            timeout=5,
        )
        if response.ok:
            cache.set_json(cache_key, {"sent": True}, ttl_seconds=_TRIGGER_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Could not send support candle formed alert for %s: %s", snapshot.symbol, exc)


def notify_trade_execution(
    symbol: str,
    side: str,
    qty: int,
    entry_price: float,
    stop_loss: float,
    strategy: str | None = None,
    broker: str = "Paper",
    user_id: Any | None = None,
    placed_at: datetime | None = None,
    is_test: bool = False,
) -> bool:
    """Send immediate trade execution alert with direct Fyers Web link to the user's
    configured Telegram channel (default: FyersTrade -1003999053085)."""
    settings = get_settings()

    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled and not is_test:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    risk_per_share = abs(entry_price - stop_loss)
    total_risk = risk_per_share * qty

    exec_time = placed_at or datetime.now(_IST)
    if exec_time.tzinfo is None:
        exec_time = exec_time.replace(tzinfo=timezone.utc)
    time_str = exec_time.astimezone(_IST).strftime("%I:%M:%S %p")

    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    strat_label = STRATEGY_SHORT_NAMES.get(strategy or "", (strategy or "Intraday MIS").upper())

    test_prefix = "⚠️ <b>[TEST ALERT]</b>\n" if is_test else ""
    title = f"{'⚠️ [TEST] ' if is_test else ''}⚡ FYERS TRADE: {action_label} {clean_symbol}"

    lines = [
        f"{test_prefix}⚡ <b>FYERS TRADE ENTRY — {clean_symbol}</b>",
        f"────────────────────────────",
        f"📊 <b>Action:</b> {action_emoji} <b>{action_label}</b>",
        f"🏷️ <b>Symbol:</b> <code>{fyers_symbol}</code>",
        f"📦 <b>Quantity:</b> <b>{qty}</b> shares",
        f"💵 <b>Entry Price (CMP):</b> <b>₹{entry_price:,.2f}</b>",
        f"🛑 <b>Stop Loss:</b> <b>₹{stop_loss:,.2f}</b> (Risk: ₹{risk_per_share:,.2f}/sh)",
        f"🛡️ <b>Total Risk:</b> ₹{total_risk:,.2f}",
        f"⏱️ <b>Time:</b> {time_str} IST",
        f"📈 <b>Strategy:</b> {strat_label}",
        f"🏦 <b>Execution:</b> {broker}",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">CLICK HERE TO PLACE ORDER ON FYERS WEB</a></b>",
        f"🔗 <a href=\"https://www.tradingview.com/chart/?symbol={fyers_symbol}\">TradingView Chart</a>",
    ]
    message_text = "\n".join(lines)

    # 1. Dispatch via notification-service
    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"trade-{clean_symbol}-{action_label.lower()}-{int(datetime.now().timestamp())}",
            "metadata": {
                "source": "pivotiq-trade-execution",
                "symbol": clean_symbol,
                "side": action_label.lower(),
                "qty": qty,
                "entryPrice": entry_price,
                "stopLoss": stop_loss,
                "fyersUrl": fyers_url,
            },
        }
        res = requests.post(
            f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications",
            json=payload,
            timeout=4,
        )
        if res.ok:
            sent = True
    except Exception as exc:
        logger.warning("Could not dispatch trade notification via service: %s", exc)

    # 2. Robust direct fallback if notification-service was not reachable or failed
    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                full_text = f"<b>{title}</b>\n\n{message_text}"
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": channel_id,
                        "text": full_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=5,
                )
                sent = True
            except Exception as exc:
                logger.warning("Direct telegram fallback failed for trade %s: %s", clean_symbol, exc)

    return sent


def notify_target_milestone_reached(
    symbol: str,
    side: str,
    entry_price: float,
    current_ltp: float,
    stop_loss: float,
    ratio: float,
    qty: int,
    user_id: Any | None = None,
    broker: str = "Paper",
) -> bool:
    """Dispatches a notification on the dedicated Trade Channel when position moves 1.0R, 1.5R, or 2.0R in profit."""
    settings = get_settings()
    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True)) and bool(cfg.get("targetMilestoneAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    sl_diff = abs(entry_price - stop_loss)
    pts_move = (current_ltp - entry_price) if is_buy else (entry_price - current_ltp)
    pct_move = (pts_move / entry_price) * 100 if entry_price else 0.0
    unrealized_pnl = pts_move * qty

    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    now_str = datetime.now(_IST).strftime("%I:%M:%S %p")

    title = f"🎯 MILESTONE: {clean_symbol} Reached {ratio:.1f}R Target"
    lines = [
        f"🎯 <b>PORTFOLIO MILESTONE: {clean_symbol} — {ratio:.1f}R GAIN</b>",
        f"────────────────────────────",
        f"📊 <b>Position:</b> {action_emoji} <b>{action_label}</b> ({qty} shs)",
        f"💵 <b>Entry Price:</b> ₹{entry_price:,.2f}",
        f"🛑 <b>Stop Loss:</b> ₹{stop_loss:,.2f} (SL Diff: ₹{sl_diff:.2f})",
        f"⚡ <b>Current LTP:</b> <b>₹{current_ltp:,.2f}</b>",
        f"📈 <b>Gain:</b> <b>+{ratio:.1f}x SL Diff</b> (+₹{pts_move:.2f} / +{pct_move:.2f}%)",
        f"💰 <b>Unrealized P&L:</b> <b>+₹{unrealized_pnl:,.2f}</b>",
        f"⏱️ <b>Time:</b> {now_str} IST",
        f"🏦 <b>Account:</b> {broker}",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">VIEW CHART ON FYERS WEB</a></b>",
    ]
    message_text = "\n".join(lines)

    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"milestone-{clean_symbol}-{ratio}r-{int(datetime.now().timestamp())}",
            "metadata": {"symbol": clean_symbol, "ratio": ratio, "ltp": current_ltp},
        }
        res = requests.post(f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications", json=payload, timeout=4)
        if res.ok:
            sent = True
    except Exception:
        pass

    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": channel_id, "text": f"<b>{title}</b>\n\n{message_text}", "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=5,
                )
                sent = True
            except Exception:
                pass
    return sent


def notify_position_auto_closed(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    ratio: float,
    qty: int,
    realized_pnl: float,
    user_id: Any | None = None,
    broker: str = "Paper",
) -> bool:
    """Dispatches a notification on the dedicated Trade Channel when position auto-closes at target (1.5R / 2.0R)."""
    settings = get_settings()
    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    pct_pnl = (realized_pnl / (entry_price * qty)) * 100 if (entry_price * qty) else 0.0

    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    now_str = datetime.now(_IST).strftime("%I:%M:%S %p")

    title = f"🎉 TARGET HIT: {clean_symbol} Auto-Closed at {ratio:.1f}R (+₹{realized_pnl:,.2f})"
    lines = [
        f"🎉 <b>AUTO-TARGET HIT & SQUARED OFF — {clean_symbol}</b>",
        f"────────────────────────────",
        f"📊 <b>Position:</b> {action_emoji} <b>{action_label}</b> ({qty} shs)",
        f"🎯 <b>Target Ratio:</b> <b>{ratio:.1f}R Target</b>",
        f"💵 <b>Entry Price:</b> ₹{entry_price:,.2f}",
        f"🏁 <b>Exit Price:</b> <b>₹{exit_price:,.2f}</b>",
        f"💰 <b>Realized Profit:</b> <b>+₹{realized_pnl:,.2f} (+{pct_pnl:.2f}%)</b>",
        f"⏱️ <b>Closed At:</b> {now_str} IST",
        f"🏦 <b>Execution:</b> {broker}",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">VIEW CHART ON FYERS WEB</a></b>",
    ]
    message_text = "\n".join(lines)

    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"autoclose-{clean_symbol}-{int(datetime.now().timestamp())}",
            "metadata": {"symbol": clean_symbol, "ratio": ratio, "exitPrice": exit_price, "pnl": realized_pnl},
        }
        res = requests.post(f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications", json=payload, timeout=4)
        if res.ok:
            sent = True
    except Exception:
        pass

    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": channel_id, "text": f"<b>{title}</b>\n\n{message_text}", "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=5,
                )
                sent = True
            except Exception:
                pass
    return sent


def notify_position_sl_closed(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    qty: int,
    realized_pnl: float,
    user_id: Any | None = None,
    broker: str = "Paper",
) -> bool:
    """Dispatches a notification on the dedicated Trade Channel when position hits SL and closes."""
    settings = get_settings()
    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    pct_pnl = (realized_pnl / (entry_price * qty)) * 100 if (entry_price * qty) else 0.0

    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    now_str = datetime.now(_IST).strftime("%I:%M:%S %p")

    title = f"🛑 STOP LOSS HIT: {clean_symbol} Closed at ₹{exit_price:,.2f}"
    lines = [
        f"🛑 <b>STOP LOSS HIT & SQUARED OFF — {clean_symbol}</b>",
        f"────────────────────────────",
        f"📊 <b>Position:</b> {action_emoji} <b>{action_label}</b> ({qty} shs)",
        f"💵 <b>Entry Price:</b> ₹{entry_price:,.2f}",
        f"🛑 <b>Stop Loss:</b> ₹{stop_loss:,.2f}",
        f"🏁 <b>Exit Price:</b> <b>₹{exit_price:,.2f}</b>",
        f"📉 <b>Realized Loss:</b> <b>-₹{abs(realized_pnl):,.2f} ({pct_pnl:.2f}%)</b>",
        f"⏱️ <b>Closed At:</b> {now_str} IST",
        f"🏦 <b>Execution:</b> {broker}",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">VIEW CHART ON FYERS WEB</a></b>",
    ]
    message_text = "\n".join(lines)

    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"slclose-{clean_symbol}-{int(datetime.now().timestamp())}",
            "metadata": {"symbol": clean_symbol, "exitPrice": exit_price, "pnl": realized_pnl},
        }
        res = requests.post(f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications", json=payload, timeout=4)
        if res.ok:
            sent = True
    except Exception:
        pass

    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": channel_id, "text": f"<b>{title}</b>\n\n{message_text}", "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=5,
                )
                sent = True
            except Exception:
                pass
    return sent


def notify_position_trailing_sl_updated(
    symbol: str,
    side: str,
    entry_price: float,
    current_ltp: float,
    initial_sl: float,
    trailing_sl: float,
    qty: int,
    user_id: Any | None = None,
    broker: str = "Paper",
) -> bool:
    """Dispatches an alert when LTP crosses 2.0R and the position's Stop-Loss is trailed to 2.0R."""
    settings = get_settings()
    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    now_str = datetime.now(_IST).strftime("%I:%M:%S %p")

    locked_pnl = round(abs(trailing_sl - entry_price) * qty, 2)
    locked_pct = (abs(trailing_sl - entry_price) / entry_price) * 100 if entry_price else 0.0

    title = f"🚀 2.0R HIT: {clean_symbol} Trailing SL Set to ₹{trailing_sl:,.2f}"
    lines = [
        f"🚀 <b>TARGET 2.0R CROSSED — TRAILING SL ACTIVATED</b>",
        f"────────────────────────────",
        f"📈 <b>Stock:</b> <b>{clean_symbol}</b> ({action_emoji} {action_label})",
        f"📦 <b>Size:</b> {qty} shares",
        f"💵 <b>Entry Price:</b> ₹{entry_price:,.2f}",
        f"⚡ <b>Current LTP:</b> ₹{current_ltp:,.2f}",
        f"🛡️ <b>Original SL:</b> ₹{initial_sl:,.2f}",
        f"🔒 <b>NEW TRAILING SL (2R):</b> <b>₹{trailing_sl:,.2f}</b>",
        f"💰 <b>Guaranteed Profit:</b> <b>+₹{locked_pnl:,.2f} (+{locked_pct:.2f}%)</b>",
        f"🏃 <b>Status:</b> <b>TRADE ACTIVE & RUNNING</b>",
        f"ℹ️ <i>Stop loss locked at 2.0R. If price drops to ₹{trailing_sl:,.2f}, position will exit with profit locked in.</i>",
        f"⏱️ <b>Time:</b> {now_str} IST",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">VIEW LIVE CHART ON FYERS</a></b>",
    ]
    message_text = "\n".join(lines)

    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"trailed-{clean_symbol}-{int(datetime.now().timestamp())}",
            "metadata": {"symbol": clean_symbol, "trailingSl": trailing_sl, "lockedPnl": locked_pnl},
        }
        res = requests.post(f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications", json=payload, timeout=4)
        if res.ok:
            sent = True
    except Exception:
        pass

    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": channel_id, "text": f"<b>{title}</b>\n\n{message_text}", "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=5,
                )
                sent = True
            except Exception:
                pass
    return sent


def notify_position_trail_sl_closed(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    trailing_sl: float,
    qty: int,
    realized_pnl: float,
    user_id: Any | None = None,
    broker: str = "Paper",
) -> bool:
    """Dispatches a notification when position exits upon hitting the Trailing Stop-Loss."""
    settings = get_settings()
    channel_id = "-1003999053085"
    alerts_enabled = True

    try:
        from bson import ObjectId
        from app.services.intraday_analysis import get_trigger_collection
        db = get_trigger_collection().database
        query: dict[str, Any] = {"type": "trading_config"}
        if user_id:
            uid_str = str(user_id)
            conds: list[dict] = [{"userId": uid_str}]
            if ObjectId.is_valid(uid_str):
                conds.append({"userId": ObjectId(uid_str)})
            query["$or"] = conds
        doc = db.user_settings.find_one(query)
        if not doc and user_id:
            doc = db.user_settings.find_one({"type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = doc["config"]
            channel_id = cfg.get("tradeTelegramChannelId") or channel_id
            alerts_enabled = bool(cfg.get("tradeTelegramAlertsEnabled", True))
    except Exception as exc:
        logger.warning("Could not read trading Telegram config: %s", exc)

    if not alerts_enabled:
        return False

    is_buy = side.lower() == "buy"
    action_label = "BUY" if is_buy else "SELL"
    action_emoji = "🟢" if is_buy else "🔴"
    pct_pnl = (realized_pnl / (entry_price * qty)) * 100 if (entry_price * qty) else 0.0

    clean_symbol = symbol.upper().replace("NSE:", "").replace("-EQ", "")
    fyers_symbol = f"NSE:{clean_symbol}-EQ"
    fyers_url = f"https://fyers.in/web/symbol/{fyers_symbol}"
    now_str = datetime.now(_IST).strftime("%I:%M:%S %p")

    title = f"🛡️ TRAILING SL HIT: {clean_symbol} Closed at ₹{exit_price:,.2f}"
    lines = [
        f"🛡️ <b>TRAILING STOP LOSS HIT — {clean_symbol}</b>",
        f"────────────────────────────",
        f"📊 <b>Position:</b> {action_emoji} <b>{action_label}</b> ({qty} shs)",
        f"💵 <b>Entry Price:</b> ₹{entry_price:,.2f}",
        f"🔒 <b>Trailed SL:</b> ₹{trailing_sl:,.2f} (2.0R)",
        f"🏁 <b>Exit Price:</b> <b>₹{exit_price:,.2f}</b>",
        f"🏆 <b>Realized Profit:</b> <b>+₹{realized_pnl:,.2f} (+{pct_pnl:.2f}%)</b>",
        f"🏷️ <b>Exit Status:</b> <b>TRAILING SL HIT</b>",
        f"⏱️ <b>Closed At:</b> {now_str} IST",
        f"🏦 <b>Execution:</b> {broker}",
        f"────────────────────────────",
        f"👉 <b><a href=\"{fyers_url}\">VIEW CHART ON FYERS WEB</a></b>",
    ]
    message_text = "\n".join(lines)

    sent = False
    try:
        payload = {
            "channels": ["telegram"],
            "recipient": {"telegramChatId": channel_id},
            "title": title,
            "data": message_text,
            "reference": f"trailslclose-{clean_symbol}-{int(datetime.now().timestamp())}",
            "metadata": {"symbol": clean_symbol, "exitPrice": exit_price, "pnl": realized_pnl, "reason": "trail_sl_hit"},
        }
        res = requests.post(f"{settings.notification_service_url.rstrip('/')}/api/v1/notifications", json=payload, timeout=4)
        if res.ok:
            sent = True
    except Exception:
        pass

    if not sent:
        token = getattr(settings, "telegram_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": channel_id, "text": f"<b>{title}</b>\n\n{message_text}", "parse_mode": "HTML", "disable_web_page_preview": True},
                    timeout=5,
                )
                sent = True
            except Exception:
                pass
    return sent



