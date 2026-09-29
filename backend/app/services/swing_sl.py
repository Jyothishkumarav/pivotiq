"""Swing High / Low Stop-Loss Suggester  (independent module — NOT wired into any trade flow)

Problem this solves
-------------------
The existing SL is computed as `entry_price * (1 ± buffer_pct)` — a flat
percentage offset.  On higher-priced stocks (₹2 000 +) even a 0.5 % offset
creates a very tight SL that gets wiped out by ordinary noise.

Better SL = the NEAREST *structurally significant* swing high (for a SELL/
SHORT trade) or swing low (for a BUY/LONG trade) that is ABOVE/BELOW the
entry price.  These are price levels where supply/demand actually showed up
in today's session, so they act as real walls.

Algorithm
---------
1. Fetch today's 5-minute Fyers candles for the symbol.
2. Run a **pivot-point** scan:
   - A candle at index `i` is a **swing high** if its `high` is the highest
     among the `N` candles on either side (look-left and look-right).
   - A candle at index `i` is a **swing low**  if its `low`  is the lowest
     among the `N` candles on either side.
   Default N = 2 (±2 bars = ±10 min context).  Configurable via `strength`.
3. Filter:
   - For SELL: keep only swing *highs* that are **above** the entry price.
   - For BUY:  keep only swing *lows*  that are **below** the entry price.
4. Return the *nearest* one (the smallest gap to entry) — it is the tightest
   level that still has structural backing, keeping risk minimal without being
   arbitrary.

Also returns the full ranked list so callers can pick a more conservative
(farther) level if desired.

Usage
-----
    from app.services.swing_sl import suggest_sl

    result = suggest_sl(
        symbol="KAYNES",
        side="sell",          # "buy" or "sell"
        entry_price=3487.30,
        access_token=token,   # Fyers JWT; None → fallback (flat %)
        date="2026-09-29",    # ISO date; None → today (IST)
        resolution="5",       # "1" / "3" / "5" / "15" — Fyers minute resolution
        strength=2,           # pivot look-left/look-right bars
    )

    # result.suggested_sl  →  recommended SL price
    # result.swing_levels  →  all detected swing highs (for sell) / lows (for buy)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import fyers_client
from app.services.fyers_client import FyersError, FyersTokenExpired

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SwingLevel:
    """A single detected swing high or swing low."""
    time: datetime              # IST timestamp of the candle
    price: float                # the high (swing high) or low (swing low)
    candle_open: float
    candle_high: float
    candle_low: float
    candle_close: float
    distance_from_entry: float  # abs(price - entry_price)
    gap_pct: float              # distance as % of entry_price


@dataclass
class SwingSLResult:
    symbol: str
    side: str                           # "buy" or "sell"
    entry_price: float
    resolution: str
    date: str
    strength: int                       # pivot look-left/right bars

    suggested_sl: float | None          # best (nearest structural) level
    suggested_sl_time: datetime | None  # when that swing formed
    gap_pct: float | None               # how far the SL is from entry (%)

    swing_levels: list[SwingLevel] = field(default_factory=list)
    fallback_sl: float | None = None    # flat-pct fallback
    fallback_pct: float = 0.3

    candles_fetched: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_intraday_candles(
    access_token: str,
    symbol: str,
    date: str,
    resolution: str,
) -> list[dict]:
    """Pull minute-level candles for a single trading day from Fyers."""
    try:
        resp = fyers_client.get_history(
            access_token,
            symbol=symbol,
            resolution=resolution,
            date_from=date,
            date_to=date,
        )
    except FyersTokenExpired as exc:
        logger.warning("swing_sl: Fyers token expired (%s): %s", symbol, exc)
        return []
    except FyersError as exc:
        logger.warning("swing_sl: Fyers error (%s): %s", symbol, exc)
        return []
    except Exception as exc:
        logger.warning("swing_sl: unexpected error fetching candles (%s): %s", symbol, exc)
        return []

    raw = resp.get("candles") or []
    seen_epochs: set[int] = set()
    candles: list[dict] = []
    for row in raw:
        if len(row) < 6:
            continue
        epoch, o, h, l, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        epoch_int = int(epoch)
        if epoch_int in seen_epochs:
            continue  # Fyers cont_flag=1 can return duplicate candles for intraday
        seen_epochs.add(epoch_int)
        ts = datetime.fromtimestamp(epoch_int, tz=IST)
        candles.append({
            "time": ts, "open": float(o), "high": float(h),
            "low": float(l), "close": float(c), "volume": int(v),
        })
    return candles



def _detect_swing_highs(candles: list[dict], strength: int) -> list[tuple[int, dict]]:
    """Return (index, candle) for every pivot swing-high.

    A bar at `i` is a swing high when its `high` is STRICTLY greater than
    every bar in [i-strength .. i+strength] excluding itself.
    """
    result: list[tuple[int, dict]] = []
    n = len(candles)
    for i in range(strength, n - strength):
        h = candles[i]["high"]
        neighbours = [candles[j]["high"] for j in range(i - strength, i + strength + 1) if j != i]
        if h > max(neighbours):
            result.append((i, candles[i]))
    return result


def _detect_swing_lows(candles: list[dict], strength: int) -> list[tuple[int, dict]]:
    """Return (index, candle) for every pivot swing-low."""
    result: list[tuple[int, dict]] = []
    n = len(candles)
    for i in range(strength, n - strength):
        lo = candles[i]["low"]
        neighbours = [candles[j]["low"] for j in range(i - strength, i + strength + 1) if j != i]
        if lo < min(neighbours):
            result.append((i, candles[i]))
    return result


def _today_ist() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_sl(
    symbol: str,
    side: str,
    entry_price: float,
    access_token: str | None = None,
    date: str | None = None,
    resolution: str = "5",
    strength: int = 2,
    fallback_pct: float = 0.3,
) -> SwingSLResult:
    """Suggest a structurally-backed SL using intraday swing pivot points.

    Parameters
    ----------
    symbol       : NSE symbol e.g. "KAYNES"
    side         : "buy"  → protect long  (use nearest swing LOW  below entry as SL)
                   "sell" → protect short (use nearest swing HIGH above entry as SL)
    entry_price  : trade entry price
    access_token : Fyers JWT (required for intraday candles)
    date         : "YYYY-MM-DD"; defaults to today (IST)
    resolution   : Fyers candle resolution in minutes ("1","3","5","15","60")
    strength     : pivot look-left/right bar count (2 = ±10 min for 5-min chart)
    fallback_pct : % offset SL to use when no structural swing found
    """
    symbol = symbol.strip().upper()
    side   = side.strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got: {side!r}")

    trading_date = date or _today_ist()

    # Compute flat-% fallback SL
    if side == "sell":
        fallback_sl = round(entry_price * (1 + fallback_pct / 100), 2)
    else:
        fallback_sl = round(entry_price * (1 - fallback_pct / 100), 2)

    base = SwingSLResult(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        resolution=resolution,
        date=trading_date,
        strength=strength,
        suggested_sl=None,
        suggested_sl_time=None,
        gap_pct=None,
        fallback_sl=fallback_sl,
        fallback_pct=fallback_pct,
    )

    if not access_token:
        base.error = "No Fyers access token — intraday candles unavailable; using fallback"
        base.suggested_sl = fallback_sl
        base.gap_pct = fallback_pct
        return base

    candles = _fetch_intraday_candles(access_token, symbol, trading_date, resolution)
    base.candles_fetched = len(candles)

    min_candles = strength * 2 + 1
    if len(candles) < min_candles:
        base.error = (
            f"Too few candles ({len(candles)}) to detect swings "
            f"(need ≥ {min_candles}); using fallback"
        )
        base.suggested_sl = fallback_sl
        base.gap_pct = fallback_pct
        return base

    # --- Pivot detection ---
    if side == "sell":
        raw_pivots = _detect_swing_highs(candles, strength)
        swing_levels: list[SwingLevel] = []
        for _, c in raw_pivots:
            price = c["high"]
            if price <= entry_price:
                continue  # SL for short must be ABOVE entry
            dist = abs(price - entry_price)
            swing_levels.append(SwingLevel(
                time=c["time"],
                price=round(price, 2),
                candle_open=c["open"],
                candle_high=c["high"],
                candle_low=c["low"],
                candle_close=c["close"],
                distance_from_entry=round(dist, 2),
                gap_pct=round(dist / entry_price * 100, 3),
            ))
    else:  # buy
        raw_pivots = _detect_swing_lows(candles, strength)
        swing_levels = []
        for _, c in raw_pivots:
            price = c["low"]
            if price >= entry_price:
                continue  # SL for long must be BELOW entry
            dist = abs(price - entry_price)
            swing_levels.append(SwingLevel(
                time=c["time"],
                price=round(price, 2),
                candle_open=c["open"],
                candle_high=c["high"],
                candle_low=c["low"],
                candle_close=c["close"],
                distance_from_entry=round(dist, 2),
                gap_pct=round(dist / entry_price * 100, 3),
            ))

    # Sort nearest first
    swing_levels.sort(key=lambda s: s.distance_from_entry)
    base.swing_levels = swing_levels

    if swing_levels:
        best = swing_levels[0]
        base.suggested_sl = best.price
        base.suggested_sl_time = best.time
        base.gap_pct = best.gap_pct
    else:
        direction = "above" if side == "sell" else "below"
        base.error = (
            f"No swing {'highs' if side == 'sell' else 'lows'} {direction} "
            f"entry ₹{entry_price:.2f} found; using {fallback_pct}% fallback"
        )
        base.suggested_sl = fallback_sl
        base.gap_pct = fallback_pct

    return base


def analyse_symbol_swings(
    symbol: str,
    access_token: str,
    date: str | None = None,
    resolution: str = "5",
    strength: int = 2,
) -> dict:
    """Diagnostic helper — return ALL swing highs + lows for a symbol/date.

    No entry_price needed.  Good for manual inspection of a chart's structure.
    """
    trading_date = date or _today_ist()
    candles = _fetch_intraday_candles(access_token, symbol.upper(), trading_date, resolution)
    if not candles:
        return {
            "symbol": symbol.upper(), "date": trading_date,
            "error": "No candles fetched", "swingHighs": [], "swingLows": [],
        }

    highs = _detect_swing_highs(candles, strength)
    lows  = _detect_swing_lows(candles, strength)

    def _fmt(pairs: list[tuple[int, dict]], key: str) -> list[dict]:
        return [
            {
                "index": idx,
                "time": c["time"].strftime("%H:%M"),
                "price": round(c[key], 2),
                "open": c["open"], "high": c["high"],
                "low": c["low"],  "close": c["close"],
            }
            for idx, c in pairs
        ]

    return {
        "symbol": symbol.upper(),
        "date": trading_date,
        "resolution": f"{resolution}min",
        "strength": strength,
        "totalCandles": len(candles),
        "swingHighs": _fmt(highs, "high"),
        "swingLows":  _fmt(lows,  "low"),
    }
