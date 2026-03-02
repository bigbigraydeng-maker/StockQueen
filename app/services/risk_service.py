"""
StockQueen V1 - Risk Management Service
Hardcoded risk management rules
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.config import RiskConfig
from app.models import RiskState, Signal, Order
from app.services.db_service import RiskService as RiskDBService

logger = logging.getLogger(__name__)


class RiskEngine:
    """Risk management engine with hardcoded rules"""
    
    def __init__(self):
        self.db_service = RiskDBService()
        self.config = RiskConfig()
    
    async def check_all_risk_limits(self) -> Dict[str, Any]:
        """
        Check all risk limits
        Returns risk check result with pass/fail status
        """
        risk_state = await self.db_service.get_risk_state()
        
        if not risk_state:
            logger.error("Could not retrieve risk state")
            return {"pass": False, "reason": "risk_state_unavailable"}
        
        checks = {
            "max_positions": self._check_max_positions(risk_state),
            "max_drawdown": self._check_max_drawdown(risk_state),
            "consecutive_losses": self._check_consecutive_losses(risk_state),
            "system_status": self._check_system_status(risk_state)
        }
        
        all_passed = all(checks.values())
        
        if not all_passed:
            failed_checks = [k for k, v in checks.items() if not v]
            logger.warning(f"Risk checks failed: {failed_checks}")
            return {
                "pass": False,
                "reason": f"risk_limits_exceeded: {failed_checks}",
                "failed_checks": failed_checks,
                "risk_state": risk_state
            }
        
        return {
            "pass": True,
            "risk_state": risk_state
        }
    
    def _check_max_positions(self, risk_state: RiskState) -> bool:
        """Check if under max positions limit"""
        return risk_state.current_positions < self.config.MAX_POSITIONS
    
    def _check_max_drawdown(self, risk_state: RiskState) -> bool:
        """Check if under max drawdown limit"""
        return risk_state.max_drawdown_pct < self.config.MAX_DRAWDOWN
    
    def _check_consecutive_losses(self, risk_state: RiskState) -> bool:
        """Check if under consecutive loss limit"""
        return risk_state.consecutive_losses < self.config.CONSECUTIVE_LOSS_LIMIT
    
    def _check_system_status(self, risk_state: RiskState) -> bool:
        """Check if system is not paused"""
        return risk_state.status != "paused"
    
    async def calculate_position_size(
        self,
        account_equity: float,
        entry_price: float,
        stop_loss: float
    ) -> int:
        """
        Calculate position size based on risk per trade
        Risk per trade = 10% of account equity
        Position size = Risk Amount / (Entry - Stop Loss)
        """
        risk_amount = account_equity * self.config.RISK_PER_TRADE
        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share <= 0:
            logger.warning("Invalid risk per share, defaulting to 0")
            return 0
        
        position_size = int(risk_amount / risk_per_share)
        
        logger.info(
            f"Position size calculation: "
            f"equity=${account_equity:.2f}, "
            f"risk_amount=${risk_amount:.2f}, "
            f"position_size={position_size} shares"
        )
        
        return position_size
    
    async def update_after_trade(self, pnl: float, pnl_pct: float) -> None:
        """Update risk state after trade completion"""
        risk_state = await self.db_service.get_risk_state()
        
        if not risk_state:
            return
        
        updates = {}
        
        # Update consecutive losses
        if pnl < 0:
            updates["consecutive_losses"] = risk_state.consecutive_losses + 1
        else:
            updates["consecutive_losses"] = 0
        
        # Update last trade P&L
        updates["last_trade_pnl"] = pnl
        
        # Update drawdown
        if pnl < 0:
            # Simplified drawdown calculation
            current_dd = risk_state.max_drawdown_pct
            new_dd = current_dd + abs(pnl_pct)
            updates["max_drawdown_pct"] = min(new_dd, 1.0)  # Cap at 100%
        
        # Update position count
        updates["current_positions"] = max(0, risk_state.current_positions - 1)
        
        # Check if we need to pause
        if updates.get("consecutive_losses", 0) >= self.config.CONSECUTIVE_LOSS_LIMIT:
            updates["status"] = "paused"
            updates["paused_at"] = datetime.utcnow().isoformat()
            logger.warning("Risk limit reached: Pausing system")
        
        if updates.get("max_drawdown_pct", 0) >= self.config.MAX_DRAWDOWN:
            updates["status"] = "paused"
            updates["paused_at"] = datetime.utcnow().isoformat()
            logger.warning("Max drawdown reached: Pausing system")
        
        await self.db_service.update_risk_state(updates)
        logger.info(f"Risk state updated after trade: P&L=${pnl:.2f}")
    
    async def can_open_position(self) -> bool:
        """Check if new position can be opened"""
        result = await self.check_all_risk_limits()
        return result["pass"]
    
    async def get_current_risk_summary(self) -> Dict[str, Any]:
        """Get current risk summary for display"""
        risk_state = await self.db_service.get_risk_state()
        
        if not risk_state:
            return {"error": "Risk state unavailable"}
        
        return {
            "current_positions": risk_state.current_positions,
            "max_positions": self.config.MAX_POSITIONS,
            "position_utilization": f"{risk_state.current_positions}/{self.config.MAX_POSITIONS}",
            "max_drawdown_pct": f"{risk_state.max_drawdown_pct:.2%}",
            "drawdown_limit": f"{self.config.MAX_DRAWDOWN:.2%}",
            "consecutive_losses": risk_state.consecutive_losses,
            "loss_limit": self.config.CONSECUTIVE_LOSS_LIMIT,
            "status": risk_state.status,
            "can_trade": await self.can_open_position()
        }


# Convenience function
async def check_risk_before_trade() -> Dict[str, Any]:
    """Check risk before executing trade"""
    engine = RiskEngine()
    return await engine.check_all_risk_limits()
