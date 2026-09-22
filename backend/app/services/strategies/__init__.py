"""Pluggable intraday trade-setup strategies.

Each watchlist picks a strategy by name (defaults to `"orb_vwap"`, the
original behaviour — untouched). `intraday_analysis.compute_snapshot`
dispatches to the matching module based on this registry.
"""

from __future__ import annotations

DEFAULT_STRATEGY = "orb_vwap"

# "orb_vwap" is handled inline in intraday_analysis.py (the original,
# unmodified logic) — it's not a module here to guarantee zero behavior
# change for existing callers. Anything else must be a real module below.
STRATEGY_NAMES = ("orb_vwap", "context_gated", "orb_pullback", "orb_pullback_support", "orb_flow")


def is_valid_strategy(name: str) -> bool:
    return name in STRATEGY_NAMES
