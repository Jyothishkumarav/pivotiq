"""Market data facade.

Dispatches to one of two swappable providers:

  - `real` (default): DB search on `stock_symbols` + Yahoo Finance for quotes,
    fundamentals, and historical OHLC.
  - `mock`: deterministic offline dataset for demos.

The active provider is a process-level runtime switch — flip it via
`/settings/data-source` at any time.
"""

from __future__ import annotations

import threading
from typing import Literal

from app.schemas.stock import Candle, Fundamentals, Quote, StockDetails, StockSummary
from app.services.market_context import current_fyers_token
from app.services.providers.base import MarketDataProvider
from app.services.providers.mock import MockProvider

ProviderMode = Literal["real", "mock"]

_lock = threading.Lock()
_mode: ProviderMode = "real"
_providers: dict[str, MarketDataProvider] = {}


def _get() -> MarketDataProvider:
    with _lock:
        if _mode not in _providers:
            if _mode == "mock":
                _providers["mock"] = MockProvider()
            else:
                # Imported lazily so a broken yfinance/mongo install doesn't
                # take down the process when only 'mock' is used.
                from app.services.providers.real import RealProvider

                _providers["real"] = RealProvider()
        return _providers[_mode]


def get_mode() -> ProviderMode:
    return _mode


def set_mode(mode: ProviderMode) -> None:
    global _mode
    if mode not in ("real", "mock"):
        raise ValueError(f"Unknown provider mode: {mode}")
    with _lock:
        _mode = mode


# ---------------- Public API (unchanged signatures) ----------------


def search(query: str, limit: int = 15) -> list[StockSummary]:
    return _get().search(query, limit)


def get_quote(symbol: str, access_token: str | None = None) -> Quote | None:
    return _get().get_quote(symbol, access_token=access_token or current_fyers_token())


def get_fundamentals(symbol: str) -> Fundamentals | None:
    return _get().get_fundamentals(symbol)


def get_details(symbol: str, force_refresh: bool = False) -> StockDetails | None:
    return _get().get_details(symbol, force_refresh=force_refresh)


def get_prior_ohlc(symbol: str) -> dict | None:
    return _get().get_prior_ohlc(symbol)


def get_candles(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    access_token: str | None = None,
) -> list[Candle]:
    return _get().get_candles(
        symbol,
        period=period,
        interval=interval,
        access_token=access_token or current_fyers_token(),
    )


def symbol_exists(symbol: str) -> bool:
    return _get().symbol_exists(symbol)
