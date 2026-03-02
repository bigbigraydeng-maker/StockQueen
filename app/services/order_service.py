"""
StockQueen V1 - Order Engine Service
Tiger Open API order execution
"""

import httpx
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.config import settings
from app.models import Signal, OrderCreate, Order
from app.services.db_service import SignalService, OrderService as OrderDBService
from app.services.risk_service import RiskEngine

logger = logging.getLogger(__name__)


class TigerOrderClient:
    """Tiger Open API client for order execution"""
    
    def __init__(self):
        self.access_token = settings.tiger_access_token
        self.tiger_id = settings.tiger_tiger_id
        self.account = settings.tiger_account
        self.base_url = settings.tiger_base_url
        self.timeout = 30.0
    
    async def place_order(
        self,
        ticker: str,
        side: str,  # "buy" or "sell"
        quantity: int,
        order_type: str = "limit",
        price: float = None,
        stop_price: float = None
    ) -> Optional[Dict[str, Any]]:
        """Place order via Tiger API"""
        # Note: This is a simplified implementation
        # Actual Tiger API requires specific SDK or endpoints
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "ticker": ticker,
            "account": self.account,
            "action": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "stop_price": stop_price
        }
        
        try:
            logger.info(f"Placing {side} order for {quantity} shares of {ticker}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Note: Replace with actual Tiger API endpoint
                response = await client.post(
                    f"{self.base_url}/v1/order",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                logger.info(f"Order placed successfully: {data.get('order_id')}")
                return data
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Tiger API HTTP error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order status from Tiger API"""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/v1/order/{order_id}",
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return None


class OrderEngine:
    """Order execution engine"""
    
    def __init__(self):
        self.client = TigerOrderClient()
        self.db_service = OrderDBService()
        self.signal_service = SignalService()
        self.risk_engine = RiskEngine()
    
    async def execute_trade_signals(self) -> Dict[str, Any]:
        """
        Execute all trade-ready signals
        Returns execution summary
        """
        results = {
            "total_trade_signals": 0,
            "orders_created": 0,
            "orders_submitted": 0,
            "errors": []
        }
        
        # Check risk limits first
        risk_check = await self.risk_engine.check_all_risk_limits()
        if not risk_check["pass"]:
            logger.warning(f"Risk check failed: {risk_check['reason']}")
            results["errors"].append(f"Risk check failed: {risk_check['reason']}")
            return results
        
        # Get trade-ready signals
        # In real implementation, query signals with status="trade"
        trade_signals = await self._get_trade_signals()
        results["total_trade_signals"] = len(trade_signals)
        
        logger.info(f"Executing {len(trade_signals)} trade signals")
        
        for signal in trade_signals:
            try:
                order_result = await self._execute_signal(signal, risk_check["risk_state"])
                
                if order_result["success"]:
                    results["orders_created"] += 1
                    if order_result.get("submitted"):
                        results["orders_submitted"] += 1
                else:
                    results["errors"].append(
                        f"Failed to execute {signal.ticker}: {order_result.get('error')}"
                    )
                    
            except Exception as e:
                logger.error(f"Error executing signal for {signal.ticker}: {e}")
                results["errors"].append(f"Error for {signal.ticker}: {str(e)}")
        
        return results
    
    async def _get_trade_signals(self) -> list:
        """Get signals ready for trading"""
        # Query database for signals with status="trade"
        # This is a placeholder
        return []
    
    async def _execute_signal(
        self,
        signal: Signal,
        risk_state
    ) -> Dict[str, Any]:
        """Execute a single trading signal"""
        
        # Calculate position size
        account_equity = risk_state.account_equity if risk_state else 10000.0
        position_size = await self.risk_engine.calculate_position_size(
            account_equity=account_equity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss
        )
        
        if position_size <= 0:
            return {"success": False, "error": "Invalid position size"}
        
        # Create order in database
        side = "buy" if signal.direction == "long" else "sell"
        
        order_create = OrderCreate(
            signal_id=signal.id,
            ticker=signal.ticker,
            direction=signal.direction,
            side=side,
            quantity=position_size,
            price=signal.entry_price,
            stop_price=signal.stop_loss
        )
        
        order = await self.db_service.create_order(order_create)
        
        if not order:
            return {"success": False, "error": "Failed to create order in database"}
        
        # Submit to Tiger API
        tiger_result = await self.client.place_order(
            ticker=signal.ticker,
            side=side,
            quantity=position_size,
            order_type="limit",
            price=signal.entry_price
        )
        
        if tiger_result:
            # Update order with Tiger ID
            await self.db_service.update_order_tiger_id(
                order.id,
                tiger_result.get("order_id")
            )
            
            # Update signal status
            await self.signal_service.update_signal_status(signal.id, "executed")
            
            return {"success": True, "submitted": True, "order_id": order.id}
        else:
            return {"success": True, "submitted": False, "order_id": order.id}
    
    async def update_order_status(self, order_id: str) -> bool:
        """Update order status from Tiger API"""
        # Get order from database
        # Query Tiger API for status
        # Update database
        return True


# Convenience function
async def execute_pending_trades() -> Dict[str, Any]:
    """Execute pending trade signals"""
    engine = OrderEngine()
    return await engine.execute_trade_signals()
