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
            assets = client.get_assets()
            if not assets:
                return None
            # assets is a list of PortfolioAccount objects
            a = assets[0] if isinstance(assets, list) else assets
            return {
                "net_liquidation": float(getattr(a, "net_liquidation", 0) or 0),
                "available_funds": float(getattr(a, "available_funds", 0) or 0),
                "buying_power": float(getattr(a, "buying_power", 0) or 0),
                "cash": float(getattr(a, "cash", 0) or 0),
                "currency": getattr(a, "currency", "USD"),
            }
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_assets error: {e}")
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
                result.append({
                    "ticker": getattr(p, "contract", {}).symbol if hasattr(getattr(p, "contract", None), "symbol") else str(p),
                    "quantity": int(getattr(p, "quantity", 0) or 0),
                    "average_cost": float(getattr(p, "average_cost", 0) or 0),
                    "market_value": float(getattr(p, "market_value", 0) or 0),
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
        order_type: str = "LMT", limit_price: float = None,
        stop_loss: float = None, take_profit: float = None,
    ) -> Optional[dict]:
        """
        Place an order synchronously.
        action: 'BUY' or 'SELL'
        order_type: 'LMT' (limit) or 'MKT' (market)
        stop_loss / take_profit: attach bracket order legs (GTC)
        """
        client = self._get_trade_client()
        if not client:
            return None
        try:
            from tigeropen.common.util.contract_utils import stock_contract
            from tigeropen.common.util.order_utils import order_leg

            contract = stock_contract(symbol=ticker, currency="USD")

            # Build order legs for bracket order
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
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }
        except Exception as e:
            logger.error(f"[TIGER-TRADE] place_order error ({action} {ticker}): {e}")
            return None

    async def place_buy_order(
        self, ticker: str, quantity: int, limit_price: float,
        stop_loss: float = None, take_profit: float = None,
    ) -> Optional[dict]:
        """Place a BUY limit order with optional bracket (stop-loss + take-profit)."""
        return await self._run_sync(
            self._sync_place_order, ticker, "BUY", quantity, "LMT", limit_price,
            stop_loss, take_profit,
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
            result = []
            for o in orders:
                result.append({
                    "order_id": o.order_id,
                    "id": o.id,
                    "status": str(getattr(o, "status", "")),
                    "ticker": getattr(getattr(o, "contract", None), "symbol", ""),
                    "action": getattr(o, "action", ""),
                    "quantity": int(getattr(o, "quantity", 0) or 0),
                    "filled": int(getattr(o, "filled", 0) or 0),
                    "limit_price": float(getattr(o, "limit_price", 0) or 0),
                })
            return result
        except Exception as e:
            logger.error(f"[TIGER-TRADE] get_open_orders error: {e}")
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


# ==================================================================
# Order sync (called by scheduler)
# ==================================================================

async def sync_tiger_orders():
    """
    Sync order status from Tiger API for all positions with
    a tiger_order_id but not yet filled.
    """
    db = get_db()
    try:
        # Get positions that have tiger_order_id and are not closed
        result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_id, status")
            .not_.is_("tiger_order_id", "null")
            .neq("status", "closed")
            .execute()
        )
        positions = result.data if result.data else []
    except Exception as e:
        logger.error(f"[TIGER-TRADE] sync: query error: {e}")
        return {"synced": 0, "errors": 1}

    if not positions:
        return {"synced": 0, "errors": 0}

    client = get_tiger_trade_client()
    synced = 0
    errors = 0

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
                if filled_price > 0:
                    update["entry_price"] = filled_price
                if filled_qty > 0:
                    update["quantity"] = filled_qty
                update["tiger_order_status"] = "filled"
            elif "CANCEL" in status_str:
                update["tiger_order_status"] = "cancelled"
            elif "PENDING" in status_str or "NEW" in status_str:
                update["tiger_order_status"] = "submitted"

            if update:
                db.table("rotation_positions").update(update).eq("id", pos["id"]).execute()
                synced += 1

        except Exception as e:
            logger.error(f"[TIGER-TRADE] sync error for {pos['ticker']}: {e}")
            errors += 1

    logger.info(f"[TIGER-TRADE] Order sync complete: {synced} synced, {errors} errors")
    return {"synced": synced, "errors": errors}


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
