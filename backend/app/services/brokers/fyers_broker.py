from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.schemas.trade import PositionOut, Segment
from app.services import fyers_client
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
from app.services.fyers_client import FyersError, nse_symbol

logger = logging.getLogger(__name__)

# Fyers numeric status mapping to standard OrderStatus
FYERS_STATUS_MAP: dict[int, OrderStatus] = {
    1: OrderStatus.CANCELLED,
    2: OrderStatus.FILLED,
    4: OrderStatus.OPEN,      # Transit / In-process
    5: OrderStatus.REJECTED,
    6: OrderStatus.OPEN,      # Pending / Trigger-pending
}


class FyersBroker(BaseBroker):
    """Production broker integration with Fyers API v3."""

    broker_name = "fyers"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def _map_order_type_and_prices(
        self, req: BrokerOrderRequest
    ) -> tuple[int, float, float]:
        """Maps OrderType to Fyers API v3 (type, limitPrice, stopPrice).

        1 => Limit Order
        2 => Market Order
        3 => Stop Order (SL-M)
        4 => Stoplimit Order (SL-L)
        """
        if req.order_type == OrderType.MARKET:
            return 2, 0.0, 0.0
        elif req.order_type == OrderType.LIMIT:
            if req.limit_price is None or req.limit_price <= 0:
                raise ValueError("Limit price must be greater than 0 for LIMIT orders")
            return 1, float(req.limit_price), 0.0
        elif req.order_type == OrderType.SL_M:
            if req.stop_price is None or req.stop_price <= 0:
                raise ValueError("Stop price must be greater than 0 for SL-M orders")
            return 3, 0.0, float(req.stop_price)
        elif req.order_type == OrderType.SL_L:
            if req.stop_price is None or req.stop_price <= 0:
                raise ValueError("Stop price must be greater than 0 for SL-L orders")
            if req.limit_price is None or req.limit_price <= 0:
                raise ValueError("Limit price must be greater than 0 for SL-L orders")
            return 4, float(req.limit_price), float(req.stop_price)
        raise ValueError(f"Unsupported order type: {req.order_type}")

    async def place_order(self, req: BrokerOrderRequest) -> BrokerOrderResponse:
        """Place an order with Fyers API v3. Enforces strictly INTRADAY."""
        if req.product_type != ProductType.INTRADAY:
            raise ValueError("Only INTRADAY (MIS) orders are permitted on Fyers.")

        fyers_type, limit_price, stop_price = self._map_order_type_and_prices(req)
        fyers_side = 1 if req.side == OrderSide.BUY else -1
        sym = nse_symbol(req.symbol)

        payload: dict[str, Any] = {
            "symbol": sym,
            "qty": int(req.qty),
            "type": fyers_type,
            "side": fyers_side,
            "productType": "INTRADAY",
            "limitPrice": limit_price,
            "stopPrice": stop_price,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "stopLoss": 0,
            "takeProfit": 0,
        }

        try:
            res = fyers_client.place_order(self.access_token, payload)
        except FyersError as exc:
            logger.error("Fyers place_order failed for %s: %s", req.symbol, exc)
            return BrokerOrderResponse(
                order_id="",
                broker=self.broker_name,
                symbol=req.symbol.upper(),
                qty=req.qty,
                filled_qty=0,
                price=limit_price,
                limit_price=req.limit_price,
                stop_price=req.stop_price,
                side=req.side,
                order_type=req.order_type,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=req.purpose,
                parent_order_id=req.parent_order_id,
                strategy=req.strategy,
                message=str(exc),
                placed_at=datetime.now(timezone.utc),
                raw={"error": str(exc)},
            )

        order_id = str(res.get("id") or "")
        msg = str(res.get("message") or "Order placed successfully")
        status_val = OrderStatus.OPEN if res.get("s") == "ok" else OrderStatus.REJECTED

        return BrokerOrderResponse(
            order_id=order_id,
            broker=self.broker_name,
            symbol=req.symbol.upper(),
            qty=req.qty,
            filled_qty=0,
            price=limit_price,
            limit_price=req.limit_price,
            stop_price=req.stop_price,
            side=req.side,
            order_type=req.order_type,
            product_type="INTRADAY",
            status=status_val,
            purpose=req.purpose,
            parent_order_id=req.parent_order_id,
            strategy=req.strategy,
            message=msg,
            placed_at=datetime.now(timezone.utc),
            raw=res,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order with Fyers."""
        try:
            res = fyers_client.cancel_order(self.access_token, order_id)
            return res.get("s") == "ok"
        except FyersError as exc:
            logger.warning("Fyers cancel_order error for %s: %s", order_id, exc)
            return False

    async def get_orders(self) -> list[BrokerOrderResponse]:
        """Fetch today's orders from Fyers."""
        try:
            res = fyers_client.get_orders(self.access_token)
        except FyersError as exc:
            logger.warning("Fyers get_orders failed: %s", exc)
            return []

        orders_list = (
            res.get("orderBook")
            or res.get("orders")
            or (res.get("data") or {}).get("orders")
            or []
        )

        # Also fetch GTT orders if any
        try:
            import requests
            from app.config import get_settings
            headers = {"Authorization": f"{get_settings().fyers_app_id}:{self.access_token}"}
            gtt_res = requests.get("https://api-t1.fyers.in/api/v3/gtt/orders", headers=headers, timeout=10)
            if gtt_res.status_code == 200:
                gtt_data = gtt_res.json()
                gtt_orders = gtt_data.get("orderBook") or gtt_data.get("orders") or []
                orders_list = list(orders_list) + list(gtt_orders)
        except Exception as gtt_exc:
            logger.debug("Fyers gtt/orders fetch optional check: %s", gtt_exc)

        out: list[BrokerOrderResponse] = []
        for o in orders_list:
            status_code = o.get("status", 6)
            std_status = FYERS_STATUS_MAP.get(status_code, OrderStatus.OPEN)
            side = OrderSide.BUY if o.get("side") == 1 else OrderSide.SELL
            fyers_type = o.get("type", 2)
            if fyers_type == 1:
                ot = OrderType.LIMIT
            elif fyers_type == 3:
                ot = OrderType.SL_M
            elif fyers_type == 4:
                ot = OrderType.SL_L
            else:
                ot = OrderType.MARKET

            raw_sym = str(o.get("symbol") or "")
            clean_sym = raw_sym.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-INDEX", "")

            # Infer purpose
            purpose = OrderPurpose.ENTRY
            if ot in (OrderType.SL_M, OrderType.SL_L):
                purpose = OrderPurpose.STOP_LOSS
            elif side == OrderSide.SELL:
                purpose = OrderPurpose.EXIT

            out.append(
                BrokerOrderResponse(
                    order_id=str(o.get("id") or ""),
                    broker=self.broker_name,
                    symbol=clean_sym,
                    qty=int(o.get("qty", 0) or o.get("quantity", 0)),
                    filled_qty=int(o.get("filledQty", 0)),
                    price=float(o.get("tradedPrice") or o.get("limitPrice") or 0.0),
                    limit_price=float(o.get("limitPrice")) if o.get("limitPrice") else None,
                    stop_price=float(o.get("stopPrice")) if o.get("stopPrice") else None,
                    side=side,
                    order_type=ot,
                    product_type=str(o.get("productType") or "INTRADAY"),
                    status=std_status,
                    purpose=purpose,
                    message=o.get("message"),
                    placed_at=datetime.now(timezone.utc),
                    raw=o,
                )
            )
        return out

    async def get_positions(self) -> list[PositionOut]:
        """Fetch current positions and delivery holdings from Fyers."""
        out: list[PositionOut] = []
        now = datetime.now(timezone.utc)

        # 1. Fetch Intraday & Net Positions
        try:
            res = fyers_client.get_positions(self.access_token)
            net_pos = (
                res.get("netPositions")
                or res.get("positions")
                or (res.get("data") or {}).get("positions")
                or []
            )
            for p in net_pos:
                net_qty = int(p.get("netQty", 0) or p.get("qty", 0))
                if net_qty == 0:
                    continue
                raw_sym = str(p.get("symbol") or "")
                clean_sym = raw_sym.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-INDEX", "")
                avg_price = float(p.get("avgPrice") or p.get("buyAvg") or 0.0)
                ltp = float(p.get("ltp") or 0.0)
                pnl = float(p.get("pl") or p.get("pnl") or 0.0)
                invested = round(avg_price * net_qty, 2)
                current_val = round(ltp * net_qty, 2)
                pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0
                prod_type = str(p.get("productType", "INTRADAY")).upper()
                seg = Segment.delivery if prod_type in ("CNC", "DELIVERY") else Segment.intraday

                out.append(
                    PositionOut(
                        symbol=clean_sym,
                        segment=seg,
                        netQty=net_qty,
                        avgPrice=avg_price,
                        ltp=ltp,
                        currentValue=current_val,
                        investedValue=invested,
                        pnl=pnl,
                        pnlPercent=pnl_pct,
                        dayChangePercent=0.0,
                        lastUpdated=now,
                    )
                )
        except FyersError as exc:
            logger.warning("Fyers get_positions failed: %s", exc)

        # 2. Fetch Delivery Holdings (CNC)
        try:
            h_res = fyers_client.get_holdings(self.access_token)
            holdings_list = h_res.get("holdings") or []
            existing_syms = {p.symbol for p in out}
            for h in holdings_list:
                raw_sym = str(h.get("symbol") or "")
                clean_sym = raw_sym.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "").replace("-INDEX", "")
                if clean_sym in existing_syms:
                    continue
                qty = int(h.get("remainingQuantity") or h.get("quantity") or 0)
                if qty <= 0:
                    continue
                cost_price = float(h.get("costPrice") or 0.0)
                ltp = float(h.get("ltp") or 0.0)
                pnl = float(h.get("pl") or 0.0)
                invested = round(cost_price * qty, 2)
                current_val = round(ltp * qty, 2)
                pnl_pct = round((pnl / invested) * 100, 2) if invested else 0.0

                out.append(
                    PositionOut(
                        symbol=clean_sym,
                        segment=Segment.delivery,
                        netQty=qty,
                        avgPrice=cost_price,
                        ltp=ltp,
                        currentValue=current_val,
                        investedValue=invested,
                        pnl=pnl,
                        pnlPercent=pnl_pct,
                        dayChangePercent=0.0,
                        lastUpdated=now,
                    )
                )
        except FyersError as exc:
            logger.warning("Fyers get_holdings failed: %s", exc)

        return out

    async def get_funds(self) -> BrokerFunds:
        """Fetch available funds and buying power with 5x intraday leverage."""
        import time
        from app.services.cache import get_cache_client
        cache = None
        cache_key = f"fyers:funds:{self.access_token[-12:]}" if len(self.access_token) >= 12 else "fyers:funds:default"
        try:
            cache = get_cache_client()
            if cache:
                cached = cache.get_json(cache_key)
                if cached and (time.time() - cached.get("_cached_at", 0)) < 30:
                    return BrokerFunds(**{k: v for k, v in cached.items() if not k.startswith("_")})
        except Exception:
            pass

        try:
            res = fyers_client.get_funds(self.access_token)
        except FyersError as exc:
            logger.warning("Fyers get_funds failed: %s", exc)
            if cache:
                try:
                    cached = cache.get_json(cache_key)
                    if cached and cached.get("available_balance", 0) > 0:
                        logger.info("Using cached Fyers funds (₹%.2f) due to rate limit/error", cached["available_balance"])
                        return BrokerFunds(**{k: v for k, v in cached.items() if not k.startswith("_")})
                except Exception:
                    pass
            return BrokerFunds(
                broker=self.broker_name,
                available_balance=0.0,
                total_balance=0.0,
                utilized_margin=0.0,
                realized_pnl=0.0,
                buying_power_5x=0.0,
            )

        fund_limits = res.get("fund_limit") or []
        avail_bal = 0.0
        total_bal = 0.0
        utilized = 0.0
        realized_pnl = 0.0

        for f in fund_limits:
            title = str(f.get("title", "")).strip().lower()
            amt = float(f.get("equityAmount", 0.0))
            if "available balance" in title:
                avail_bal = amt
            elif "total balance" in title:
                total_bal = amt
            elif "utilized amount" in title:
                utilized = amt
            elif "realized profit and loss" in title:
                realized_pnl = amt

        if total_bal <= 0 and avail_bal > 0:
            total_bal = avail_bal + utilized

        buying_power = round(avail_bal * 5.0, 2)
        funds = BrokerFunds(
            broker=self.broker_name,
            available_balance=round(avail_bal, 2),
            total_balance=round(total_bal, 2),
            utilized_margin=round(utilized, 2),
            realized_pnl=round(realized_pnl, 2),
            buying_power_5x=buying_power,
        )
        if cache and avail_bal > 0:
            try:
                data = funds.model_dump()
                data["_cached_at"] = time.time()
                cache.set_json(cache_key, data, ttl_seconds=600)
            except Exception:
                pass
        return funds

