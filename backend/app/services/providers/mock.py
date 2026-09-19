"""Mock market data provider: static dataset seeded in `app.seed.mock_stocks`.

Deterministic pseudo-live quotes based on 30s time buckets. Perfect for demo
and offline dev without hitting external APIs.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from app.schemas.stock import (
    AnalystInfo,
    BalanceInfo,
    Candle,
    DividendInfo,
    Fundamentals,
    MarketInfo,
    PriceInfo,
    ProfileInfo,
    ProfitabilityInfo,
    Quote,
    StockDetails,
    StockSummary,
    ValuationInfo,
)
from app.seed.mock_stocks import MOCK_STOCKS

_BY_SYMBOL = {s["symbol"]: s for s in MOCK_STOCKS}
_REFRESH_WINDOW_SECONDS = 30


def _jitter_seed(symbol: str, bucket: int) -> float:
    digest = hashlib.sha256(f"{symbol}:{bucket}".encode()).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return (value * 2) - 1


def _current_bucket() -> int:
    return int(datetime.now(timezone.utc).timestamp() // _REFRESH_WINDOW_SECONDS)


class MockProvider:
    name = "mock"

    def search(self, query: str, limit: int = 15) -> list[StockSummary]:
        q = query.strip().lower()
        if not q:
            return []
        results = [s for s in MOCK_STOCKS if q in s["symbol"].lower() or q in s["name"].lower()]
        results.sort(key=lambda s: (not s["symbol"].lower().startswith(q), s["symbol"]))
        return [StockSummary(symbol=s["symbol"], name=s["name"], exchange=s["exchange"]) for s in results[:limit]]

    def _raw(self, symbol: str) -> dict | None:
        return _BY_SYMBOL.get(symbol.upper())

    def get_quote(self, symbol: str, access_token: str | None = None) -> Quote | None:
        raw = self._raw(symbol)
        if raw is None:
            return None
        bucket = _current_bucket()
        jitter_pct = _jitter_seed(raw["symbol"], bucket) * 0.6
        ltp = round(raw["prevClose"] * (1 + jitter_pct / 100), 2)
        ltp = max(raw["low"] * 0.98, min(raw["high"] * 1.02, ltp))
        change = round(ltp - raw["prevClose"], 2)
        change_pct = round((change / raw["prevClose"]) * 100, 2)
        return Quote(
            symbol=raw["symbol"],
            name=raw["name"],
            exchange=raw["exchange"],
            ltp=ltp,
            change=change,
            changePercent=change_pct,
            open=raw["open"],
            high=max(raw["high"], ltp),
            low=min(raw["low"], ltp),
            prevClose=raw["prevClose"],
            volume=raw["volume"],
            lastUpdated=datetime.now(timezone.utc),
        )

    def get_fundamentals(self, symbol: str) -> Fundamentals | None:
        raw = self._raw(symbol)
        if raw is None:
            return None
        return Fundamentals(
            symbol=raw["symbol"],
            marketCap=raw["marketCap"],
            peRatio=raw["peRatio"],
            pbRatio=raw["pbRatio"],
            eps=raw["eps"],
            week52High=raw["week52High"],
            week52Low=raw["week52Low"],
            dividendYield=raw["dividendYield"],
        )

    def get_prior_ohlc(self, symbol: str) -> dict | None:
        raw = self._raw(symbol)
        if raw is None:
            return None
        return {"high": raw["high"], "low": raw["low"], "close": raw["prevClose"]}

    def get_candles(self, symbol: str, period: str = "1y", interval: str = "1d", access_token: str | None = None) -> list[Candle]:
        raw = self._raw(symbol)
        if raw is None:
            return []
        days = {"1y": 252, "6mo": 126, "3mo": 63, "1mo": 21}.get(period, 252)
        base = raw["prevClose"]
        candles: list[Candle] = []
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(days, 0, -1):
            digest = hashlib.sha256(f"{raw['symbol']}:candle:{i}".encode()).hexdigest()
            drift = (int(digest[:8], 16) / 0xFFFFFFFF - 0.5) * 4  # ±2% drift
            close = base * (1 + drift / 100)
            open_ = close * (1 + ((int(digest[8:16], 16) / 0xFFFFFFFF - 0.5) * 1.5) / 100)
            high = max(open_, close) * (1 + (int(digest[16:20], 16) / 0xFFFF) * 0.01)
            low = min(open_, close) * (1 - (int(digest[20:24], 16) / 0xFFFF) * 0.01)
            volume = int(raw["volume"] * (0.5 + int(digest[24:28], 16) / 0xFFFF))
            candles.append(
                Candle(
                    time=today - timedelta(days=i),
                    open=round(open_, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=volume,
                )
            )
            base = close
        return candles

    def get_details(self, symbol: str, force_refresh: bool = False) -> StockDetails | None:
        raw = self._raw(symbol)
        if raw is None:
            return None
        return StockDetails(
            symbol=raw["symbol"],
            updatedAt=datetime.now(timezone.utc),
            source="mock",
            profile=ProfileInfo(shortName=raw["name"]),
            price=PriceInfo(
                previousClose=raw["prevClose"],
                open=raw["open"],
                dayLow=raw["low"],
                dayHigh=raw["high"],
                fiftyTwoWeekLow=raw["week52Low"],
                fiftyTwoWeekHigh=raw["week52High"],
            ),
            valuation=ValuationInfo(
                trailingPE=raw["peRatio"],
                priceToBook=raw["pbRatio"],
            ),
            market=MarketInfo(marketCap=raw["marketCap"], volume=raw["volume"]),
            profitability=ProfitabilityInfo(trailingEps=raw["eps"]),
            balance=BalanceInfo(),
            dividend=DividendInfo(dividendYield=raw["dividendYield"]),
            analyst=AnalystInfo(),
        )

    def symbol_exists(self, symbol: str) -> bool:
        return symbol.upper() in _BY_SYMBOL
