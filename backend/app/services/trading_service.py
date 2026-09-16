"""Paper-trading engine: simulated fills, position aggregation, portfolio summary.

No real money and no real order routing — orders are filled against the mock
market-data provider's current price. Positions are derived on read from the
trade ledger (average-cost method) rather than maintained as separate mutable
state, keeping the ledger the single source of truth.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas.trade import OrderStatus, PortfolioSummary, PositionOut, Segment
from app.services import market_data


def resolve_fill_price(order_type: str, side: str, limit_price: float | None, ltp: float) -> tuple[float, str]:
    """Every paper order fills immediately.

    * `market` → fills at the current LTP.
    * `limit`  → fills at exactly the user-specified limit price, regardless of
      whether the market has "reached" it. This is a strategy-testing sandbox,
      not an order book — the user picks the price they want to record their
      hypothetical entry/exit at.
    """
    if order_type == "market":
        return ltp, OrderStatus.filled.value
    assert limit_price is not None
    return limit_price, OrderStatus.filled.value


async def fill_pending_limits(db: AsyncIOMotorDatabase, user_id: ObjectId) -> int:
    """One-time migration for orders placed under the older "wait for price"
    behaviour. Immediately fills any open limit order at its stored limit price."""
    open_orders: list[dict[str, Any]] = await db.paper_trades.find(
        {
            "userId": user_id,
            "status": OrderStatus.open.value,
            "orderType": "limit",
        }
    ).to_list(length=None)

    if not open_orders:
        return 0

    now = datetime.now(timezone.utc)
    for order in open_orders:
        await db.paper_trades.update_one(
            {"_id": order["_id"]},
            {"$set": {"status": OrderStatus.filled.value, "executedAt": now}},
        )
    return len(open_orders)


def compute_positions(trades: list[dict]) -> list[PositionOut]:
    filled = [t for t in trades if t["status"] == OrderStatus.filled.value]
    filled.sort(key=lambda t: t["executedAt"])

    state: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"netQty": 0, "avgPrice": 0.0, "firstBoughtAt": None, "lastTransactionAt": None}
    )
    for t in filled:
        key = (t["symbol"], t["segment"])
        s = state[key]
        s["lastTransactionAt"] = t["executedAt"]
        if t["side"] == "buy":
            # Track when the position was opened; reset on full sell-out below.
            if s["netQty"] == 0:
                s["firstBoughtAt"] = t["executedAt"]
            new_qty = s["netQty"] + t["qty"]
            s["avgPrice"] = ((s["avgPrice"] * s["netQty"]) + (t["price"] * t["qty"])) / new_qty if new_qty else 0.0
            s["netQty"] = new_qty
        else:
            sell_qty = min(t["qty"], s["netQty"]) if s["netQty"] > 0 else 0
            s["netQty"] -= sell_qty
            if s["netQty"] == 0:
                s["avgPrice"] = 0.0
                s["firstBoughtAt"] = None

    positions: list[PositionOut] = []
    for (symbol, segment), s in state.items():
        if s["netQty"] <= 0:
            continue
        quote = market_data.get_quote(symbol)
        if quote is None:
            continue
        invested = round(s["avgPrice"] * s["netQty"], 2)
        current_value = round(quote.ltp * s["netQty"], 2)
        pnl = round(current_value - invested, 2)
        pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0
        positions.append(
            PositionOut(
                symbol=symbol,
                segment=Segment(segment),
                netQty=s["netQty"],
                avgPrice=round(s["avgPrice"], 2),
                ltp=quote.ltp,
                currentValue=current_value,
                investedValue=invested,
                pnl=pnl,
                pnlPercent=pnl_pct,
                dayChangePercent=quote.changePercent,
                lastUpdated=quote.lastUpdated,
                firstBoughtAt=s["firstBoughtAt"],
                lastTransactionAt=s["lastTransactionAt"],
            )
        )
    return positions


def _today_pnl_for_position(position: PositionOut) -> float:
    """No separate "start of day" price is tracked, so today's P&L is the
    same entry-price-vs-current-price gain as the position's total P&L.
    """
    return position.pnl


def compute_portfolio_summary(positions: list[PositionOut], segment: str | None) -> PortfolioSummary:
    relevant = positions if segment is None else [p for p in positions if p.segment.value == segment]
    invested = round(sum(p.investedValue for p in relevant), 2)
    current = round(sum(p.currentValue for p in relevant), 2)
    pnl = round(current - invested, 2)
    pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0
    today_pnl = round(sum(_today_pnl_for_position(p) for p in relevant), 2)
    return PortfolioSummary(
        segment=segment or "combined",
        investedValue=invested,
        currentValue=current,
        pnl=pnl,
        pnlPercent=pnl_pct,
        todayPnl=today_pnl,
        holdingsCount=len(relevant),
    )
