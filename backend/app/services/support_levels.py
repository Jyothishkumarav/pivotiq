"""Support/resistance level computation.

Two independent families per the spec:
  A. Pivot-point methods (Classic, Fibonacci, Camarilla, Woodie) from prior H/L/C.
  B. Swing-low / price-action zones (deterministically synthesized from the
     mock provider's OHLC since no historical time series is stored yet).
"""

import hashlib
from datetime import datetime, timedelta, timezone

from app.schemas.stock import SupportLevelsResponse, SupportResistanceSet, SwingZone
from app.services import market_data


def _classic(h: float, l: float, c: float) -> dict:
    pp = (h + l + c) / 3
    return {
        "pivot": pp,
        "r1": 2 * pp - l,
        "r2": pp + (h - l),
        "r3": h + 2 * (pp - l),
        "s1": 2 * pp - h,
        "s2": pp - (h - l),
        "s3": l - 2 * (h - pp),
    }


def _fibonacci(h: float, l: float, c: float) -> dict:
    pp = (h + l + c) / 3
    diff = h - l
    return {
        "pivot": pp,
        "r1": pp + 0.382 * diff,
        "r2": pp + 0.618 * diff,
        "r3": pp + 1.0 * diff,
        "s1": pp - 0.382 * diff,
        "s2": pp - 0.618 * diff,
        "s3": pp - 1.0 * diff,
    }


def _camarilla(h: float, l: float, c: float) -> dict:
    diff = h - l
    pp = (h + l + c) / 3
    return {
        "pivot": pp,
        "r1": c + (1.1 / 12) * diff,
        "r2": c + (1.1 / 6) * diff,
        "r3": c + (1.1 / 4) * diff,
        "s1": c - (1.1 / 12) * diff,
        "s2": c - (1.1 / 6) * diff,
        "s3": c - (1.1 / 4) * diff,
    }


def _woodie(h: float, l: float, c: float) -> dict:
    pp = (h + l + 2 * c) / 4
    return {
        "pivot": pp,
        "r1": 2 * pp - l,
        "r2": pp + (h - l),
        "r3": None,
        "s1": 2 * pp - h,
        "s2": pp - h + l,
        "s3": None,
    }


_METHODS = {
    "classic": _classic,
    "fibonacci": _fibonacci,
    "camarilla": _camarilla,
    "woodie": _woodie,
}


def _round_set(method: str, timeframe: str, raw: dict) -> SupportResistanceSet:
    def r(v: float | None) -> float | None:
        return None if v is None else round(v, 2)

    return SupportResistanceSet(
        method=method,
        timeframe=timeframe,
        pivot=r(raw["pivot"]),
        r1=r(raw["r1"]),
        r2=r(raw["r2"]),
        r3=r(raw["r3"]),
        s1=r(raw["s1"]),
        s2=r(raw["s2"]),
        s3=r(raw["s3"]),
    )


def _synthesize_swing_zones(symbol: str, low: float, high: float) -> list[SwingZone]:
    """Deterministic stand-in for real local-minima clustering over OHLC history."""
    zones: list[SwingZone] = []
    span = high - low
    seeds = [0.12, 0.32, 0.58]
    for i, frac in enumerate(seeds):
        digest = hashlib.sha256(f"{symbol}:zone:{i}".encode()).hexdigest()
        touch_count = 1 + (int(digest[:2], 16) % 4)
        days_ago = int(digest[2:4], 16) % 60
        zones.append(
            SwingZone(
                level=round(low + span * frac, 2),
                touchCount=touch_count,
                lastTouchedAt=datetime.now(timezone.utc) - timedelta(days=days_ago),
            )
        )
    zones.sort(key=lambda z: z.level, reverse=True)
    return zones


def compute_support_levels(symbol: str) -> SupportLevelsResponse | None:
    ohlc = market_data.get_prior_ohlc(symbol)
    if ohlc is None:
        return None
    h, l, c = ohlc["high"], ohlc["low"], ohlc["close"]

    pivot_sets = [_round_set(name, "daily", fn(h, l, c)) for name, fn in _METHODS.items()]
    swing_zones = _synthesize_swing_zones(symbol.upper(), l, h)

    return SupportLevelsResponse(
        symbol=symbol.upper(),
        computedAt=datetime.now(timezone.utc),
        pivotMethods=pivot_sets,
        swingLowZones=swing_zones,
    )


def nearest_support_below(symbol: str, current_price: float) -> float | None:
    """Highest support value that is still <= current price, across all methods."""
    levels = compute_support_levels(symbol)
    if levels is None:
        return None
    candidates: list[float] = []
    for pivot_set in levels.pivotMethods:
        for v in (pivot_set.s1, pivot_set.s2, pivot_set.s3):
            if v is not None and v <= current_price:
                candidates.append(v)
    for zone in levels.swingLowZones:
        if zone.level <= current_price:
            candidates.append(zone.level)
    return max(candidates) if candidates else None
