"""
StockQueen V2.4 - Tiger Trade Service
Tiger Open API order execution via official SDK (tigeropen).
Paper trading (模拟盘) is determined by the TIGER_ACCOUNT (paper account ID).
"""

import asyncio
import logging
import math
import os
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.config import settings, RiskConfig
from app.database import get_db

logger = logging.getLogger(__name__)


class TigerTradeClient:
    """
    Tiger Open API trade client using official tigeropen SDK.
    Mirrors the initialization pattern from market_service.TigerAPIClient.
    """

    def __init__(self):
        self.tiger_id = settings.tiger_id
        self.account = settings.tiger_account
        self.private_key_str = settings.tiger_private_key
        self._trade_client = None
        self._pk_file = None
        self._init_failed = False
        self._last_fail_time = 0  # Allow retry after cooldown

    # ------------------------------------------------------------------
    # SDK initialisation (synchronous — call inside executor)
    # ------------------------------------------------------------------

    def _get_trade_client(self):
        """Lazy-init TradeClient (sync, run in executor)."""
        import time as _time
        if self._trade_client is not None:
            return self._trade_client
        # Allow retry every 60s after failure
        if self._init_failed:
            if _time.time() - self._last_fail_time < 60:
                return None
            self._init_failed = False
            logger.info("[TIGER-TRADE] Retrying initialization...")

        if not self.tiger_id or not self.private_key_str or not self.account:
            logger.warning("[TIGER-TRADE] credentials not configured, skipping")
            self._init_failed = True
            return None

        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.common.util.signature_utils import read_private_key
            from tigeropen.common.consts import Language
            from tigeropen.trade.trade_client import TradeClient

            # Write private key to temp file (SDK reads from file path)
            self._pk_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False
            )
            self._pk_file.write(self.private_key_str)
            self._pk_file.close()

            client_config = TigerOpenClientConfig()
            client_config.private_key = read_private_key(self._pk_file.name)
            client_config.tiger_id = self.tiger_id
            client_config.account = self.account
            client_config.language = Language.en_US

            self._trade_client = TradeClient(client_config)
            logger.info(f"[TIGER-TRADE] TradeClient initialized (account={self.account})")
            return self._trade_client

        except Exception as e:
            logger.error(f"[TIGER-TRADE] Failed to initialize TradeClient: {e}")
            self._init_failed = True
            self._last_fail_time = _time.time()
            return None

    async def _run_sync(self, fn, *args, **kwargs):
        """Run a synchronous SDK call in the default executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def _sync_get_assets(self) -> Optional[dict]:
        client = self._get_trade_client()
        if not client:
            return None
        try:
            assets = client.get_assets(account=self.account)
            if not assets:
                return None
            a = assets[0] if isinstance(assets, list) else assets

            # Tiger SDK PortfolioAccount: data lives in 'summary' and 'segments'
            summary = getattr(a, "summary", None) or {}
            segments = getattr(a, "segments", None) or {}
            # Securities segment has available_funds, cash, buying_power
            sec_seg = segments.get("S", {}) if isinstance(segments, dict) else {}

            nlv = float(summary.get("net_liquidation", 0) or 0) if isinstance(summary, dict) else float(getattr(summary, "net_liquidation", 0) or 0)
            unrealized = float(summary.get("unrealized_pnl", 0) or 0) if isinstance(summary, dict) else float(getattr(summary, "unrealized_pnl", 0) or 0)

            # Try segments first, fallback to summary
            if isinstance(sec_seg, dict):
                avail = float(sec_seg.get("available_funds", 0) or 0)
                cash = float(sec_seg.get("cash", 0) or 0)
                buying_power = float(sec_seg.get("buying_power", 0) or sec_seg.get("excess_liquidity", 0) or 0)
            else:
                avail = float(getattr(sec_seg, "available_funds", 0) or 0)
                cash = float(getattr(sec_seg, "cash", 0) or 0)
                buying_power = float(getattr(sec_seg, "buying_power", 0) or getattr(sec_seg, "excess_liquidity", 0) or 0)

            result = {
                "net_liquidation": nlv,
                "available_funds": avail,
                "buying_power": buying_power,
                "cash": cash,
                "unrealized_pnl": unrealized,
                "currency": "USD",
            }
            logger.info(f"[TIGER-TRADE] assets: NLV=${nlv:,.0f} avail=${avail:,.0f} cash=${cash:,.0f} upnl=${unrealized:,.0f}")
            return result
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_assets error: {e}", exc_info=True)
            return None

    async def get_account_assets(self) -> Optional[dict]:
        return await self._run_sync(self._sync_get_assets)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def _sync_get_positions(self) -> List[dict]:
        client = self._get_trade_client()
        if not client:
            return []
        try:
            positions = client.get_positions()
            result = []
            for p in positions:
                qty = int(getattr(p, "quantity", 0) or 0)
                mkt_val = float(getattr(p, "market_value", 0) or 0)
                avg_cost = float(getattr(p, "average_cost", 0) or 0)
                # Try to get latest_price directly from Position object
                latest = float(getattr(p, "latest_price", 0) or 0)
                if latest <= 0 and qty > 0 and mkt_val > 0:
                    latest = mkt_val / qty
                result.append({
                    "ticker": getattr(p, "contract", {}).symbol if hasattr(getattr(p, "contract", None), "symbol") else str(p),
                    "quantity": qty,
                    "average_cost": avg_cost,
                    "market_value": mkt_val,
                    "latest_price": latest,
                    "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0) or 0),
                })
            return result
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_positions error: {e}")
            return []

    async def get_positions(self) -> List[dict]:
        return await self._run_sync(self._sync_get_positions)

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def _sync_place_order(
        self, ticker: str, action: str, quantity: int,
        order_type: str = "MKT", limit_price: float = None,
        stop_loss: float = None, take_profit: float = None,
    ) -> Optional[dict]:
        """
        Place an order synchronously.
        action: 'BUY' or 'SELL'
        order_type: 'MKT' (market, default) or 'LMT' (limit)
        stop_loss / take_profit: optional bracket legs (only used if explicitly passed)
        """
        client = self._get_trade_client()
        if not client:
            return None
        try:
            from tigeropen.common.util.contract_utils import stock_contract
            from tigeropen.common.util.order_utils import order_leg

            contract = stock_contract(symbol=ticker, currency="USD")

            # Build optional bracket legs (only when explicitly requested)
            legs = []
            if stop_loss is not None and stop_loss > 0:
                legs.append(order_leg("LOSS", stop_loss, time_in_force="GTC"))
            if take_profit is not None and take_profit > 0:
                legs.append(order_leg("PROFIT", take_profit, time_in_force="GTC"))

            if order_type == "MKT":
                order = client.create_order(
                    self.account, contract, action, "MKT", quantity,
                    order_legs=legs if legs else None,
                )
            else:
                if limit_price is None:
                    logger.error(f"[TIGER-TRADE] limit_price required for LMT order")
                    return None
                order = client.create_order(
                    self.account, contract, action, "LMT", quantity,
                    limit_price=limit_price,
                    order_legs=legs if legs else None,
                )

            client.place_order(order)

            bracket_info = ""
            if legs:
                parts = []
                if stop_loss:
                    parts.append(f"SL=${stop_loss:.2f}")
                if take_profit:
                    parts.append(f"TP=${take_profit:.2f}")
                bracket_info = f" [{' / '.join(parts)}]"

            logger.info(
                f"[TIGER-TRADE] Order placed: {action} {quantity}x {ticker} "
                f"@ {'MKT' if order_type == 'MKT' else f'${limit_price}'}"
                f"{bracket_info} | order_id={order.order_id}"
            )
            return {
                "order_id": order.order_id,
                "id": order.id,
                "status": str(getattr(order, "status", "NEW")),
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "limit_price": limit_price,
            }
        except Exception as e:
            logger.error(f"[TIGER-TRADE] place_order error ({action} {ticker}): {e}")
            return None

    async def place_buy_order(
        self, ticker: str, quantity: int, limit_price: float = None,
        stop_loss: float = None, take_profit: float = None,
        order_type: str = "MKT",
    ) -> Optional[dict]:
        """Place a BUY order. Default MKT (market) for immediate fill.
        No bracket legs — trailing stop is managed by intraday monitor."""
        return await self._run_sync(
            self._sync_place_order, ticker, "BUY", quantity, order_type, limit_price,
        )

    async def place_sell_order(
        self, ticker: str, quantity: int, limit_price: float = None
    ) -> Optional[dict]:
        """Place a SELL order. Market order if limit_price is None."""
        if limit_price is not None:
            return await self._run_sync(
                self._sync_place_order, ticker, "SELL", quantity, "LMT", limit_price
            )
        return await self._run_sync(
            self._sync_place_order, ticker, "SELL", quantity, "MKT"
        )

    # ------------------------------------------------------------------
    # Order query / cancel
    # ------------------------------------------------------------------

    def _sync_get_order(self, order_id: int) -> Optional[dict]:
        client = self._get_trade_client()
        if not client:
            return None
        try:
            order = client.get_order(id=order_id)
            return {
                "order_id": order.order_id,
                "id": order.id,
                "status": str(getattr(order, "status", "")),
                "filled_quantity": int(getattr(order, "filled", 0) or 0),
                "avg_fill_price": float(getattr(order, "avg_fill_price", 0) or 0),
                "remaining": int(getattr(order, "remaining", 0) or 0),
            }
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_order error: {e}")
            return None

    async def get_order_status(self, order_id: int) -> Optional[dict]:
        return await self._run_sync(self._sync_get_order, order_id)

    def _sync_cancel_order(self, order_id: int) -> bool:
        client = self._get_trade_client()
        if not client:
            return False
        try:
            client.cancel_order(id=order_id)
            logger.info(f"[TIGER-TRADE] Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"[TIGER-TRADE] cancel_order error: {e}")
            return False

    async def cancel_order(self, order_id: int) -> bool:
        return await self._run_sync(self._sync_cancel_order, order_id)

    # ------------------------------------------------------------------
    # Open orders
    # ------------------------------------------------------------------

    def _sync_get_open_orders(self) -> List[dict]:
        client = self._get_trade_client()
        if not client:
            return []
        try:
            orders = client.get_open_orders(self.account)
            logger.info(f"[TIGER-TRADE] get_open_orders returned {len(orders) if orders else 0} orders")
            result = []
            for o in orders:
                action_raw = getattr(o, "action", "")
                action_str = str(action_raw).upper()
                order_type = str(getattr(o, "order_type", ""))
                limit_price = float(getattr(o, "limit_price", 0) or 0)
                aux_price = float(getattr(o, "aux_price", 0) or 0)
                quantity = int(getattr(o, "quantity", 0) or 0)
                filled = int(getattr(o, "filled", 0) or 0)
                ticker = getattr(getattr(o, "contract", None), "symbol", "")
                status = str(getattr(o, "status", ""))
                parent_id = getattr(o, "parent_id", None)

                logger.info(
                    f"[TIGER-TRADE] open order: {ticker} {action_str} {quantity}x "
                    f"type={order_type} limit={limit_price} aux={aux_price} "
                    f"filled={filled} status={status} parent_id={parent_id}"
                )
                result.append({
                    "order_id": o.order_id,
                    "id": o.id,
                    "status": status,
                    "ticker": ticker,
                    "action": action_str,
                    "order_type": order_type,
                    "quantity": quantity,
                    "filled": filled,
                    "limit_price": limit_price,
                    "aux_price": aux_price,
                    "parent_id": parent_id,
                })
            return result
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_open_orders error: {e}", exc_info=True)
            return []

    async def get_open_orders(self) -> List[dict]:
        return await self._run_sync(self._sync_get_open_orders)


# ==================================================================
# Position sizing
# ==================================================================

async def calculate_position_size(
    tiger_client: TigerTradeClient,
    entry_price: float,
    max_positions: int = 8,
    fallback_equity: float = 100_000.0,
) -> int:
    """
    Calculate number of shares for a new position.
    Equal-weight: account_equity / max_positions / entry_price
    """
    equity = fallback_equity
    try:
        assets = await tiger_client.get_account_assets()
        if assets and assets.get("net_liquidation", 0) > 0:
            equity = assets["net_liquidation"]
            logger.info(f"[TIGER-TRADE] Account equity: ${equity:,.0f}")
    except Exception as e:
        logger.warning(f"[TIGER-TRADE] Could not fetch equity, using fallback ${fallback_equity:,.0f}: {e}")

    allocation = equity / max_positions
    # Cap single position at 50% of total equity
    max_single = equity * 0.5
    allocation = min(allocation, max_single)

    if entry_price <= 0:
        return 0

    shares = math.floor(allocation / entry_price)
    return max(shares, 0)


def calc_recommended_qty(
    entry_price: float,
    equity: float = 100_000.0,
    max_positions: int = 3,
) -> int:
    """
    纯计算函数：推荐买入股数（不依赖 Tiger SDK）。
    等权分配，单仓位不超过总权益 50%。
    """
    if entry_price <= 0 or equity <= 0:
        return 0
    allocation = equity / max_positions
    allocation = min(allocation, equity * 0.5)
    return max(math.floor(allocation / entry_price), 0)


# ==================================================================
# Order sync (called by scheduler)
# ==================================================================

async def sync_tiger_orders():
    """
    Sync order status from Tiger API — Tiger is the source of truth.
    1. For orders with tiger_order_id: sync fill price/qty from Tiger
    2. Cross-reference Tiger positions vs DB: detect manual fills, orphaned positions
    3. Update DB entry_price to actual fill price (not signal price)
    """
    db = get_db()
    client = get_tiger_trade_client()
    synced = 0
    errors = 0

    # === Part 1: Sync order status for positions with tiger_order_id ===
    try:
        result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_id, tiger_order_status, status, entry_price, stop_loss, take_profit, atr14")
            .not_.is_("tiger_order_id", "null")
            .in_("status", ["active", "pending_entry"])
            .execute()
        )
        positions = result.data if result.data else []
    except Exception as e:
        logger.error(f"[TIGER-SYNC] DB query error: {e}")
        return {"synced": 0, "errors": 1}

    for pos in positions:
        tiger_id = pos.get("tiger_order_id")
        if not tiger_id:
            continue
        try:
            order_info = await client.get_order_status(int(tiger_id))
            if not order_info:
                continue

            status_str = order_info.get("status", "").upper()
            update = {}

            if "FILLED" in status_str:
                filled_price = order_info.get("avg_fill_price", 0)
                filled_qty = order_info.get("filled_quantity", 0)
                update["tiger_order_status"] = "filled"

                # Tiger fill price is the source of truth
                if filled_price > 0:
                    update["entry_price"] = round(filled_price, 4)
                    update["current_price"] = round(filled_price, 4)

                    # Recalculate SL/TP based on actual fill price (not signal price)
                    atr14 = float(pos.get("atr14", 0) or 0)
                    if atr14 > 0:
                        from app.config.rotation_watchlist import RotationConfig as RC
                        update["stop_loss"] = round(filled_price - RC.ATR_STOP_MULTIPLIER * atr14, 2)
                        update["take_profit"] = round(filled_price + RC.ATR_TARGET_MULTIPLIER * atr14, 2)

                if filled_qty > 0:
                    update["quantity"] = filled_qty

                logger.info(
                    f"[TIGER-SYNC] {pos['ticker']} FILLED @ ${filled_price:.2f} x{filled_qty} "
                    f"(signal was ${pos.get('entry_price', 0)})"
                )

            elif "CANCEL" in status_str:
                update["tiger_order_status"] = "cancelled"
            elif "PENDING" in status_str or "NEW" in status_str:
                update["tiger_order_status"] = "submitted"

            if update:
                db.table("rotation_positions").update(update).eq("id", pos["id"]).execute()
                synced += 1

        except Exception as e:
            logger.error(f"[TIGER-SYNC] Error for {pos['ticker']}: {e}")
            errors += 1

    # === Part 1.5: Sync exit orders (pending_exit → closed with actual fill price) ===
    try:
        exit_result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_exit_order_id, exit_price, entry_price")
            .eq("status", "pending_exit")
            .not_.is_("tiger_exit_order_id", "null")
            .execute()
        )
        for pos in (exit_result.data or []):
            exit_order_id = pos.get("tiger_exit_order_id")
            if not exit_order_id:
                continue
            try:
                order_info = await client.get_order_status(int(exit_order_id))
                if not order_info:
                    continue
                status_str = order_info.get("status", "").upper()
                if "FILLED" in status_str:
                    actual_exit_price = order_info.get("avg_fill_price", 0)
                    update = {"status": "closed"}
                    if actual_exit_price > 0:
                        update["exit_price"] = round(actual_exit_price, 4)
                    db.table("rotation_positions").update(update).eq("id", pos["id"]).execute()
                    synced += 1
                    logger.info(
                        f"[TIGER-SYNC] {pos['ticker']} EXIT FILLED @ ${actual_exit_price:.2f}"
                    )
                elif "CANCEL" in status_str:
                    # Sell order cancelled — revert to active
                    db.table("rotation_positions").update({
                        "status": "active",
                        "tiger_exit_order_id": None,
                        "exit_reason": None,
                        "exit_date": None,
                        "exit_price": None,
                    }).eq("id", pos["id"]).execute()
                    synced += 1
                    logger.warning(
                        f"[TIGER-SYNC] {pos['ticker']} exit order cancelled, reverting to active"
                    )
            except Exception as e:
                logger.error(f"[TIGER-SYNC] Exit sync error for {pos['ticker']}: {e}")
                errors += 1
    except Exception as e:
        logger.error(f"[TIGER-SYNC] Exit orders query error: {e}")

    # === Part 2: Cross-reference Tiger holdings with DB ===
    # Detect positions that Tiger holds but DB doesn't know about (manual trades)
    try:
        tiger_positions = await client.get_positions()
        tiger_tickers = {tp.get("ticker", "") for tp in tiger_positions if tp.get("quantity", 0) > 0}

        # Get all active DB tickers (exclude pending_exit — those are being sold)
        db_result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_status, entry_price, current_price")
            .eq("status", "active")
            .execute()
        )
        db_tickers = {p["ticker"] for p in (db_result.data or [])}

        # Tickers in Tiger but not in DB — log warning
        orphaned = tiger_tickers - db_tickers
        if orphaned:
            logger.warning(f"[TIGER-SYNC] Tiger holds tickers not in DB: {orphaned}")

        # Tickers in DB as 'filled' but not in Tiger — possibly sold outside the system.
        # NEVER auto-close: Tiger API can return empty/partial results due to network
        # issues, causing all positions to be incorrectly closed. Log only.
        filled_in_db = {
            p["ticker"]: p
            for p in (db_result.data or [])
            if p.get("tiger_order_status") == "filled"
        }
        sold_outside = set(filled_in_db.keys()) - tiger_tickers
        if sold_outside:
            logger.warning(
                f"[TIGER-SYNC] DB has filled positions not in Tiger: {sold_outside} "
                f"(Tiger returned {len(tiger_tickers)} tickers, DB has {len(filled_in_db)} filled). "
                f"Use manual close if these were truly sold."
            )

        # === Part 2.5: Force-sync by ticker — Tiger holdings are source of truth ===
        # Handles stale/wrong tiger_order_id (e.g. overwritten by failed rebalance)
        tiger_holdings_map = {tp.get("ticker", ""): tp for tp in tiger_positions if tp.get("quantity", 0) > 0}
        all_nonclosed = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_status, quantity, atr14")
            .neq("status", "closed")
            .execute()
        ).data or []

        seen_sync = set()
        for pos in all_nonclosed:
            ticker = pos.get("ticker", "")
            if ticker in seen_sync or ticker not in tiger_holdings_map:
                continue
            seen_sync.add(ticker)
            tp = tiger_holdings_map[ticker]
            tiger_qty = int(tp.get("quantity", 0))
            avg_cost = float(tp.get("average_cost", 0) or 0)

            update = {}
            if pos.get("tiger_order_status") != "filled":
                update["tiger_order_status"] = "filled"
            if tiger_qty > 0 and pos.get("quantity") != tiger_qty:
                update["quantity"] = tiger_qty
            # Update entry_price to actual avg_cost (Tiger is source of truth)
            if avg_cost > 0:
                update["entry_price"] = round(avg_cost, 4)
                atr14 = float(pos.get("atr14", 0) or 0)
                if atr14 > 0:
                    from app.config.rotation_watchlist import RotationConfig as RC
                    update["stop_loss"] = round(avg_cost - RC.ATR_STOP_MULTIPLIER * atr14, 2)
                    update["take_profit"] = round(avg_cost + RC.ATR_TARGET_MULTIPLIER * atr14, 2)

            if update:
                db.table("rotation_positions").update(update).eq("id", pos["id"]).execute()
                synced += 1
                logger.info(f"[TIGER-SYNC] Ticker-sync {ticker}: qty={tiger_qty} avg=${avg_cost:.2f} → {list(update.keys())}")

    except Exception as e:
        logger.warning(f"[TIGER-SYNC] Cross-reference check failed: {e}")

    logger.info(f"[TIGER-SYNC] Complete: {synced} synced, {errors} errors")
    return {"synced": synced, "errors": errors}


# ==================================================================
# Intraday Trailing Stop Monitor (every 5 min during market hours)
# ==================================================================

async def run_intraday_trailing_stop():
    """
    Real-time trailing stop check using Tiger live positions.
    Runs every 5 min during US market hours (NZT 02:30-09:00).

    Logic:
    1. Get active positions from DB (with SL/TP/ATR/highest_price)
    2. Get real-time prices from Tiger positions API
    3. Update highest_price, compute effective trailing SL
    4. If triggered → place MKT SELL order on Tiger immediately
    """
    from app.config.rotation_watchlist import RotationConfig as RC

    db = get_db()
    client = get_tiger_trade_client()

    # Get active positions with Tiger order filled
    try:
        result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, atr14, "
                    "highest_price, quantity, tiger_order_status")
            .eq("status", "active")
            .execute()
        )
        positions = result.data if result.data else []
    except Exception as e:
        logger.error(f"[TRAILING] DB query error: {e}")
        return {"checked": 0, "triggered": 0, "errors": 1}

    if not positions:
        return {"checked": 0, "triggered": 0, "errors": 0}

    # Only check positions that are actually filled in Tiger
    filled = [p for p in positions if p.get("tiger_order_status") == "filled"]
    if not filled:
        logger.info("[TRAILING] No filled positions to monitor")
        return {"checked": 0, "triggered": 0, "errors": 0}

    # Get real-time prices from Tiger
    try:
        tiger_positions = await client.get_positions()
        tiger_prices = {}
        for tp in tiger_positions:
            tk = tp.get("ticker", "")
            price = tp.get("latest_price", 0)
            if tk and price > 0:
                tiger_prices[tk] = price
    except Exception as e:
        logger.error(f"[TRAILING] Tiger positions fetch error: {e}")
        return {"checked": 0, "triggered": 0, "errors": 1}

    checked = 0
    triggered = 0
    errors = 0

    for pos in filled:
        ticker = pos.get("ticker", "")
        pos_id = pos.get("id")
        entry_price = float(pos.get("entry_price", 0) or 0)
        stop_loss = float(pos.get("stop_loss", 0) or 0)
        take_profit = float(pos.get("take_profit", 0) or 0)
        atr14 = float(pos.get("atr14", 0) or 0)
        highest_price = float(pos.get("highest_price", 0) or 0)
        quantity = int(pos.get("quantity", 0) or 0)

        if entry_price <= 0 or ticker not in tiger_prices:
            continue

        current_price = tiger_prices[ticker]
        checked += 1

        # Update highest price
        if highest_price <= 0:
            highest_price = max(current_price, entry_price)
        else:
            highest_price = max(highest_price, current_price)

        # Compute effective stop (static or trailing, whichever is higher)
        effective_sl = stop_loss
        if RC.TRAILING_STOP_ENABLED and atr14 > 0 and entry_price > 0:
            profit = highest_price - entry_price
            if profit >= RC.TRAILING_ACTIVATE_ATR * atr14:
                trailing_sl = highest_price - RC.TRAILING_STOP_ATR_MULT * atr14
                if trailing_sl > effective_sl:
                    effective_sl = trailing_sl

        # Update DB with latest price and highest_price
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0.0
        try:
            db.table("rotation_positions").update({
                "current_price": round(current_price, 4),
                "unrealized_pnl_pct": round(pnl_pct, 4),
                "highest_price": round(highest_price, 2),
            }).eq("id", pos_id).execute()
        except Exception as e:
            logger.error(f"[TRAILING] DB update error for {ticker}: {e}")

        exit_reason = None

        # Check stop loss (static or trailing)
        if effective_sl > 0 and current_price < effective_sl:
            is_trailing = effective_sl > stop_loss
            exit_reason = "trailing_stop" if is_trailing else "stop_loss"
            logger.warning(
                f"[TRAILING] {exit_reason.upper()} triggered: {ticker} "
                f"price=${current_price:.2f} < SL=${effective_sl:.2f} "
                f"(entry=${entry_price:.2f}, high=${highest_price:.2f})"
            )

        # Check take profit
        elif take_profit > 0 and current_price > take_profit:
            exit_reason = "take_profit"
            logger.info(
                f"[TRAILING] TAKE_PROFIT triggered: {ticker} "
                f"price=${current_price:.2f} > TP=${take_profit:.2f}"
            )

        if exit_reason and quantity > 0:
            # Place MKT SELL order on Tiger immediately
            try:
                sell_result = await client.place_sell_order(ticker, quantity)
                if sell_result:
                    sell_order_id = str(sell_result.get("id") or sell_result.get("order_id", ""))
                    db.table("rotation_positions").update({
                        "status": "pending_exit",
                        "exit_reason": exit_reason,
                        "exit_date": datetime.now().strftime("%Y-%m-%d"),
                        "exit_price": round(current_price, 2),  # preliminary; sync will update with actual fill
                        "tiger_exit_order_id": sell_order_id,
                    }).eq("id", pos_id).execute()
                    triggered += 1
                    logger.info(
                        f"[TRAILING] SELL {quantity}x {ticker} @ MKT "
                        f"reason={exit_reason} order_id={sell_order_id}"
                    )
                else:
                    logger.error(f"[TRAILING] SELL order failed for {ticker}")
                    errors += 1
            except Exception as e:
                logger.error(f"[TRAILING] SELL error for {ticker}: {e}")
                errors += 1

            # Send notification
            try:
                from app.services.notification_service import notify_rotation_exit
                from app.services.rotation_service import DailyTimingSignal
                signal = DailyTimingSignal(
                    ticker=ticker,
                    signal_type="exit",
                    trigger_conditions=[f"{exit_reason}: ${current_price:.2f} < SL ${effective_sl:.2f}"],
                    current_price=current_price,
                    entry_price=entry_price,
                    exit_reason=exit_reason,
                )
                await notify_rotation_exit(signal)
            except Exception:
                pass  # notification failure is non-critical

    logger.info(f"[TRAILING] Check complete: {checked} checked, {triggered} triggered, {errors} errors")
    return {"checked": checked, "triggered": triggered, "errors": errors}


# ==================================================================
# Unfilled Order Management
# ==================================================================

async def manage_unfilled_orders(max_wait_minutes: int = 30):
    """
    Check for submitted-but-unfilled orders older than max_wait_minutes.
    Cancel them and re-submit as MKT orders for immediate fill.
    """
    db = get_db()
    client = get_tiger_trade_client()

    try:
        result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_id, tiger_order_status, quantity, created_at, entry_date")
            .eq("tiger_order_status", "submitted")
            .in_("status", ["active", "pending_entry"])
            .execute()
        )
        positions = result.data if result.data else []
    except Exception as e:
        logger.error(f"[UNFILLED] DB query error: {e}")
        return {"cancelled": 0, "resubmitted": 0, "errors": 1}

    if not positions:
        return {"cancelled": 0, "resubmitted": 0, "errors": 0}

    cancelled = 0
    resubmitted = 0
    errors = 0

    for pos in positions:
        ticker = pos.get("ticker", "")
        tiger_id = pos.get("tiger_order_id")
        quantity = int(pos.get("quantity", 0) or 0)
        pos_id = pos.get("id")

        if not tiger_id or quantity <= 0:
            continue

        # Check order status from Tiger
        try:
            order_info = await client.get_order_status(int(tiger_id))
            if not order_info:
                continue

            status_str = order_info.get("status", "").upper()

            # Already filled — just update DB
            if "FILLED" in status_str:
                filled_price = order_info.get("avg_fill_price", 0)
                filled_qty = order_info.get("filled_quantity", 0)
                update = {"tiger_order_status": "filled"}
                if filled_price > 0:
                    update["entry_price"] = filled_price
                if filled_qty > 0:
                    update["quantity"] = filled_qty
                db.table("rotation_positions").update(update).eq("id", pos_id).execute()
                continue

            # Already cancelled
            if "CANCEL" in status_str:
                db.table("rotation_positions").update({
                    "tiger_order_status": "cancelled"
                }).eq("id", pos_id).execute()
                continue

            # Still pending — cancel and resubmit as MKT
            remaining = order_info.get("remaining", quantity)
            if remaining > 0:
                ok = await client.cancel_order(int(tiger_id))
                if ok:
                    cancelled += 1
                    logger.info(f"[UNFILLED] Cancelled pending order for {ticker} (id={tiger_id})")

                    # Resubmit as MKT
                    new_result = await client.place_buy_order(
                        ticker, remaining, order_type="MKT",
                    )
                    if new_result:
                        new_order_id = str(new_result.get("id") or new_result.get("order_id", ""))
                        db.table("rotation_positions").update({
                            "tiger_order_id": new_order_id,
                            "tiger_order_status": "submitted",
                        }).eq("id", pos_id).execute()
                        resubmitted += 1
                        logger.info(f"[UNFILLED] Resubmitted MKT order for {ticker} (new_id={new_order_id})")
                    else:
                        errors += 1
                        logger.error(f"[UNFILLED] MKT resubmit failed for {ticker}")
                else:
                    errors += 1

        except Exception as e:
            logger.error(f"[UNFILLED] Error processing {ticker}: {e}")
            errors += 1

    logger.info(f"[UNFILLED] Complete: {cancelled} cancelled, {resubmitted} resubmitted, {errors} errors")
    return {"cancelled": cancelled, "resubmitted": resubmitted, "errors": errors}


# ==================================================================
# Singleton
# ==================================================================

_tiger_trade_client: Optional[TigerTradeClient] = None


def get_tiger_trade_client() -> TigerTradeClient:
    """Get or create the singleton TigerTradeClient."""
    global _tiger_trade_client
    if _tiger_trade_client is None:
        _tiger_trade_client = TigerTradeClient()
    return _tiger_trade_client
