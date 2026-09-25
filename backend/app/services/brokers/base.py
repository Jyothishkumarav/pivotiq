from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.trade import PositionOut


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    SL_M = "sl_m"  # Stop-Loss Market (Trigger price, executes at market)
    SL_L = "sl_l"  # Stop-Loss Limit (Trigger price + Limit price)


class ProductType(str, Enum):
    INTRADAY = "INTRADAY"  # Strictly Intraday / MIS only


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderPurpose(str, Enum):
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    EXIT = "exit"


class BrokerOrderRequest(BaseModel):
    symbol: str
    qty: int = Field(gt=0)
    side: OrderSide
    order_type: OrderType
    product_type: ProductType = ProductType.INTRADAY
    price: float | None = None  # Executed / trigger / requested price
    limit_price: float | None = None
    stop_price: float | None = None  # Trigger price for SL-M / SL-L
    purpose: OrderPurpose = OrderPurpose.ENTRY
    parent_order_id: str | None = None
    strategy: str | None = None
    tag: str | None = None
    placed_at: datetime | None = None
    executed_at: datetime | None = None


class BrokerOrderResponse(BaseModel):
    order_id: str
    broker: str
    symbol: str
    qty: int
    filled_qty: int = 0
    price: float = 0.0
    limit_price: float | None = None
    stop_price: float | None = None
    side: OrderSide
    order_type: OrderType
    product_type: str = "INTRADAY"
    status: OrderStatus
    purpose: OrderPurpose = OrderPurpose.ENTRY
    parent_order_id: str | None = None
    strategy: str | None = None
    message: str | None = None
    placed_at: datetime
    executed_at: datetime | None = None
    raw: dict[str, Any] | None = None


class BrokerFunds(BaseModel):
    broker: str
    available_balance: float
    total_balance: float
    utilized_margin: float = 0.0
    realized_pnl: float = 0.0
    buying_power_5x: float  # available_balance * 5.0


class BaseBroker(ABC):
    """Abstract interface that every supported broker provider must implement."""

    broker_name: str

    @abstractmethod
    async def place_order(self, req: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place an order with the broker (enforcing INTRADAY product type)."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open / pending order."""
        pass

    @abstractmethod
    async def get_orders(self) -> list[BrokerOrderResponse]:
        """Fetch the order book for the current session."""
        pass

    @abstractmethod
    async def get_positions(self) -> list[PositionOut]:
        """Fetch current open positions."""
        pass

    @abstractmethod
    async def get_funds(self) -> BrokerFunds:
        """Fetch available margin and fund limits."""
        pass
