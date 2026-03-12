"""
StockQueen V2 - Knowledge Base Router
API endpoints for RAG knowledge base: feed, search, manage.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query

from app.models import (
    APIResponse,
    KnowledgeFeedRequest,
    KnowledgeFeedURLRequest,
)
from app.services.knowledge_service import get_knowledge_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== USER FEED ENDPOINTS ====================

@router.post("/feed", response_model=APIResponse)
async def feed_text(request: KnowledgeFeedRequest):
    """
    投喂纯文本到知识库。
    可附带 category, tickers, tags 等元数据。
    """
    ks = get_knowledge_service()

    entry = await ks.add_knowledge(
        content=request.content,
        source_type="user_feed_text",
        category=request.category,
        tickers=request.tickers,
        tags=request.tags,
    )

    if entry:
        return APIResponse(
            success=True,
            message="知识已入库",
            data={
                "id": entry.id,
                "tickers": entry.tickers,
                "category": entry.category,
                "summary": entry.summary,
            },
        )
    return APIResponse(success=False, message="入库失败", error="存储错误")


@router.post("/feed-url", response_model=APIResponse)
async def feed_url(request: KnowledgeFeedURLRequest):
    """
    投喂URL到知识库。
    系统自动抓取内容 → AI生成摘要 → 向量化 → 入库。
    """
    ks = get_knowledge_service()

    entry = await ks.add_from_url(
        url=request.url,
        category=request.category,
        tickers=request.tickers,
        tags=request.tags,
    )

    if entry:
        return APIResponse(
            success=True,
            message="URL内容已抓取并入库",
            data={
                "id": entry.id,
                "tickers": entry.tickers,
                "summary": entry.summary,
            },
        )
    return APIResponse(
        success=False, message="URL抓取或入库失败", error="请检查URL是否可访问"
    )


# ==================== SEARCH ENDPOINTS ====================

@router.get("/search")
async def search_knowledge(
    query: str = Query(..., description="搜索关键词"),
    top_k: int = Query(5, ge=1, le=20),
    source_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
):
    """
    语义搜索知识库。
    支持按 source_type, category, ticker 过滤。
    """
    ks = get_knowledge_service()
    tickers = [ticker] if ticker else None

    results = await ks.search(
        query=query,
        top_k=top_k,
        source_type=source_type,
        category=category,
        tickers=tickers,
    )

    return {
        "success": True,
        "query": query,
        "count": len(results),
        "results": results,
    }


@router.get("/ticker/{ticker}")
async def search_by_ticker(ticker: str, top_k: int = Query(10, ge=1, le=50)):
    """获取特定标的的所有相关知识条目。"""
    ks = get_knowledge_service()
    results = await ks.search_by_ticker(ticker.upper(), top_k=top_k)

    return {
        "success": True,
        "ticker": ticker.upper(),
        "count": len(results),
        "results": results,
    }


# ==================== MANAGEMENT ENDPOINTS ====================

@router.get("/stats")
async def get_stats():
    """知识库统计：总条数、按类型/分类分布、最近更新时间。"""
    ks = get_knowledge_service()
    stats = await ks.get_stats()
    return {"success": True, "data": stats.dict()}


@router.get("/recent")
async def get_recent(limit: int = Query(20, ge=1, le=100)):
    """获取最近入库的知识条目。"""
    ks = get_knowledge_service()
    entries = await ks.get_recent(limit=limit)
    return {"success": True, "count": len(entries), "entries": entries}


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str):
    """删除指定知识条目。"""
    ks = get_knowledge_service()
    success = await ks.delete_entry(entry_id)

    if success:
        return APIResponse(success=True, message=f"已删除知识条目 {entry_id}")
    return APIResponse(success=False, message="删除失败", error="条目不存在或已删除")
