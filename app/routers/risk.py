"""
StockQueen V1 - Risk API Router
API endpoints for risk management
"""

from fastapi import APIRouter, Depends, HTTPException

from app.models import APIResponse, RiskState
from app.services.risk_service import RiskEngine
from app.middleware.auth import require_api_key

router = APIRouter()
risk_engine = RiskEngine()


@router.get("/status")
async def get_risk_status():
    """Get current risk status summary"""
    summary = await risk_engine.get_current_risk_summary()
    return summary


@router.get("/check")
async def check_risk():
    """Check if trading is allowed"""
    result = await risk_engine.check_all_risk_limits()
    return result


@router.post("/reset", response_model=APIResponse)
async def reset_risk_state(_key: str = Depends(require_api_key)):
    """Reset risk state (admin only)"""
    from app.services.db_service import RiskService
    
    await RiskService.update_risk_state({
        "current_positions": 0,
        "max_drawdown_pct": 0.0,
        "consecutive_losses": 0,
        "status": "normal",
        "paused_at": None
    })
    
    return APIResponse(
        success=True,
        message="Risk state reset successfully"
    )
