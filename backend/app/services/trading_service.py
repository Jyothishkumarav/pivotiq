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


async def get_user_trading_config(user_id: ObjectId | str, db: AsyncIOMotorDatabase | None) -> dict:
    """Fetch user's dynamic trading settings (paper capital, tight SL buffer %, risk, active watchlist)."""
    default_config = {
        "paperCapital": 100_000.0,
        "slBufferPct": 25.0,
        "maxRiskPerTrade": 1100.0,
        "maxOpenPositions": 10,
        "activeWatchlistId": None,
    }
    if db is None:
        return default_config
    try:
        user_ids = [str(user_id)]
        if ObjectId.is_valid(str(user_id)):
            user_ids.append(ObjectId(str(user_id)))
        doc = await db.user_settings.find_one({"userId": {"$in": user_ids}, "type": "trading_config"})
        if doc and "config" in doc and isinstance(doc["config"], dict):
            cfg = dict(default_config)
            cfg.update(doc["config"])
            return cfg
    except Exception:
        pass
    return default_config


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


def compute_positions(trades: list[dict], access_token: str | None = None) -> list[PositionOut]:
    filled = [t for t in trades if str(t.get("status", "")).lower() == OrderStatus.filled.value]
    filled.sort(key=lambda t: t.get("executedAt") or datetime.min.replace(tzinfo=timezone.utc))

    state: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "netQty": 0,
            "avgPrice": 0.0,
            "entryAvgPrice": 0.0,
            "totalEntryQty": 0,
            "lastExitPrice": 0.0,
            "realizedPnl": 0.0,
            "firstBoughtAt": None,
            "lastTransactionAt": None,
        }
    )
    for t in filled:
        key = (str(t.get("symbol", "")).upper(), t.get("segment", Segment.intraday.value))
        s = state[key]
        exec_at = t.get("executedAt") or datetime.now(timezone.utc)
        if isinstance(exec_at, datetime) and exec_at.tzinfo is None:
            exec_at = exec_at.replace(tzinfo=timezone.utc)
        s["lastTransactionAt"] = exec_at
        qty = int(t.get("qty", 0))
        price = float(t.get("price", 0.0))
        side = str(t.get("side", "buy")).lower()

        if s["netQty"] == 0:
            s["firstBoughtAt"] = exec_at
            s["avgPrice"] = price
            s["entryAvgPrice"] = price
            s["totalEntryQty"] += qty
            s["netQty"] = qty if side == "buy" else -qty
        elif s["netQty"] > 0:
            if side == "buy":
                new_qty = s["netQty"] + qty
                s["avgPrice"] = ((s["avgPrice"] * s["netQty"]) + (price * qty)) / new_qty if new_qty else price
                s["entryAvgPrice"] = s["avgPrice"]
                s["totalEntryQty"] += qty
                s["netQty"] = new_qty
            else:  # selling to close/reduce long
                closed = min(qty, s["netQty"])
                s["realizedPnl"] += (price - s["avgPrice"]) * closed
                s["lastExitPrice"] = price
                rem = qty - closed
                s["netQty"] -= closed
                if rem > 0:
                    s["netQty"] = -rem
                    s["avgPrice"] = price
                    s["entryAvgPrice"] = price
                    s["totalEntryQty"] += rem
                    s["firstBoughtAt"] = exec_at
        else:  # s["netQty"] < 0 (Short position)
            curr_abs = abs(s["netQty"])
            if side == "sell":
                new_abs = curr_abs + qty
                s["avgPrice"] = ((s["avgPrice"] * curr_abs) + (price * qty)) / new_abs if new_abs else price
                s["entryAvgPrice"] = s["avgPrice"]
                s["totalEntryQty"] += qty
                s["netQty"] = -new_abs
            else:  # side == "buy" (covering short, e.g. SL hit)
                closed = min(qty, curr_abs)
                s["realizedPnl"] += (s["avgPrice"] - price) * closed
                s["lastExitPrice"] = price
                rem = qty - closed
                new_abs = curr_abs - closed
                if rem > 0:
                    s["netQty"] = rem
                    s["avgPrice"] = price
                    s["entryAvgPrice"] = price
                    s["totalEntryQty"] += rem
                    s["firstBoughtAt"] = exec_at
                elif new_abs == 0:
                    s["netQty"] = 0
                else:
                    s["netQty"] = -new_abs

    from app.services.market_data import is_index_symbol

    positions: list[PositionOut] = []
    for (symbol, segment), s in state.items():
        if is_index_symbol(symbol):
            continue
        if s["totalEntryQty"] == 0 and s["netQty"] == 0:
            continue

        quote = market_data.get_quote(symbol, access_token=access_token)
        change_pct = float(quote.changePercent) if quote is not None else 0.0
        last_updated = quote.lastUpdated if quote is not None else (s["lastTransactionAt"] or datetime.now(timezone.utc))

        if s["netQty"] != 0:
            # Active open position
            ltp = float(quote.ltp) if quote is not None else float(s["avgPrice"])
            abs_qty = abs(s["netQty"])
            invested = round(s["avgPrice"] * abs_qty, 2)
            current_value = round(ltp * abs_qty, 2)
            if s["netQty"] > 0:
                unrealized = current_value - invested
            else:
                unrealized = invested - current_value
            pnl = round(s["realizedPnl"] + unrealized, 2)
            pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0
            display_avg = round(s["avgPrice"], 2)
        else:
            # Closed position (SL Hit or squared off)
            exit_price = s["lastExitPrice"] if s["lastExitPrice"] > 0 else (float(quote.ltp) if quote else s["entryAvgPrice"])
            ltp = round(exit_price, 2)
            invested = 0.0
            current_value = 0.0
            pnl = round(s["realizedPnl"], 2)
            initial_val = s["entryAvgPrice"] * max(1, s["totalEntryQty"])
            pnl_pct = round((pnl / initial_val) * 100, 2) if initial_val else 0.0
            display_avg = round(s["entryAvgPrice"], 2)

        positions.append(
            PositionOut(
                symbol=symbol,
                segment=Segment(segment),
                netQty=s["netQty"],
                avgPrice=display_avg,
                ltp=ltp,
                currentValue=current_value,
                investedValue=invested,
                pnl=pnl,
                pnlPercent=pnl_pct,
                dayChangePercent=change_pct,
                lastUpdated=last_updated,
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
    pnl = round(sum(p.pnl for p in relevant), 2)
    pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0
    today_pnl = round(sum(_today_pnl_for_position(p) for p in relevant), 2)
    active_count = len([p for p in relevant if p.netQty != 0])
    return PortfolioSummary(
        segment=segment or "combined",
        investedValue=invested,
        currentValue=current,
        pnl=pnl,
        pnlPercent=pnl_pct,
        todayPnl=today_pnl,
        holdingsCount=active_count,
    )


def compute_realized_pnl(trades: list[dict[str, Any]]) -> float:
    """Computes total realized P&L across all closed positions from filled trades."""
    filled = [t for t in trades if str(t.get("status", "")).lower() == "filled"]
    filled.sort(key=lambda t: t.get("executedAt") or datetime.min.replace(tzinfo=timezone.utc))
    state: dict[str, dict[str, Any]] = defaultdict(lambda: {"netQty": 0, "avgPrice": 0.0})
    realized_pnl = 0.0

    for t in filled:
        sym = str(t.get("symbol", "")).upper()
        s = state[sym]
        qty = int(t.get("qty", 0))
        price = float(t.get("price", 0.0))
        side = str(t.get("side", "buy")).lower()

        if s["netQty"] == 0:
            s["avgPrice"] = price
            s["netQty"] = qty if side == "buy" else -qty
        elif s["netQty"] > 0:
            if side == "buy":
                new_qty = s["netQty"] + qty
                s["avgPrice"] = ((s["avgPrice"] * s["netQty"]) + (price * qty)) / new_qty if new_qty else price
                s["netQty"] = new_qty
            else:  # selling to close/reduce long
                closed = min(qty, s["netQty"])
                realized_pnl += (price - s["avgPrice"]) * closed
                s["netQty"] -= closed
                rem = qty - closed
                if rem > 0:
                    s["netQty"] = -rem
                    s["avgPrice"] = price
                elif s["netQty"] == 0:
                    s["avgPrice"] = 0.0
        else:  # s["netQty"] < 0 (Short)
            curr_abs = abs(s["netQty"])
            if side == "sell":
                new_abs = curr_abs + qty
                s["avgPrice"] = ((s["avgPrice"] * curr_abs) + (price * qty)) / new_abs if new_abs else price
                s["netQty"] = -new_abs
            else:  # buying to cover short
                closed = min(qty, curr_abs)
                realized_pnl += (s["avgPrice"] - price) * closed
                new_abs = curr_abs - closed
                rem = qty - closed
                if rem > 0:
                    s["netQty"] = rem
                    s["avgPrice"] = price
                elif new_abs == 0:
                    s["netQty"] = 0
                    s["avgPrice"] = 0.0
                else:
                    s["netQty"] = -new_abs

    return round(realized_pnl, 2)
