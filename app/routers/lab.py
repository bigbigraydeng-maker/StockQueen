"""
StockQueen V5 - Lab Dashboard Router
订单监控、回测分析、参数调优 API 端点
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
import pytz

from app.database import get_db
from app.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lab", tags=["lab"])


@router.get("/orders/recent")
async def get_recent_orders(
    limit: int = Query(10, ge=1, le=50),
):
    """
    获取最近 N 个订单（活跃状态）

    Args:
        limit: 最多返回订单数（1-50）

    Returns:
        {
            "orders": [
                {
                    "ticker": "VIAV",
                    "status": "active",
                    "tiger_order_id": "42897485771196416",
                    "tiger_order_status": "submitted",
                    "entry_price": 40.76,
                    "created_at": "2026-04-15T03:37:23Z"
                },
                ...
            ]
        }
    """
    try:
        db = get_db()
        result = db.table("rotation_positions").select(
            "ticker, status, tiger_order_id, tiger_order_status, entry_price, created_at"
        ).eq("status", "active").order("created_at", desc=True).limit(limit).execute()

        orders = []
        for row in result.data or []:
            orders.append({
                "ticker": row.get("ticker"),
                "status": row.get("status"),
                "tiger_order_id": row.get("tiger_order_id"),
                "tiger_order_status": row.get("tiger_order_status"),
                "entry_price": row.get("entry_price"),
                "created_at": row.get("created_at"),
            })

        return {"orders": orders}

    except Exception as e:
        logger.error(f"[LAB] Error fetching recent orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/retry-queue")
async def get_retry_queue(
    limit: int = Query(20, ge=1, le=100),
):
    """
    获取重试队列中的订单（待重试）

    Returns:
        {
            "retry_queue": [
                {
                    "id": "uuid",
                    "ticker": "AAPL",
                    "entry_price": 150.00,
                    "quantity": 100,
                    "stop_loss": 145.00,
                    "take_profit": 160.00,
                    "retry_count": 1,
                    "max_retries": 3,
                    "last_error": "Connection timeout",
                    "next_retry_at": "2026-04-15T03:40:00Z",
                    "created_at": "2026-04-15T03:37:00Z"
                },
                ...
            ]
        }
    """
    try:
        db = get_db()
        result = db.table("order_retry_queue").select(
            "id, ticker, entry_price, quantity, stop_loss, take_profit, "
            "retry_count, max_retries, last_error, next_retry_at, created_at"
        ).eq("status", "pending").order("next_retry_at", asc=True).limit(limit).execute()

        retry_queue = []
        for row in result.data or []:
            retry_queue.append({
                "id": row.get("id"),
                "ticker": row.get("ticker"),
                "entry_price": row.get("entry_price"),
                "quantity": row.get("quantity"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "retry_count": row.get("retry_count", 0),
                "max_retries": row.get("max_retries", 3),
                "last_error": row.get("last_error"),
                "next_retry_at": row.get("next_retry_at"),
                "created_at": row.get("created_at"),
            })

        return {"retry_queue": retry_queue}

    except Exception as e:
        logger.error(f"[LAB] Error fetching retry queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/failed")
async def get_failed_orders(
    limit: int = Query(10, ge=1, le=50),
):
    """
    获取最终失败订单（需人工处理）

    Returns:
        {
            "failed_orders": [
                {
                    "id": "uuid",
                    "ticker": "TSLA",
                    "entry_price": 250.00,
                    "quantity": 50,
                    "stop_loss": 240.00,
                    "take_profit": 270.00,
                    "max_retries": 3,
                    "last_error": "Insufficient funds",
                    "created_at": "2026-04-15T03:30:00Z",
                    "updated_at": "2026-04-15T03:37:30Z"
                },
                ...
            ]
        }
    """
    try:
        db = get_db()
        result = db.table("order_retry_queue").select(
            "id, ticker, entry_price, quantity, stop_loss, take_profit, "
            "max_retries, last_error, created_at, updated_at"
        ).eq("status", "failed_all").order("updated_at", desc=True).limit(limit).execute()

        failed_orders = []
        for row in result.data or []:
            failed_orders.append({
                "id": row.get("id"),
                "ticker": row.get("ticker"),
                "entry_price": row.get("entry_price"),
                "quantity": row.get("quantity"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "max_retries": row.get("max_retries", 3),
                "last_error": row.get("last_error"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            })

        return {"failed_orders": failed_orders}

    except Exception as e:
        logger.error(f"[LAB] Error fetching failed orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/summary")
async def get_dashboard_summary():
    """
    获取仪表板概览数据（订单统计、库存持仓等）

    Returns:
        {
            "stats": {
                "total_active_orders": 4,
                "total_in_retry_queue": 2,
                "total_failed_orders": 0,
                "success_rate": 95.5
            },
            "account": {
                "nlv": 1023897,
                "available_funds": 819321,
                "positions_count": 4,
                "leverage_usage": 59.2
            }
        }
    """
    try:
        db = get_db()

        # 订单统计
        active = db.table("rotation_positions").select("id").eq("status", "active").execute()
        active_count = len(active.data or [])

        retry_queue = db.table("order_retry_queue").select("id").eq("status", "pending").execute()
        retry_count = len(retry_queue.data or [])

        failed = db.table("order_retry_queue").select("id").eq("status", "failed_all").execute()
        failed_count = len(failed.data or [])

        total = active_count + retry_count + failed_count
        success_rate = (active_count / total * 100) if total > 0 else 0

        # 账户数据（从 Tiger API 获取）
        try:
            from app.services.order_service import TigerTradeClient
            tiger = TigerTradeClient(account_label="primary")
            account_info = tiger.get_account()

            account_data = {
                "nlv": account_info.get("nlv"),
                "available_funds": account_info.get("available_funds"),
                "positions_count": len(account_info.get("positions", [])),
                "leverage_usage": account_info.get("leverage_usage_pct", 0),
            }
        except Exception as e:
            logger.warning(f"[LAB] Failed to fetch account info: {e}")
            account_data = {
                "nlv": 0,
                "available_funds": 0,
                "positions_count": 0,
                "leverage_usage": 0,
            }

        return {
            "stats": {
                "total_active_orders": active_count,
                "total_in_retry_queue": retry_count,
                "total_failed_orders": failed_count,
                "success_rate": round(success_rate, 1),
            },
            "account": account_data,
        }

    except Exception as e:
        logger.error(f"[LAB] Error fetching dashboard summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
