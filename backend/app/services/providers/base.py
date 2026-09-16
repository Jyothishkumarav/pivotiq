from typing import Protocol

from app.schemas.stock import Candle, Fundamentals, Quote, StockDetails, StockSummary


class MarketDataProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 15) -> list[StockSummary]: ...

    def get_quote(self, symbol: str, access_token: str | None = None) -> Quote | None: ...

    def get_fundamentals(self, symbol: str) -> Fundamentals | None: ...

    def get_details(self, symbol: str, force_refresh: bool = False) -> StockDetails | None: ...

    def get_prior_ohlc(self, symbol: str) -> dict | None: ...

    def get_candles(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        access_token: str | None = None,
    ) -> list[Candle]: ...

    def symbol_exists(self, symbol: str) -> bool: ...
