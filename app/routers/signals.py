"""
StockQueen V1 - Signals API Router
API endpoints for signal management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List

from app.models import Signal, SignalSummary, APIResponse, SignalConfirm
from app.services.db_service import SignalService
from app.services.notification_service import notify_signals_ready

router = APIRouter()
signal_service = SignalService()


@router.get("/observe", response_model=List[Signal])
async def get_observe_signals():
    """Get all observe signals for human confirmation"""
    signals = await signal_service.get_observe_signals()
    return signals


@router.get("/confirmed", response_model=List[Signal])
async def get_confirmed_signals():
    """Get all confirmed signals"""
    signals = await signal_service.get_confirmed_signals()
    return signals


@router.post("/confirm", response_model=APIResponse)
async def confirm_signal(confirm: SignalConfirm):
    """Human confirmation of signal"""
    success = await signal_service.confirm_signal(
        signal_id=confirm.signal_id,
        confirmed=confirm.confirmed,
        notes=confirm.notes
    )
    
    if success:
        return APIResponse(
            success=True,
            message=f"Signal {confirm.signal_id} {'confirmed' if confirm.confirmed else 'skipped'}"
        )
    else:
        raise HTTPException(status_code=500, detail="Failed to confirm signal")


@router.get("/summary", response_model=SignalSummary)
async def get_signal_summary():
    """Get daily signal summary"""
    observe = await signal_service.get_observe_signals()
    confirmed = await signal_service.get_confirmed_signals()
    
    return SignalSummary(
        date="2025-02-25",  # TODO: Use actual date
        total_observe=len(observe),
        total_confirmed=len(confirmed),
        total_trade=0,  # TODO: Query trade signals
        signals=observe
    )


@router.post("/notify", response_model=APIResponse)
async def send_signal_notification(background_tasks: BackgroundTasks):
    """Send signal notification via OpenClaw"""
    signals = await signal_service.get_observe_signals()
    
    background_tasks.add_task(notify_signals_ready, signals)
    
    return APIResponse(
        success=True,
        message=f"Notification queued for {len(signals)} signals"
    )
