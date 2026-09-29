from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import logging
from typing import Any
from uuid import uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas.trade import PositionOut, Segment
from app.services import fyers_client, market_data, trading_service
from app.services.brokers.base import (
    BaseBroker,
    BrokerFunds,
    BrokerOrderRequest,
    BrokerOrderResponse,
    OrderPurpose,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)

logger = logging.getLogger(__name__)

DEFAULT_PAPER_CAPITAL = 100_000.0


class PaperBroker(BaseBroker):
    """Paper-trading broker sandbox that simulates fills, SL triggers, and positions."""

    broker_name = "paper"

    def __init__(self, user_id: ObjectId, db: AsyncIOMotorDatabase, access_token: str | None = None) -> None:
        self.user_id = user_id
        self.db = db
        self.access_token = access_token

    async def _get_access_token(self) -> str | None:
        if self.access_token:
            return self.access_token
        if self.db is not None:
            user_ids = [str(self.user_id)]
            if ObjectId.is_valid(str(self.user_id)):
                user_ids.append(ObjectId(str(self.user_id)))
            try:
                coro = self.db.fyers_credentials.find_one({"userId": {"$in": user_ids}})
                creds = await coro if inspect.isawaitable(coro) else None
                if isinstance(creds, dict):
                    self.access_token = creds.get("accessToken")
            except Exception:
                pass
        return self.access_token

    async def place_order(self, req: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place simulated paper order with serial execution lock to prevent margin race conditions."""
        async with self._get_order_lock():
            return await self._place_order_internal(req)

    async def _place_order_internal(self, req: BrokerOrderRequest) -> BrokerOrderResponse:
        if req.product_type != ProductType.INTRADAY:
            raise ValueError("Only INTRADAY orders are allowed.")

        if market_data.is_index_symbol(req.symbol):
            return BrokerOrderResponse(
                order_id=f"paper_{uuid4().hex[:12]}",
                broker=self.broker_name,
                symbol=req.symbol.upper(),
                qty=req.qty,
                filled_qty=0,
                price=float(req.price or 0.0),
                limit_price=req.limit_price,
                stop_price=req.stop_price,
                side=req.side,
                order_type=req.order_type,
                product_type=req.product_type.value,
                status=OrderStatus.REJECTED,
                purpose=req.purpose,
                parent_order_id=req.parent_order_id,
                strategy=req.strategy,
                message=f"{req.symbol} is an index. Only tradeable equity stocks are permitted.",
                placed_at=datetime.now(timezone.utc),
                executed_at=None,
            )

        token = await self._get_access_token()
        quote = market_data.get_quote(req.symbol, access_token=token)
        ltp = quote.ltp if quote and quote.ltp > 0 else 100.0
        now = req.executed_at or req.placed_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        order_id = f"paper_{uuid4().hex[:12]}"

        # If an explicit entry price was provided (e.g. strategy trigger price), honor it
        exec_price = float(req.price) if (req.price is not None and req.price > 0) else ltp

        # Enforce account limits for ENTRY orders (configurable capital, 5x leverage, max positions)
        if req.purpose == OrderPurpose.ENTRY:
            # User Rule: Strictly no fresh entries before 09:30 AM IST (04:00 UTC) or after 02:30 PM IST (09:00 UTC)
            now_utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
            time_min = now_utc.hour * 60 + now_utc.minute
            if time_min < 240 or time_min > 540:
                return BrokerOrderResponse(
                    order_id=order_id,
                    broker=self.broker_name,
                    symbol=req.symbol.upper(),
                    qty=req.qty,
                    filled_qty=0,
                    price=exec_price,
                    limit_price=req.limit_price,
                    stop_price=req.stop_price,
                    side=req.side,
                    order_type=req.order_type,
                    product_type=req.product_type.value,
                    status=OrderStatus.REJECTED,
                    purpose=req.purpose,
                    parent_order_id=req.parent_order_id,
                    strategy=req.strategy,
                    message="No fresh entry orders allowed before 09:30 AM IST or after 02:30 PM IST (only position exits allowed).",
                    placed_at=now,
                    executed_at=None,
                )

            cfg = await trading_service.get_user_trading_config(self.user_id, self.db)
            max_positions = int(cfg.get("maxOpenPositions", 10))
            session_date = now.date().isoformat()
            positions = await self.get_positions(target_date=session_date)
            # Enforce single entry per symbol per session date
            s_start = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
            s_end = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
            existing_entry = await self.db.paper_orders.find_one({
                "userId": {"$in": self._user_ids()},
                "symbol": req.symbol.upper(),
                "purpose": OrderPurpose.ENTRY.value,
                "placedAt": {"$gte": s_start, "$lte": s_end},
                "status": {"$in": [OrderStatus.OPEN.value, OrderStatus.FILLED.value]},
            })
            if existing_entry:
                return BrokerOrderResponse(
                    order_id=order_id,
                    broker=self.broker_name,
                    symbol=req.symbol.upper(),
                    qty=req.qty,
                    filled_qty=0,
                    price=exec_price,
                    status=OrderStatus.REJECTED,
                    purpose=req.purpose,
                    message=f"Duplicate entry rejected: Position already exists for {req.symbol.upper()} on {session_date}.",
                    placed_at=now,
                    executed_at=None,
                )

            open_syms = {p.symbol for p in positions if p.netQty != 0}
            if req.symbol.upper() not in open_syms and len(open_syms) >= max_positions:
                return BrokerOrderResponse(
                    order_id=order_id,
                    broker=self.broker_name,
                    symbol=req.symbol.upper(),
                    qty=req.qty,
                    filled_qty=0,
                    price=exec_price,
                    limit_price=req.limit_price,
                    stop_price=req.stop_price,
                    side=req.side,
                    order_type=req.order_type,
                    product_type=req.product_type.value,
                    status=OrderStatus.REJECTED,
                    purpose=req.purpose,
                    parent_order_id=req.parent_order_id,
                    strategy=req.strategy,
                    message=f"Maximum {max_positions} concurrent open positions reached.",
                    placed_at=now,
                    executed_at=None,
                )

            funds = await self.get_funds(target_date=session_date)
            margin_required = round((req.qty * exec_price) / 5.0, 2)
            if margin_required > funds.available_balance:
                return BrokerOrderResponse(
                    order_id=order_id,
                    broker=self.broker_name,
                    symbol=req.symbol.upper(),
                    qty=req.qty,
                    filled_qty=0,
                    price=exec_price,
                    limit_price=req.limit_price,
                    stop_price=req.stop_price,
                    side=req.side,
                    order_type=req.order_type,
                    product_type=req.product_type.value,
                    status=OrderStatus.REJECTED,
                    purpose=req.purpose,
                    parent_order_id=req.parent_order_id,
                    strategy=req.strategy,
                    message=f"Insufficient margin: Required ₹{margin_required:,.2f} exceeds available ₹{funds.available_balance:,.2f}.",
                    placed_at=now,
                    executed_at=None,
                )

        # Market orders fill immediately; SL orders stay OPEN until stopPrice is hit
        if req.order_type == OrderType.MARKET:
            fill_price = exec_price
            status = OrderStatus.FILLED
            executed_at = now
        elif req.order_type == OrderType.LIMIT:
            fill_price = req.limit_price or exec_price
            status = OrderStatus.FILLED
            executed_at = now
        elif req.order_type in (OrderType.SL_M, OrderType.SL_L):
            fill_price = req.stop_price or ltp
            status = OrderStatus.OPEN
            executed_at = None
        else:
            fill_price = exec_price
            status = OrderStatus.FILLED
            executed_at = now

        order_doc = {
            "_id": order_id,
            "userId": self.user_id,
            "broker": self.broker_name,
            "symbol": req.symbol.upper(),
            "qty": req.qty,
            "filledQty": req.qty if status == OrderStatus.FILLED else 0,
            "price": fill_price,
            "limitPrice": req.limit_price,
            "stopPrice": req.stop_price,
            "side": req.side.value,
            "orderType": req.order_type.value,
            "productType": req.product_type.value,
            "status": status.value,
            "purpose": req.purpose.value,
            "parentOrderId": req.parent_order_id,
            "strategy": req.strategy,
            "placedAt": now,
            "executedAt": executed_at,
        }
        await self.db.paper_orders.insert_one(order_doc)

        # If filled, also record in paper_trades ledger so compute_positions picks it up
        if status == OrderStatus.FILLED:
            trade_doc = {
                "userId": self.user_id,
                "symbol": req.symbol.upper(),
                "segment": Segment.intraday.value,
                "side": req.side.value,
                "qty": req.qty,
                "price": fill_price,
                "orderType": req.order_type.value,
                "status": "filled",
                "executedAt": now,
                "orderId": order_id,
                "purpose": req.purpose.value,
            }
            await self.db.paper_trades.insert_one(trade_doc)

        return BrokerOrderResponse(
            order_id=order_id,
            broker=self.broker_name,
            symbol=req.symbol.upper(),
            qty=req.qty,
            filled_qty=req.qty if status == OrderStatus.FILLED else 0,
            price=fill_price,
            limit_price=req.limit_price,
            stop_price=req.stop_price,
            side=req.side,
            order_type=req.order_type,
            product_type=req.product_type.value,
            status=status,
            purpose=req.purpose,
            parent_order_id=req.parent_order_id,
            strategy=req.strategy,
            message="Simulated order placed successfully",
            placed_at=now,
            executed_at=executed_at,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open paper order."""
        res = await self.db.paper_orders.update_one(
            {"_id": order_id, "userId": self.user_id, "status": OrderStatus.OPEN.value},
            {"$set": {"status": OrderStatus.CANCELLED.value}},
        )
        return res.modified_count > 0

    def _user_ids(self) -> list[Any]:
        uid_str = str(self.user_id)
        return [uid_str, ObjectId(uid_str)] if ObjectId.is_valid(uid_str) else [self.user_id]

    async def get_orders(self, target_date: str | None = None) -> list[BrokerOrderResponse]:
        """Fetch paper orders for the user, checking if open SL orders should trigger."""
        await self._check_sl_triggers(target_date)
        session_date = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query: dict[str, Any] = {"userId": {"$in": self._user_ids()}}
        start_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        end_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999)
        query["placedAt"] = {"$gte": start_dt, "$lte": end_dt}
        cursor = self.db.paper_orders.find(query).sort([("placedAt", -1), ("symbol", 1), ("purpose", 1)])
        orders: list[BrokerOrderResponse] = []
        async for doc in cursor:
            orders.append(
                BrokerOrderResponse(
                    order_id=str(doc["_id"]),
                    broker=self.broker_name,
                    symbol=doc["symbol"],
                    qty=doc["qty"],
                    filled_qty=doc.get("filledQty", 0),
                    price=doc.get("price", 0.0),
                    limit_price=doc.get("limitPrice"),
                    stop_price=doc.get("stopPrice"),
                    side=OrderSide(doc["side"]),
                    order_type=OrderType(doc["orderType"]),
                    product_type=doc.get("productType", "INTRADAY"),
                    status=OrderStatus(doc["status"]),
                    purpose=OrderPurpose(doc.get("purpose", "entry")),
                    parent_order_id=doc.get("parentOrderId"),
                    strategy=doc.get("strategy"),
                    placed_at=doc["placedAt"],
                    executed_at=doc.get("executedAt"),
                )
            )
        return orders

    async def _check_sl_triggers(self, target_date: str | None = None) -> None:
        """Evaluate open SL orders against triggers, live quotes, or historical session candles.
        
        Strictly scopes to the target session date:
        1. Checks intraday_triggers if slHitAt was recorded.
        2. In live session (today), checks real-time quotes.
        3. In completed or historical sessions, checks 5m candles.
        4. If session has completed and SL was never hit, auto-squares off at session close.
        """
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        sess_date = target_date or today_str

        start_dt = datetime.fromisoformat(sess_date).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        end_dt = datetime.fromisoformat(sess_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999)

        open_sls = await self.db.paper_orders.find(
            {
                "userId": {"$in": self._user_ids()},
                "status": OrderStatus.OPEN.value,
                "orderType": {"$in": [OrderType.SL_M.value, OrderType.SL_L.value]},
                "placedAt": {"$gte": start_dt, "$lte": end_dt},
            }
        ).to_list(length=None)

        if not open_sls:
            return

        token = await self._get_access_token()
        is_today = (sess_date == today_str)

        for sl in open_sls:
            sym = sl["symbol"].upper()
            stop_price = sl.get("stopPrice")
            if not stop_price:
                continue
            side = str(sl["side"]).lower()
            placed_at = sl.get("placedAt") or start_dt
            if placed_at.tzinfo is None:
                placed_at = placed_at.replace(tzinfo=timezone.utc)

            triggered = False
            fill_price = stop_price
            exec_time = now
            purpose = OrderPurpose.STOP_LOSS.value

            # 1. Check if intraday_triggers recorded an SL hit
            trig = await self.db.intraday_triggers.find_one({
                "symbol": sym,
                "date": sess_date,
                "slHitAt": {"$ne": None},
            })
            if trig and trig.get("slHitAt"):
                triggered = True
                fill_price = stop_price
                hit_dt = trig["slHitAt"]
                exec_time = hit_dt.astimezone(timezone.utc) if hit_dt.tzinfo else hit_dt.replace(tzinfo=timezone.utc)

            # 2. If live today, check current LTP quote
            if not triggered and is_today:
                quote = market_data.get_quote(sym, access_token=token)
                if quote and quote.ltp > 0:
                    if (side == "sell" and quote.ltp <= stop_price) or (side == "buy" and quote.ltp >= stop_price):
                        triggered = True
                        fill_price = stop_price
                        exec_time = now

            # 3. If past day or not triggered, check 5m session candles
            if not triggered:
                try:
                    resp = fyers_client.get_history(token, sym, resolution="5", date_from=sess_date, date_to=sess_date)
                    candles = resp.get("candles") or []
                    placed_ts = placed_at.timestamp()
                    for c in candles:
                        c_ts = c[0]
                        if c_ts < placed_ts:
                            continue
                        c_low = c[3]
                        c_high = c[2]
                        if (side == "sell" and c_low <= stop_price) or (side == "buy" and c_high >= stop_price):
                            triggered = True
                            fill_price = stop_price
                            exec_time = datetime.fromtimestamp(c_ts, tz=timezone.utc)
                            break

                except Exception as c_exc:
                    logger.debug("Candle check error for %s on %s: %s", sym, sess_date, c_exc)

            if triggered:
                updated = await self.db.paper_orders.find_one_and_update(
                    {"_id": sl["_id"], "status": OrderStatus.OPEN.value},
                    {
                        "$set": {
                            "status": OrderStatus.FILLED.value,
                            "filledQty": sl["qty"],
                            "price": fill_price,
                            "executedAt": exec_time,
                        }
                    },
                )
                if not updated:
                    continue

                existing_trade = await self.db.paper_trades.find_one({"orderId": str(sl["_id"])})
                if not existing_trade:
                    await self.db.paper_trades.insert_one(
                        {
                            "userId": self.user_id,
                            "symbol": sym,
                            "segment": Segment.intraday.value,
                            "side": side,
                            "qty": sl["qty"],
                            "price": fill_price,
                            "orderType": sl["orderType"],
                            "status": "filled",
                            "executedAt": exec_time,
                            "orderId": str(sl["_id"]),
                            "purpose": purpose,
                        }
                    )

    async def get_positions(self, target_date: str | None = None) -> list[PositionOut]:
        """Derive positions from trade ledger. Intraday positions are strictly scoped to the session date."""
        await self._check_sl_triggers(target_date)
        session_date = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query: dict[str, Any] = {"userId": {"$in": self._user_ids()}, "segment": Segment.intraday.value}
        start_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        end_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999)
        query["executedAt"] = {"$gte": start_dt, "$lte": end_dt}
        trades = await self.db.paper_trades.find(query).to_list(length=None)

        # Build sl_map from paper_orders for this session date
        orders_cursor = self.db.paper_orders.find({
            "userId": {"$in": self._user_ids()},
            "placedAt": {"$gte": start_dt, "$lte": end_dt},
        })
        orders = await orders_cursor.to_list(length=None)
        sl_map: dict[str, float] = {}
        for o in orders:
            sym = o.get("symbol", "").upper()
            if o.get("stopPrice"):
                sl_map[sym] = float(o["stopPrice"])
            elif o.get("purpose") == "stop_loss" and o.get("price"):
                sl_map[sym] = float(o["price"])

        # Also fallback to intraday_triggers for base strategy SL and fallback SL
        strat_sl_map: dict[str, float] = {}
        trig_cursor = self.db.intraday_triggers.find({"date": session_date})
        triggers = await trig_cursor.to_list(length=None)
        for tr in triggers:
            sym = tr.get("symbol", "").upper()
            base_sl = tr.get("tightStop") or tr.get("stopLoss")
            if base_sl:
                strat_sl_map[sym] = float(base_sl)
            if sym not in sl_map and base_sl:
                sl_map[sym] = float(base_sl)

        token = await self._get_access_token()
        return trading_service.compute_positions(
            trades,
            access_token=token,
            target_date=session_date,
            sl_map=sl_map,
            strat_sl_map=strat_sl_map,
        )

    _order_lock: asyncio.Lock | None = None

    @classmethod
    def _get_order_lock(cls) -> asyncio.Lock:
        if cls._order_lock is None:
            cls._order_lock = asyncio.Lock()
        return cls._order_lock

    async def get_funds(self, target_date: str | None = None) -> BrokerFunds:
        """Simulated funds with 5x leverage. Each trading day has fresh 1L capital reset."""
        session_date = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        positions = await self.get_positions(target_date=session_date)
        active_positions = [p for p in positions if p.netQty != 0]
        utilized_margin = sum(p.investedValue / 5.0 for p in active_positions)  # 5x leverage utilized
        unrealized_pnl = sum(p.pnl for p in active_positions)

        # Compute realized PnL from closed trades for this session
        start_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        end_dt = datetime.fromisoformat(session_date).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999)
        query = {"userId": {"$in": self._user_ids()}, "segment": Segment.intraday.value, "executedAt": {"$gte": start_dt, "$lte": end_dt}}
        trades = await self.db.paper_trades.find(query).to_list(length=None)
        realized_pnl = trading_service.compute_realized_pnl(trades)

        cfg = await trading_service.get_user_trading_config(self.user_id, self.db)
        paper_capital = float(cfg.get("paperCapital", DEFAULT_PAPER_CAPITAL))

        total = paper_capital + realized_pnl + unrealized_pnl
        avail = max(0.0, total - utilized_margin)
        buying_power = round(avail * 5.0, 2)

        return BrokerFunds(
            broker=self.broker_name,
            available_balance=round(avail, 2),
            total_balance=round(total, 2),
            utilized_margin=round(utilized_margin, 2),
            realized_pnl=round(realized_pnl, 2),
            buying_power_5x=buying_power,
        )
