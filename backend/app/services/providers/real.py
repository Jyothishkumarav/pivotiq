"""Real market data provider.

Search  → MongoDB `stock_symbols` collection (populated via
          `scripts/import_nse500.py`).
Data    → Yahoo Finance via `yfinance` (NSE symbols get a `.NS` suffix).

Yahoo's API is unofficial — every request is cached in memory with a short
TTL (30s for quotes, 24h for fundamentals/history) to avoid rate-limiting.
DB snapshot fields serve as a fallback when Yahoo fails or returns partial
data.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

import yfinance as yf
from pymongo import MongoClient

from app.config import get_settings
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
from app.services import fyers_client
from app.services.fyers_client import FyersError, FyersTokenExpired

logger = logging.getLogger(__name__)

_QUOTE_TTL_SECONDS = 30
_LONG_TTL_SECONDS = 24 * 60 * 60
_CANDLES_TTL_SECONDS = 4 * 60 * 60
# When Yahoo returns a 429 (or any error), skip that symbol for this long.
_YAHOO_COOLDOWN_SECONDS = 15 * 60

T = TypeVar("T")


def _build_yf_session():
    """Return a Chrome-impersonating session (per yfinance docs) that dodges most
    Yahoo 429 rate limits. Falls back to yfinance's default session if curl_cffi
    isn't available at runtime."""
    try:
        from curl_cffi import requests as curl_requests

        return curl_requests.Session(impersonate="chrome")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("curl_cffi session unavailable, falling back to default: %s", exc)
        return None


class _TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, ttl_seconds: int, factory: Callable[[], T]) -> T:
        now = time.time()
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and now - hit[0] < ttl_seconds:
                return hit[1]
        value = factory()
        # Only cache truthy / non-empty results so a failed fetch (None / {} / empty
        # dict from a 429) doesn't poison the cache for the full TTL window.
        if value:
            with self._lock:
                self._store[key] = (now, value)
        return value


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        n = float(value)
        if n != n:  # NaN
            return None
        return n
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


class RealProvider:
    name = "real"

    def __init__(self) -> None:
        settings = get_settings()
        # Use a dedicated sync PyMongo client — RealProvider is used from the
        # threadpool where sync I/O is appropriate.
        self._client = MongoClient(settings.mongo_uri)
        try:
            self._db = self._client.get_default_database()
        except Exception:
            self._db = self._client[settings.mongo_db_name]
        self._cache = _TTLCache()
        self._session = _build_yf_session()
        self._yahoo_cooldown_until: dict[str, float] = {}
        self._cooldown_lock = threading.Lock()

    def _in_cooldown(self, symbol: str) -> bool:
        with self._cooldown_lock:
            until = self._yahoo_cooldown_until.get(symbol, 0.0)
        return time.time() < until

    def _mark_cooldown(self, symbol: str) -> None:
        with self._cooldown_lock:
            self._yahoo_cooldown_until[symbol] = time.time() + _YAHOO_COOLDOWN_SECONDS

    def _yf_symbol(self, symbol: str) -> str:
        return f"{symbol.upper()}.NS"

    def _ticker(self, symbol: str) -> "yf.Ticker":
        return yf.Ticker(self._yf_symbol(symbol))

    def _snapshot_from_db(self, symbol: str) -> dict | None:
        doc = self._db.stock_symbols.find_one({"symbol": symbol.upper()})
        return doc.get("snapshot") if doc else None

    def _invalidate_fyers_credentials(self, access_token: str) -> None:
        """Clear the stored credential that Fyers has told us is dead so the UI
        immediately reflects `Not connected` and stops burning requests."""
        try:
            self._db.fyers_credentials.delete_many({"accessToken": access_token})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to invalidate expired Fyers credential: %s", exc)

    # ---------------- Search ----------------
    def search(self, query: str, limit: int = 15) -> list[StockSummary]:
        q = query.strip()
        if not q:
            return []
        pattern = re.escape(q)
        cursor = self._db.stock_symbols.find(
            {
                "$or": [
                    {"symbol": {"$regex": f"^{pattern}", "$options": "i"}},
                    {"symbol": {"$regex": pattern, "$options": "i"}},
                    {"name": {"$regex": pattern, "$options": "i"}},
                ]
            },
            {"symbol": 1, "name": 1, "exchange": 1},
        ).limit(limit)

        results = list(cursor)
        results.sort(
            key=lambda d: (
                0 if d["symbol"].upper().startswith(q.upper()) else 1,
                d["symbol"],
            )
        )
        return [
            StockSummary(
                symbol=d["symbol"],
                name=d.get("name") or d["symbol"],
                exchange=d.get("exchange", "NSE"),
            )
            for d in results[:limit]
        ]

    # ---------------- Quote ----------------
    def _fetch_fast_info(self, symbol: str) -> dict:
        try:
            ticker = self._ticker(symbol)
            info = ticker.fast_info
            return {
                "ltp": _num(info.get("last_price")),
                "open": _num(info.get("open")),
                "high": _num(info.get("day_high")),
                "low": _num(info.get("day_low")),
                "prevClose": _num(info.get("previous_close")),
                "volume": _int(info.get("last_volume")) or _int(info.get("regular_market_volume")),
            }
        except Exception as exc:
            logger.warning("yfinance fast_info failed for %s: %s", symbol, exc)
            return {}

    def _fetch_quote_from_fyers(self, symbol: str, access_token: str) -> Quote | None:
        try:
            resp = fyers_client.get_quotes(access_token, [symbol])
        except FyersTokenExpired as exc:
            logger.warning("Fyers token expired for %s: %s", symbol, exc)
            self._invalidate_fyers_credentials(access_token)
            return None
        except FyersError as exc:
            logger.warning("Fyers quote failed for %s: %s", symbol, exc)
            return None
        data = resp.get("d") or []
        row = next((r for r in data if r.get("s") == "ok"), None)
        v = (row or {}).get("v") or {}
        ltp = _num(v.get("lp"))
        prev_close = _num(v.get("prev_close_price"))
        if ltp is None or prev_close is None:
            return None
        change = _num(v.get("ch")) or round(ltp - prev_close, 2)
        change_pct = _num(v.get("chp")) or (round((change / prev_close) * 100, 2) if prev_close else 0.0)
        return Quote(
            symbol=symbol.upper(),
            name=v.get("description") or v.get("short_name") or symbol.upper(),
            exchange=v.get("exchange") or "NSE",
            ltp=round(ltp, 2),
            change=round(change, 2),
            changePercent=round(change_pct, 2),
            open=round(_num(v.get("open_price")) or prev_close, 2),
            high=round(_num(v.get("high_price")) or ltp, 2),
            low=round(_num(v.get("low_price")) or ltp, 2),
            prevClose=round(prev_close, 2),
            volume=int(_num(v.get("volume")) or 0),
            lastUpdated=datetime.now(timezone.utc),
        )

    def get_quote(self, symbol: str, access_token: str | None = None) -> Quote | None:
        symbol = symbol.upper()
        snapshot = self._snapshot_from_db(symbol)
        if snapshot is None:
            return None

        if access_token:
            quote = self._fetch_quote_from_fyers(symbol, access_token)
            if quote is not None:
                return quote

        yq = self._cache.get_or_set(
            f"quote:{symbol}", _QUOTE_TTL_SECONDS, lambda: self._fetch_fast_info(symbol)
        )

        ltp = yq.get("ltp") or snapshot.get("ltp") or snapshot.get("prevClose")
        prev_close = yq.get("prevClose") or snapshot.get("prevClose")
        if ltp is None or prev_close is None:
            return None

        open_ = yq.get("open") or snapshot.get("open") or prev_close
        high = yq.get("high") or snapshot.get("high") or ltp
        low = yq.get("low") or snapshot.get("low") or ltp
        volume = yq.get("volume") or snapshot.get("volume") or 0

        change = round(ltp - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

        return Quote(
            symbol=symbol,
            name=symbol,
            exchange="NSE",
            ltp=round(ltp, 2),
            change=change,
            changePercent=change_pct,
            open=round(open_, 2),
            high=round(high, 2),
            low=round(low, 2),
            prevClose=round(prev_close, 2),
            volume=int(volume),
            lastUpdated=datetime.now(timezone.utc),
        )

    # ---------------- Fundamentals ----------------
    def _fetch_info(self, symbol: str) -> dict:
        if self._in_cooldown(symbol):
            return {}
        try:
            info = self._ticker(symbol).info or {}
        except Exception as exc:
            logger.warning("yfinance info failed for %s: %s", symbol, exc)
            self._mark_cooldown(symbol)
            info = {}

        div_yield = info.get("dividendYield")
        if div_yield is not None and div_yield < 1:
            div_yield = div_yield * 100  # yfinance returns fraction sometimes

        return {
            "marketCap": _num(info.get("marketCap")),
            "peRatio": _num(info.get("trailingPE")),
            "pbRatio": _num(info.get("priceToBook")),
            "eps": _num(info.get("trailingEps")),
            "week52High": _num(info.get("fiftyTwoWeekHigh")),
            "week52Low": _num(info.get("fiftyTwoWeekLow")),
            "dividendYield": _num(div_yield),
        }

    def get_fundamentals(self, symbol: str) -> Fundamentals | None:
        symbol = symbol.upper()
        snapshot = self._snapshot_from_db(symbol)
        if snapshot is None:
            return None

        info = self._cache.get_or_set(
            f"info:{symbol}", _LONG_TTL_SECONDS, lambda: self._fetch_info(symbol)
        )

        # If yfinance failed and we have no meaningful snapshot fundamentals
        # either, prefer to return None so the UI hides the card rather than
        # showing a wall of zeros.
        has_any = any(
            v is not None
            for v in (
                info.get("marketCap"),
                info.get("peRatio"),
                info.get("pbRatio"),
                info.get("eps"),
                snapshot.get("week52High"),
                snapshot.get("week52Low"),
            )
        )
        if not has_any:
            return None

        return Fundamentals(
            symbol=symbol,
            marketCap=info.get("marketCap") or 0.0,
            peRatio=info.get("peRatio") or 0.0,
            pbRatio=info.get("pbRatio") or 0.0,
            eps=info.get("eps") or 0.0,
            week52High=info.get("week52High") or snapshot.get("week52High") or 0.0,
            week52Low=info.get("week52Low") or snapshot.get("week52Low") or 0.0,
            dividendYield=info.get("dividendYield") or 0.0,
        )

    # ---------------- Prior OHLC (for pivot calc) ----------------
    def _fetch_prior_ohlc(self, symbol: str) -> dict | None:
        if self._in_cooldown(symbol):
            return None
        try:
            hist = self._ticker(symbol).history(period="5d", auto_adjust=False)
            if hist is None or hist.empty or len(hist) < 2:
                return None
            prior = hist.iloc[-2]
            return {
                "high": float(prior["High"]),
                "low": float(prior["Low"]),
                "close": float(prior["Close"]),
            }
        except Exception as exc:
            logger.warning("yfinance history failed for %s: %s", symbol, exc)
            self._mark_cooldown(symbol)
            return None

    def get_prior_ohlc(self, symbol: str) -> dict | None:
        symbol = symbol.upper()
        result = self._cache.get_or_set(
            f"prior:{symbol}", _LONG_TTL_SECONDS, lambda: self._fetch_prior_ohlc(symbol)
        )
        if result is not None:
            return result

        snapshot = self._snapshot_from_db(symbol)
        if snapshot is None:
            return None
        # Fallback: use today's H/L and prevClose from the daily CSV snapshot.
        # Not strictly "prior" but the closest we have without history.
        if snapshot.get("high") and snapshot.get("low") and snapshot.get("prevClose"):
            return {
                "high": snapshot["high"],
                "low": snapshot["low"],
                "close": snapshot["prevClose"],
            }
        return None

    # ---------------- Comprehensive details ----------------
    def _fetch_full_info(self, symbol: str, bypass_cooldown: bool = False) -> dict | None:
        if not bypass_cooldown and self._in_cooldown(symbol):
            return None
        try:
            info = self._ticker(symbol).info or {}
            if not info or (len(info) < 5 and not info.get("regularMarketPrice")):
                return None
            return info
        except Exception as exc:
            logger.warning("yfinance full info failed for %s: %s", symbol, exc)
            self._mark_cooldown(symbol)
            return None

    def _persist_details(self, symbol: str, info: dict) -> None:
        try:
            self._db.stock_details.update_one(
                {"symbol": symbol},
                {
                    "$set": {
                        "symbol": symbol,
                        "raw": info,
                        "updatedAt": datetime.now(timezone.utc),
                        "source": "yahoo",
                    },
                    "$setOnInsert": {"createdAt": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
        except Exception as exc:
            logger.warning("Failed to persist stock_details for %s: %s", symbol, exc)

    def _load_details(self, symbol: str) -> tuple[dict, str, datetime | None] | None:
        doc = self._db.stock_details.find_one({"symbol": symbol})
        if not doc or not doc.get("raw"):
            return None
        return doc["raw"], doc.get("source", "cache"), doc.get("updatedAt")

    def _map_details(self, symbol: str, info: dict, source: str, updated_at: datetime | None = None) -> StockDetails:
        div_yield = info.get("dividendYield")
        if div_yield is not None and div_yield < 1:
            div_yield = div_yield * 100

        return StockDetails(
            symbol=symbol,
            updatedAt=updated_at or datetime.now(timezone.utc),
            source=source,  # type: ignore[arg-type]
            profile=ProfileInfo(
                shortName=info.get("shortName") or info.get("longName"),
                sector=info.get("sector"),
                sectorDisp=info.get("sectorDisp"),
                industry=info.get("industry"),
                industryDisp=info.get("industryDisp"),
            ),
            price=PriceInfo(
                regularMarketPrice=_num(info.get("regularMarketPrice") or info.get("currentPrice")),
                previousClose=_num(info.get("previousClose") or info.get("regularMarketPreviousClose")),
                open=_num(info.get("open") or info.get("regularMarketOpen")),
                dayLow=_num(info.get("dayLow") or info.get("regularMarketDayLow")),
                dayHigh=_num(info.get("dayHigh") or info.get("regularMarketDayHigh")),
                regularMarketChange=_num(info.get("regularMarketChange")),
                regularMarketChangePercent=_num(info.get("regularMarketChangePercent")),
                fiftyTwoWeekLow=_num(info.get("fiftyTwoWeekLow")),
                fiftyTwoWeekHigh=_num(info.get("fiftyTwoWeekHigh")),
                allTimeLow=_num(info.get("allTimeLow")),
                allTimeHigh=_num(info.get("allTimeHigh")),
                fiftyDayAverage=_num(info.get("fiftyDayAverage")),
                twoHundredDayAverage=_num(info.get("twoHundredDayAverage")),
                twoHundredDayAverageChange=_num(info.get("twoHundredDayAverageChange")),
                twoHundredDayAverageChangePercent=_num(info.get("twoHundredDayAverageChangePercent")),
            ),
            valuation=ValuationInfo(
                trailingPE=_num(info.get("trailingPE")),
                forwardPE=_num(info.get("forwardPE")),
                pegRatio=_num(info.get("pegRatio") or info.get("peg Ratio")),
                trailingPegRatio=_num(info.get("trailingPegRatio") or info.get("trailing Peg Ratio")),
                priceToBook=_num(info.get("priceToBook")),
                priceToSalesTrailing12Months=_num(info.get("priceToSalesTrailing12Months")),
                priceEpsCurrentYear=_num(info.get("priceEpsCurrentYear")),
                beta=_num(info.get("beta")),
            ),
            market=MarketInfo(
                marketCap=_num(info.get("marketCap")),
                nonDilutedMarketCap=_num(info.get("nonDilutedMarketCap")),
                volume=_int(info.get("volume") or info.get("regularMarketVolume")),
                averageVolume=_int(info.get("averageVolume")),
                averageVolume10days=_int(info.get("averageVolume10days") or info.get("averageDailyVolume10Day")),
            ),
            profitability=ProfitabilityInfo(
                profitMargins=_num(info.get("profitMargins")),
                operatingMargins=_num(info.get("operatingMargins")),
                returnOnEquity=_num(info.get("returnOnEquity")),
                returnOnAssets=_num(info.get("returnOnAssets")),
                trailingEps=_num(info.get("trailingEps")),
                revenuePerShare=_num(info.get("revenuePerShare")),
                revenueGrowth=_num(info.get("revenueGrowth")),
            ),
            balance=BalanceInfo(
                totalCash=_num(info.get("totalCash")),
                totalCashPerShare=_num(info.get("totalCashPerShare")),
                totalDebt=_num(info.get("totalDebt")),
                totalRevenue=_num(info.get("totalRevenue")),
                operatingCashflow=_num(info.get("operatingCashflow")),
                quickRatio=_num(info.get("quickRatio")),
            ),
            dividend=DividendInfo(
                dividendRate=_num(info.get("dividendRate")),
                dividendYield=_num(div_yield),
            ),
            analyst=AnalystInfo(
                numberOfAnalystOpinions=_int(info.get("numberOfAnalystOpinions")),
                recommendationKey=info.get("recommendationKey"),
                recommendationMean=_num(info.get("recommendationMean")),
                targetLowPrice=_num(info.get("targetLowPrice")),
                targetHighPrice=_num(info.get("targetHighPrice")),
                targetMeanPrice=_num(info.get("targetMeanPrice")),
                targetMedianPrice=_num(info.get("targetMedianPrice")),
            ),
        )

    def get_details(self, symbol: str, force_refresh: bool = False) -> StockDetails | None:
        symbol = symbol.upper()
        if not self.symbol_exists(symbol):
            return None

        # 1. Unless the caller explicitly refreshes, prefer the DB doc.
        if not force_refresh:
            cached = self._load_details(symbol)
            if cached is not None:
                info, source, updated_at = cached
                return self._map_details(symbol, info, source, updated_at)

        # 2. DB miss (or refresh) → try Yahoo.
        info = self._fetch_full_info(symbol, bypass_cooldown=force_refresh)
        if info is not None:
            self._persist_details(symbol, info)
            return self._map_details(symbol, info, "yahoo")

        # 3. Yahoo failed and we haven't got a DB doc — synthesize from snapshot
        #    so the UI still shows real data. Do NOT persist synthesized info to
        #    stock_details; it's a stopgap, and we want a real Yahoo fetch to
        #    populate it later.
        synth = self._snapshot_to_info(symbol)
        if synth:
            return self._map_details(symbol, synth, "snapshot")
        return None

    def _resolve_details(self, symbol: str) -> tuple[dict, str] | None:
        """Legacy helper retained for backward compatibility; unused by new flow."""
        info = self._fetch_full_info(symbol)
        if info is not None:
            self._persist_details(symbol, info)
            return info, "yahoo"
        cached = self._load_details(symbol)
        if cached is not None:
            return cached[0], "cache"
        synth = self._snapshot_to_info(symbol)
        if synth:
            return synth, "snapshot"
        return None

    def _snapshot_to_info(self, symbol: str) -> dict:
        snapshot = self._snapshot_from_db(symbol)
        if not snapshot:
            return {}
        return {
            "shortName": symbol,
            "regularMarketPrice": snapshot.get("ltp"),
            "previousClose": snapshot.get("prevClose"),
            "open": snapshot.get("open"),
            "dayHigh": snapshot.get("high"),
            "dayLow": snapshot.get("low"),
            "regularMarketChange": snapshot.get("change"),
            "regularMarketChangePercent": snapshot.get("changePercent"),
            "fiftyTwoWeekHigh": snapshot.get("week52High"),
            "fiftyTwoWeekLow": snapshot.get("week52Low"),
            "volume": snapshot.get("volume"),
        }

    # ---------------- Existence ----------------
    def symbol_exists(self, symbol: str) -> bool:
        return self._db.stock_symbols.count_documents({"symbol": symbol.upper()}, limit=1) > 0

    # ---------------- Candles ----------------
    def _fetch_candles_from_fyers(self, symbol: str, access_token: str, period: str) -> list[Candle]:
        days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
        days = days_map.get(period, 365)
        date_to = datetime.now(timezone.utc).date()
        date_from = date_to - timedelta(days=days)
        try:
            resp = fyers_client.get_history(
                access_token,
                symbol,
                resolution="D",
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
            )
        except FyersTokenExpired as exc:
            logger.warning("Fyers token expired for %s: %s", symbol, exc)
            self._invalidate_fyers_credentials(access_token)
            return []
        except FyersError as exc:
            logger.warning("Fyers history failed for %s: %s", symbol, exc)
            return []
        raw = resp.get("candles") or []
        candles: list[Candle] = []
        for row in raw:
            if len(row) < 6:
                continue
            epoch, o, h, l, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(int(epoch), tz=timezone.utc),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=int(v),
                )
            )
        return candles

    def _fetch_candles(self, symbol: str, period: str, interval: str) -> list[Candle]:
        if self._in_cooldown(symbol):
            return []
        try:
            hist = self._ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
            if hist is None or hist.empty:
                return []
            candles: list[Candle] = []
            for ts, row in hist.iterrows():
                close = row["Close"]
                # Skip in-progress / incomplete rows (Yahoo returns NaN for them).
                if close != close:
                    continue
                dt = ts.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                candles.append(
                    Candle(
                        time=dt,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(close),
                        volume=int(row["Volume"]),
                    )
                )
            return candles
        except Exception as exc:
            logger.warning("yfinance history failed for %s (%s/%s): %s", symbol, period, interval, exc)
            self._mark_cooldown(symbol)
            return []

    def get_candles(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        access_token: str | None = None,
    ) -> list[Candle]:
        symbol = symbol.upper()
        if access_token:
            fkey = f"candles-fyers:{symbol}:{period}:{interval}"
            fcandles = self._cache.get_or_set(
                fkey, _CANDLES_TTL_SECONDS, lambda: self._fetch_candles_from_fyers(symbol, access_token, period)
            )
            if fcandles:
                return fcandles

        cache_key = f"candles:{symbol}:{period}:{interval}"
        return self._cache.get_or_set(
            cache_key, _CANDLES_TTL_SECONDS, lambda: self._fetch_candles(symbol, period, interval)
        )
