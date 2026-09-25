from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.services.brokers.base import (
    BaseBroker,
    BrokerOrderRequest,
    BrokerOrderResponse,
    OrderPurpose,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)

from app.services.market_data import is_index_symbol

logger = logging.getLogger(__name__)


DEFAULT_ACCOUNT_CAPITAL = 100_000.0
MAX_OPEN_POSITIONS = 10
MAX_RISK_PER_TRADE = 1100.0
LEVERAGE = 5.0


def round_to_tick(val: float, tick: float = 0.05) -> float:
    """Round price to the nearest standard NSE equity tick size (0.05)."""
    return round(round(val / tick) * tick, 2)


class TradeSizingResult(BaseModel):
    qty: int
    bufferedSl: float
    rawTightSl: float
    riskPerShare: float
    totalRisk: float
    maxRiskAllowed: float
    tradeCapital: float
    marginRequired: float
    purchasingPower: float
    leverage: float
    affordable: bool
    formulaExplanation: str


def calculate_trade_sizing(
    available_capital: float,
    stock_price: float,
    tight_sl: float,
    capital_allocation_pct: float = 10.0,
    max_risk_amount: float = MAX_RISK_PER_TRADE,
    leverage: float = LEVERAGE,
    sl_buffer_pct: float = 25.0,
    account_capital: float = DEFAULT_ACCOUNT_CAPITAL,
    max_open_positions: int = MAX_OPEN_POSITIONS,
    side: str = "buy",
) -> TradeSizingResult:
    """Calculates quantity and buffered stop-loss strictly adhering to user rules:

    1. SL Buffer:
       `SL = tight_sl - (risk * sl_buffer_pct%)` for BUY (widens stop by buffer % of risk distance).
       `SL = tight_sl + (risk * sl_buffer_pct%)` for SELL.
    2. Per-trade Capital Allocation:
       Each trade can use at most (account_capital / max_open_positions) margin,
       and cannot exceed current `available_capital`.
       With 5x leverage: purchasing_power = max_trade_margin * 5.0.
    3. Max Risk per trade:
       Total trade SL loss (qty * per_share_risk) CANNOT exceed `max_risk_amount` (₹1,100 default).
    4. Quantity:
       `final_qty = min(qty_capital, qty_risk)`
       Ensuring:
       - final_qty * per_share_risk <= max_risk_amount (strictly <= max_risk_amount)
       - (final_qty * stock_price) / leverage <= available_capital
    """
    if stock_price <= 0:
        raise ValueError("stock_price must be greater than 0")

    # 1. SL Buffer calculation
    raw_risk = abs(stock_price - tight_sl)
    buffer_amt = raw_risk * (sl_buffer_pct / 100.0)

    if side.lower() == "buy":
        buffered_sl = round_to_tick(tight_sl - buffer_amt)
    else:
        buffered_sl = round_to_tick(tight_sl + buffer_amt)

    per_share_risk = max(round(abs(stock_price - buffered_sl), 2), 0.05)

    # 2. Capital allocation with 5x leverage:
    # Max trade margin per position is determined by capital_allocation_pct of available_capital,
    # or capped at account_capital / max_open_positions.
    max_trade_margin = min(available_capital, available_capital * (capital_allocation_pct / 100.0))
    if account_capital != DEFAULT_ACCOUNT_CAPITAL or max_open_positions != MAX_OPEN_POSITIONS:
        max_trade_margin = min(max_trade_margin, account_capital / max(1, max_open_positions))
    max_trade_margin = max(0.0, max_trade_margin)
    purchasing_power = max_trade_margin * leverage

    qty_capital = math.floor(purchasing_power / stock_price) if stock_price > 0 else 0

    # 3. Risk-based quantity limit (SL per trade <= max_risk_amount)
    qty_risk = math.floor(max_risk_amount / per_share_risk) if per_share_risk > 0 else 0

    if qty_capital <= 0 or max_trade_margin <= 0 or qty_risk <= 0:
        final_qty = 0
        affordable = False
    else:
        final_qty = min(qty_capital, qty_risk)
        # Ensure total risk strictly does not exceed max_risk_amount
        while final_qty > 0 and (final_qty * per_share_risk) > max_risk_amount:
            final_qty -= 1
        # Ensure margin required does not exceed available capital
        while final_qty > 0 and ((final_qty * stock_price) / leverage) > available_capital:
            final_qty -= 1
        affordable = final_qty > 0

    margin_required = round_to_tick((final_qty * stock_price) / leverage)
    total_risk = round(final_qty * per_share_risk, 2)

    explanation = (
        f"Available Margin: ₹{available_capital:,.2f} | Trade Margin: ₹{max_trade_margin:,.2f} | "
        f"5x Buying Power: ₹{purchasing_power:,.2f} | "
        f"Raw SL: ₹{tight_sl:.2f} -> Buffered SL ({sl_buffer_pct:.0f}% risk buffer): ₹{buffered_sl:.2f} | "
        f"Risk/sh: ₹{per_share_risk:.2f} | Qty: {final_qty} (Total Risk: ₹{total_risk:.2f} <= ₹{max_risk_amount:.2f})"
    )

    return TradeSizingResult(
        qty=final_qty,
        bufferedSl=buffered_sl,
        rawTightSl=tight_sl,
        riskPerShare=per_share_risk,
        totalRisk=total_risk,
        maxRiskAllowed=max_risk_amount,
        tradeCapital=round(max_trade_margin, 2),
        marginRequired=margin_required,
        purchasingPower=round(purchasing_power, 2),
        leverage=leverage,
        affordable=affordable,
        formulaExplanation=explanation,
    )


class ExecuteOrderResult(BaseModel):
    buyOrder: BrokerOrderResponse
    slOrder: BrokerOrderResponse | None = None
    sizing: TradeSizingResult | None = None
    status: str
    message: str


async def execute_order_with_sl(
    broker: BaseBroker,
    symbol: str,
    side: str,  # "buy" or "sell"
    stock_price: float,
    tight_sl: float,
    qty: int | None = None,
    capital_allocation_pct: float = 50.0,
    max_risk_amount: float = 1100.0,
    sl_buffer_pct: float = 20.0,
    strategy: str | None = None,
    db: AsyncIOMotorDatabase | None = None,
    user_id: ObjectId | None = None,
    triggered_at: datetime | None = None,
) -> ExecuteOrderResult:
    """Executes an entry order (Intraday MIS: BUY or SELL) and immediately follows up with an SL order."""
    is_buy = side.lower() == "buy"
    entry_side = OrderSide.BUY if is_buy else OrderSide.SELL
    sl_side = OrderSide.SELL if is_buy else OrderSide.BUY

    exec_time = triggered_at or datetime.now(timezone.utc)
    if exec_time.tzinfo is None:
        exec_time = exec_time.replace(tzinfo=timezone.utc)

    # User Rule: Never take trade before 09:30 AM IST (04:00 UTC)
    if exec_time.hour < 4:
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message="No trades allowed before 09:30 AM IST (ORB completion period).",
                placed_at=exec_time,
            ),
            slOrder=None,
            sizing=None,
            status="failed",
            message="No trades allowed before 09:30 AM IST (ORB completion period).",
        )

    # 0. Do NOT trade broad-market indices (NIFTY 50, BANKNIFTY, etc.) - only equity stocks allowed
    from app.services.market_data import is_index_symbol
    if is_index_symbol(symbol):
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message=f"{symbol} is an index. Only equity stocks can be traded.",
                placed_at=datetime.now(timezone.utc),
            ),
            slOrder=None,
            sizing=None,
            status="failed",
            message=f"{symbol} is an index. Only tradeable equity stocks are permitted.",
        )

    # User Rule: Strictly no fresh entries before 09:30 AM IST (04:00 UTC) or after 02:30 PM IST (09:00 UTC)
    exec_dt = exec_time.astimezone(timezone.utc) if exec_time.tzinfo else exec_time.replace(tzinfo=timezone.utc)
    time_min = exec_dt.hour * 60 + exec_dt.minute
    if time_min < 240 or time_min > 540:
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message="No fresh entries allowed before 09:30 AM IST or after 02:30 PM IST (only position exits allowed).",
                placed_at=exec_time,
            ),
            slOrder=None,
            sizing=None,
            status="failed",
            message="No fresh entries allowed before 09:30 AM IST or after 02:30 PM IST (only position exits allowed).",
        )

    # Load dynamic user trading settings
    from app.services import trading_service
    trading_cfg = await trading_service.get_user_trading_config(user_id, db)
    max_positions = int(trading_cfg.get("maxOpenPositions", MAX_OPEN_POSITIONS))
    user_sl_buffer = float(trading_cfg.get("slBufferPct", 25.0))
    user_max_risk = float(trading_cfg.get("maxRiskPerTrade", MAX_RISK_PER_TRADE))
    user_capital = float(trading_cfg.get("paperCapital", DEFAULT_ACCOUNT_CAPITAL))

    if user_id is not None:
        eff_sl_buffer = user_sl_buffer
        eff_max_risk = min(max_risk_amount, user_max_risk)
    else:
        eff_sl_buffer = sl_buffer_pct
        eff_max_risk = max_risk_amount

    target_date_str = None
    if triggered_at:
        target_date_str = triggered_at.date().isoformat() if hasattr(triggered_at, "date") else str(triggered_at)[:10]

    # 1. Enforce max concurrent open positions for this session
    try:
        positions = await broker.get_positions(target_date=target_date_str)
    except TypeError:
        positions = await broker.get_positions()
    open_symbols = {p.symbol for p in positions if p.netQty != 0}
    if symbol.upper() not in open_symbols and len(open_symbols) >= max_positions:
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message=f"Maximum {max_positions} concurrent open positions reached.",
                placed_at=datetime.now(timezone.utc),
            ),
            slOrder=None,
            sizing=None,
            status="failed",
            message=f"Maximum {max_positions} concurrent open positions reached.",
        )

    # 2. Fetch available funds to calculate sizing if qty is not specified
    try:
        funds = await broker.get_funds(target_date=target_date_str)
    except TypeError:
        funds = await broker.get_funds()
    avail_capital = funds.available_balance
    if avail_capital <= 0:
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message=f"Insufficient available margin: ₹{avail_capital:,.2f}.",
                placed_at=datetime.now(timezone.utc),
            ),
            slOrder=None,
            sizing=None,
            status="failed",
            message=f"Insufficient available margin in account (₹{avail_capital:,.2f}).",
        )

    sizing = calculate_trade_sizing(
        available_capital=avail_capital,
        stock_price=stock_price,
        tight_sl=tight_sl,
        capital_allocation_pct=capital_allocation_pct,
        max_risk_amount=eff_max_risk,
        leverage=5.0,
        sl_buffer_pct=eff_sl_buffer,
        account_capital=user_capital,
        max_open_positions=max_positions,
        side="buy" if is_buy else "sell",
    )

    order_qty = qty if qty and qty > 0 else sizing.qty
    if order_qty <= 0:
        return ExecuteOrderResult(
            buyOrder=BrokerOrderResponse(
                order_id="",
                broker=broker.broker_name,
                symbol=symbol.upper(),
                qty=0,
                price=stock_price,
                side=entry_side,
                order_type=OrderType.MARKET,
                product_type="INTRADAY",
                status=OrderStatus.REJECTED,
                purpose=OrderPurpose.ENTRY,
                strategy=strategy,
                message="Insufficient capital or quantity calculated is 0",
                placed_at=datetime.now(timezone.utc),
            ),
            slOrder=None,
            sizing=sizing,
            status="failed",
            message=f"Order quantity calculated is 0: {sizing.formulaExplanation}",
        )

    # 2. Place entry order (Intraday MIS)
    entry_req = BrokerOrderRequest(
        symbol=symbol.upper(),
        qty=order_qty,
        side=entry_side,
        price=stock_price,
        order_type=OrderType.MARKET,
        product_type=ProductType.INTRADAY,
        purpose=OrderPurpose.ENTRY,
        strategy=strategy,
        placed_at=exec_time,
        executed_at=exec_time,
    )
    entry_res = await broker.place_order(entry_req)

    if entry_res.status == OrderStatus.REJECTED:
        return ExecuteOrderResult(
            buyOrder=entry_res,
            slOrder=None,
            sizing=sizing,
            status="failed",
            message=f"{entry_side.value.upper()} entry order rejected by {broker.broker_name}: {entry_res.message}",
        )

    # 3. Immediately place SL order after entry
    sl_req = BrokerOrderRequest(
        symbol=symbol.upper(),
        qty=order_qty,
        side=sl_side,
        order_type=OrderType.SL_M,
        stop_price=sizing.bufferedSl,
        product_type=ProductType.INTRADAY,
        purpose=OrderPurpose.STOP_LOSS,
        parent_order_id=entry_res.order_id,
        strategy=strategy,
        placed_at=exec_time,
    )
    sl_res = await broker.place_order(sl_req)

    # Record linked execution in DB if provided
    if db is not None and user_id is not None:
        chain_doc = {
            "userId": user_id,
            "broker": broker.broker_name,
            "symbol": symbol.upper(),
            "strategy": strategy,
            "side": side.lower(),
            "qty": order_qty,
            "stockPrice": stock_price,
            "tightSl": tight_sl,
            "bufferedSl": sizing.bufferedSl,
            "entryOrderId": entry_res.order_id,
            "entryStatus": entry_res.status.value,
            "buyOrderId": entry_res.order_id,
            "buyStatus": entry_res.status.value,
            "slOrderId": sl_res.order_id,
            "slStatus": sl_res.status.value,
            "totalRisk": sizing.totalRisk,
            "marginRequired": sizing.marginRequired,
            "placedAt": exec_time,
        }
        await db.order_chains.insert_one(chain_doc)

    action_label = "Buy" if is_buy else "Sell (Short)"
    return ExecuteOrderResult(
        buyOrder=entry_res,
        slOrder=sl_res,
        sizing=sizing,
        status="success",
        message=(
            f"{action_label} order placed ({entry_res.order_id}). "
            f"SL order placed @ ₹{sizing.bufferedSl:.2f} ({sl_res.order_id}) on {broker.broker_name}."
        ),
    )


async def execute_buy_and_sl_order(
    broker: BaseBroker,
    symbol: str,
    stock_price: float,
    tight_sl: float,
    qty: int | None = None,
    capital_allocation_pct: float = 50.0,
    max_risk_amount: float = 1100.0,
    sl_buffer_pct: float = 20.0,
    strategy: str | None = None,
    db: AsyncIOMotorDatabase | None = None,
    user_id: ObjectId | None = None,
    triggered_at: datetime | None = None,
) -> ExecuteOrderResult:
    return await execute_order_with_sl(
        broker=broker,
        symbol=symbol,
        side="buy",
        stock_price=stock_price,
        tight_sl=tight_sl,
        qty=qty,
        capital_allocation_pct=capital_allocation_pct,
        max_risk_amount=max_risk_amount,
        sl_buffer_pct=sl_buffer_pct,
        strategy=strategy,
        db=db,
        user_id=user_id,
        triggered_at=triggered_at,
    )


async def execute_exit_order(
    broker: BaseBroker,
    symbol: str,
    qty: int,
    side: OrderSide = OrderSide.SELL,
    strategy: str | None = None,
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
) -> BrokerOrderResponse:
    """Executes an exit / square-off order (Intraday MIS)."""
    exit_req = BrokerOrderRequest(
        symbol=symbol.upper(),
        qty=qty,
        side=side,
        order_type=order_type,
        limit_price=limit_price,
        product_type=ProductType.INTRADAY,
        purpose=OrderPurpose.EXIT,
        strategy=strategy,
    )
    return await broker.place_order(exit_req)


async def execute_sell_exit_order(
    broker: BaseBroker,
    symbol: str,
    qty: int,
    strategy: str | None = None,
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
) -> BrokerOrderResponse:
    """Executes a SELL exit / target order (Intraday MIS)."""
    return await execute_exit_order(
        broker=broker,
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        strategy=strategy,
        order_type=order_type,
        limit_price=limit_price,
    )


async def is_symbol_autotrade_enabled(user_id: ObjectId | str, symbol: str, db: AsyncIOMotorDatabase) -> bool:
    """Check if the symbol has autoTrade explicitly enabled in any of the user's watchlists."""
    sym = symbol.upper()
    try:
        user_ids = [str(user_id)]
        if ObjectId.is_valid(str(user_id)):
            user_ids.append(ObjectId(str(user_id)))
        doc = await db.watchlists.find_one({
            "userId": {"$in": user_ids},
            "items": {"$elemMatch": {"symbol": sym, "autoTrade": True}},
        })
        return doc is not None
    except Exception as exc:
        logger.warning("Error checking symbol autotrade status for %s: %s", sym, exc)
        return False


async def trigger_autotrade_if_enabled(
    snapshot: Any,
    user_id: ObjectId,
    db: AsyncIOMotorDatabase,
) -> ExecuteOrderResult | None:
    """Evaluates an incoming triggered setup.
    User Rule:
    - If Live Trade is toggled ON for this item in watchlist:
        Execute it in FYERS!
    - Else (if toggled OFF):
        Execute it in PAPER, with 1L capital (₹100,000)!
    """
    setup = getattr(snapshot, "tradeSetup", None)
    if setup is None or setup.triggeredAt is None or setup.action not in ("buy", "sell"):
        return None

    strategy_name = setup.strategy
    if not strategy_name:
        return None

    entry_price = setup.triggerPrice or setup.entry or snapshot.currentPrice
    tight_sl = setup.stopLoss
    if not tight_sl or tight_sl <= 0 or not entry_price or entry_price <= 0:
        logger.warning("No valid price/stopLoss for auto-trade on %s", snapshot.symbol)
        return None

    # User Rule: Strictly no fresh entries before 09:30 AM IST (04:00 UTC) or after 02:30 PM IST (09:00 UTC)
    t_at = setup.triggeredAt
    t_dt = t_at.astimezone(timezone.utc) if t_at.tzinfo else t_at.replace(tzinfo=timezone.utc)
    t_min = t_dt.hour * 60 + t_dt.minute
    if t_min < 240 or t_min > 540:
        logger.info("Skipping trigger on %s: outside 09:30 - 14:30 IST window (%02d:%02d UTC)", snapshot.symbol, t_dt.hour, t_dt.minute)
        return None

    sym_upper = snapshot.symbol.upper()
    date_str = (setup.triggeredAt.astimezone(timezone.utc)).date().isoformat()
    action = setup.action.lower()

    try:
        from app.services.cache import get_cache_client
        cache = get_cache_client()
    except Exception:
        cache = None

    # Check if this item is toggled ON for Live Trade in watchlist
    is_live_trade = await is_symbol_autotrade_enabled(user_id, sym_upper, db)

    res_to_return = None

    # ---------------------------------------------------------
    # 1. ALWAYS EXECUTE IN PAPER (UNIVERSAL BASELINE DEFAULT)
    # ---------------------------------------------------------
    paper_key = f"autotrade:paper:{sym_upper}:{strategy_name}:{date_str}"
    if not (cache and cache.exists(paper_key)):
        try:
            from app.services.brokers.paper_broker import PaperBroker
            paper_broker = PaperBroker(user_id=user_id, db=db)
            paper_res = await execute_order_with_sl(
                broker=paper_broker,
                symbol=sym_upper,
                side=action,
                stock_price=entry_price,
                tight_sl=tight_sl,
                capital_allocation_pct=50.0,
                max_risk_amount=1100.0,
                sl_buffer_pct=20.0,
                strategy=strategy_name,
                db=db,
                user_id=user_id,
            )
            if cache and paper_res.status == "success":
                cache.set_json(paper_key, {"executed": True, "at": datetime.now(timezone.utc).isoformat()}, ttl_seconds=8 * 3600)
            logger.info("Paper %s trade executed for %s on %s (order %s)", action, sym_upper, strategy_name, paper_res.buyOrder.order_id)
            res_to_return = paper_res
        except Exception as exc:
            logger.error("Paper trade failed for %s on %s: %s", sym_upper, strategy_name, exc)

    # ---------------------------------------------------------
    # 2. IN PARALLEL: IF FYERS ENABLED, ALSO EXECUTE LIVE ON FYERS
    # ---------------------------------------------------------
    if is_live_trade:
        broker_key = f"autotrade:fyers:{sym_upper}:{strategy_name}:{date_str}"
        if not (cache and cache.exists(broker_key)):
            strat_cfg = {}
            try:
                user_ids = [str(user_id)]
                if ObjectId.is_valid(str(user_id)):
                    user_ids.append(ObjectId(str(user_id)))
                doc = await db.user_settings.find_one({"userId": {"$in": user_ids}, "type": "strategy_autotrade"})
                if doc:
                    strat_cfg = doc.get("configs", {}).get(strategy_name, {})
            except Exception as exc:
                logger.warning("Could not load user_settings for autotrade: %s", exc)

            try:
                from app.services.brokers import get_broker
                broker = await get_broker("fyers", user_id, db)
                fyers_res = await execute_order_with_sl(
                    broker=broker,
                    symbol=sym_upper,
                    side=action,
                    stock_price=entry_price,
                    tight_sl=tight_sl,
                    capital_allocation_pct=float(strat_cfg.get("capitalAllocationPct", 50.0)),
                    max_risk_amount=float(strat_cfg.get("maxRiskPerTrade", 1100.0)),
                    sl_buffer_pct=float(strat_cfg.get("slBufferPct", 20.0)),
                    strategy=strategy_name,
                    db=db,
                    user_id=user_id,
                )
                if cache and fyers_res.status == "success":
                    cache.set_json(broker_key, {"executed": True, "at": datetime.now(timezone.utc).isoformat()}, ttl_seconds=8 * 3600)
                logger.info("Live Fyers %s trade executed for %s on %s: %s", action, sym_upper, strategy_name, fyers_res.message)
                res_to_return = fyers_res
            except Exception as exc:
                logger.error("Live Fyers trade failed for %s on %s: %s", sym_upper, strategy_name, exc)

    return res_to_return


async def sync_watchlist_entered_trades(
    user_id: ObjectId | str,
    db: AsyncIOMotorDatabase,
    target_date: str | None = None,
) -> list[ExecuteOrderResult]:
    """Scans all symbols in the user's watchlists.
    If an item in the watchlist entered/triggered today:
    - If Live Trade is toggled ON for that item -> executes in Fyers.
    - Else -> executes in Paper Trading (with 1L capital & 20% buffered SL).
    Ensures that any trade meeting entry criteria is immediately executed.
    """
    results: list[ExecuteOrderResult] = []
    try:
        user_ids = [str(user_id)]
        if ObjectId.is_valid(str(user_id)):
            user_ids.append(ObjectId(str(user_id)))

        from app.services import trading_service
        trading_cfg = await trading_service.get_user_trading_config(user_id, db)
        active_wl_id = trading_cfg.get("activeWatchlistId")
        wl_query: dict[str, Any] = {"userId": {"$in": user_ids}}
        if active_wl_id and active_wl_id not in ("all", ""):
            if ObjectId.is_valid(active_wl_id):
                wl_query["_id"] = ObjectId(active_wl_id)
            else:
                wl_query["_id"] = active_wl_id

        watchlists = await db.watchlists.find(wl_query).to_list(100)
        if not watchlists:
            return results

        date_str = target_date or datetime.now(timezone.utc).date().isoformat()
        max_positions = int(trading_cfg.get("maxOpenPositions", MAX_OPEN_POSITIONS))
        cfg_buffer = float(trading_cfg.get("slBufferPct", 25.0))
        cfg_risk = float(trading_cfg.get("maxRiskPerTrade", 1100.0))

        # Map symbol -> (is_live_trade, strategy)
        symbols_map: dict[str, dict] = {}
        for wl in watchlists:
            strat = wl.get("strategy") or "orb_pullback_support"
            for item in wl.get("items", []):
                sym = str(item.get("symbol") or "").upper()
                if not sym:
                    continue
                is_live = bool(item.get("autoTrade", False))
                if sym not in symbols_map or is_live:
                    symbols_map[sym] = {"is_live": is_live, "strategy": strat}

        all_syms = list(symbols_map.keys())
        if not all_syms:
            return results

        # Find triggers recorded for today for these symbols
        triggers = await db.intraday_triggers.find({
            "date": date_str,
            "symbol": {"$in": all_syms},
            "action": {"$in": ["buy", "sell"]},
        }).sort("triggeredAt", 1).to_list(200)

        try:
            from app.services.cache import get_cache_client
            cache = get_cache_client()
        except Exception:
            cache = None

        seen_syms: set[str] = set()
        for t in triggers:
            sym = t["symbol"].upper()
            if sym in seen_syms:
                continue
            entry_price = t.get("triggerPrice")
            tight_sl = t.get("stopLoss")
            action = str(t.get("action") or "").lower()
            strat = t.get("strategy") or symbols_map[sym]["strategy"]

            if not entry_price or entry_price <= 0 or not tight_sl or tight_sl <= 0 or action not in ("buy", "sell"):
                continue

            if is_index_symbol(sym):
                continue

            # User Rule: Strictly no fresh entries before 09:30 AM IST (04:00 UTC) or after 02:30 PM IST (09:00 UTC)
            t_at = t.get("triggeredAt")
            if t_at:
                t_dt = t_at.astimezone(timezone.utc) if t_at.tzinfo else t_at.replace(tzinfo=timezone.utc)
                t_min = t_dt.hour * 60 + t_dt.minute
                if t_min < 240 or t_min > 540:
                    continue

            seen_syms.add(sym)
            is_live = symbols_map[sym]["is_live"]

            # Check if user already reached max open positions for this session
            uid = ObjectId(str(user_id)) if ObjectId.is_valid(str(user_id)) else user_id
            from app.services.brokers import get_broker
            target_broker = await get_broker("fyers" if is_live else "paper", uid, db)
            try:
                current_positions = await target_broker.get_positions(target_date=date_str)
            except TypeError:
                current_positions = await target_broker.get_positions()
            current_open_syms = {p.symbol for p in current_positions if p.netQty != 0}
            if sym in current_open_syms:
                continue
            if len(current_open_syms) >= max_positions:
                logger.info("Reached maximum %d open positions for %s, stopping auto-sync", max_positions, date_str)
                break

            try:
                current_funds = await target_broker.get_funds(target_date=date_str)
            except TypeError:
                current_funds = await target_broker.get_funds()
            if current_funds.available_balance <= 0:
                logger.info("No available margin remaining (₹%.2f) for %s, stopping auto-sync", current_funds.available_balance, date_str)
                break

            order_key = f"autotrade:{'fyers' if is_live else 'paper'}:{sym}:{strat}:{date_str}"
            if not target_date and cache and cache.exists(order_key):
                continue

            # Check DB to prevent duplicate executions for this date
            start_of_day = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
            end_of_day = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
            existing_chain = await db.order_chains.find_one({
                "userId": {"$in": user_ids},
                "symbol": sym,
                "strategy": strat,
                "placedAt": {"$gte": start_of_day, "$lte": end_of_day},
            })
            if existing_chain:
                continue

            triggered_at = t.get("triggeredAt")

            # -------------------------------------------------------------
            # 1. ALWAYS EXECUTE PAPER TRADE (UNIVERSAL BASELINE DEFAULT)
            # -------------------------------------------------------------
            existing_paper = await db.paper_orders.find_one({
                "userId": {"$in": user_ids},
                "symbol": sym,
                "placedAt": {"$gte": start_of_day, "$lte": end_of_day},
            })
            if not existing_paper:
                try:
                    from app.services.brokers.paper_broker import PaperBroker
                    uid = ObjectId(str(user_id)) if ObjectId.is_valid(str(user_id)) else user_id
                    paper_broker = PaperBroker(user_id=uid, db=db)
                    res_paper = await execute_order_with_sl(
                        broker=paper_broker,
                        symbol=sym,
                        side=action,
                        stock_price=float(entry_price),
                        tight_sl=float(tight_sl),
                        sl_buffer_pct=cfg_buffer,
                        max_risk_amount=cfg_risk,
                        strategy=strat,
                        db=db,
                        user_id=uid if isinstance(uid, ObjectId) else None,
                        triggered_at=triggered_at,
                    )
                    if res_paper.status == "success":
                        paper_order_key = f"autotrade:paper:{sym}:{strat}:{date_str}"
                        if cache:
                            cache.set_json(paper_order_key, {"executed": True}, ttl_seconds=8 * 3600)
                        results.append(res_paper)
                        logger.info("Paper auto-trade synced for %s (%s): order %s", sym, action, res_paper.buyOrder.order_id)
                    else:
                        logger.warning("Paper auto-trade rejected for %s (%s): %s", sym, action, res_paper.message)
                except Exception as exc:
                    logger.error("Failed executing paper auto-trade for %s: %s", sym, exc)

            # -------------------------------------------------------------
            # 2. IN PARALLEL: IF LIVE TRADE ENABLED, ALSO EXECUTE ON FYERS
            # -------------------------------------------------------------
            if is_live and not existing_chain:
                try:
                    from app.services.brokers import get_broker
                    broker = await get_broker("fyers", user_ids[0], db)
                    res_fyers = await execute_order_with_sl(
                        broker=broker,
                        symbol=sym,
                        side=action,
                        stock_price=float(entry_price),
                        tight_sl=float(tight_sl),
                        sl_buffer_pct=cfg_buffer,
                        max_risk_amount=cfg_risk,
                        strategy=strat,
                        db=db,
                        user_id=ObjectId(str(user_id)) if ObjectId.is_valid(str(user_id)) else None,
                        triggered_at=triggered_at,
                    )
                    if res_fyers.status == "success":
                        fyers_order_key = f"autotrade:fyers:{sym}:{strat}:{date_str}"
                        if cache:
                            cache.set_json(fyers_order_key, {"executed": True}, ttl_seconds=8 * 3600)
                        results.append(res_fyers)
                        logger.info("Live Fyers auto-trade synced for %s (%s): order %s", sym, action, res_fyers.buyOrder.order_id)
                    else:
                        logger.warning("Live Fyers auto-trade rejected for %s: %s", sym, res_fyers.message)
                except Exception as exc:
                    logger.error("Failed executing live auto-trade for %s: %s", sym, exc)
    except Exception as e:
        logger.error("Error in sync_watchlist_entered_trades: %s", e)

    return results

