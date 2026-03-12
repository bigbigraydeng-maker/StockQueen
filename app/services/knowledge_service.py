"""
StockQueen V2 - Knowledge Service
RAG knowledge base: write, search, and manage knowledge entries.
Uses Supabase pgvector for vector similarity search.
"""

import json
import logging
import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime, date

from app.database import get_db
from app.models import KnowledgeEntry, KnowledgeCreate, KnowledgeStats
from app.services.embedding_service import get_embedding_service
from app.config import settings

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Core knowledge base service: write, search, manage"""

    def __init__(self):
        self.embedding = get_embedding_service()

    # ==================== WRITE METHODS ====================

    async def add_knowledge(
        self,
        content: str,
        source_type: str,
        category: Optional[str] = None,
        tickers: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        relevance_date: Optional[str] = None,
        expires_at: Optional[str] = None,
        metadata: Optional[dict] = None,
        summary: Optional[str] = None,
    ) -> Optional[KnowledgeEntry]:
        """
        Add a knowledge entry: vectorize content and store in Supabase.
        """
        try:
            # Generate embedding
            embedding = await self.embedding.embed_text(content)
            if embedding is None:
                logger.error("Failed to generate embedding, storing without vector")

            # Auto-generate summary if not provided and content is long
            if not summary and len(content) > 300:
                summary = await self._generate_summary(content)

            # Auto-extract tickers if not provided
            if not tickers:
                tickers = self._extract_tickers(content)

            data = {
                "content": content,
                "summary": summary,
                "source_type": source_type,
                "category": category,
                "tickers": tickers or [],
                "tags": tags or [],
                "relevance_date": relevance_date or date.today().isoformat(),
                "metadata": json.dumps(metadata) if metadata else None,
            }

            if expires_at:
                data["expires_at"] = expires_at

            # Store embedding as string for pgvector
            if embedding:
                data["embedding"] = str(embedding)

            db = get_db()
            result = db.table("knowledge_base").insert(data).execute()

            if result.data:
                logger.info(
                    f"Knowledge added: {source_type} | "
                    f"tickers={tickers} | {content[:60]}..."
                )
                return KnowledgeEntry(**result.data[0])
            return None

        except Exception as e:
            logger.error(f"Error adding knowledge: {e}")
            return None

    async def add_from_url(
        self,
        url: str,
        category: Optional[str] = None,
        tickers: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[KnowledgeEntry]:
        """
        Fetch URL content, summarize with AI, and add to knowledge base.
        """
        try:
            # Fetch URL content
            content = await self._fetch_url_content(url)
            if not content:
                logger.error(f"Failed to fetch URL: {url}")
                return None

            # Generate summary via DeepSeek
            summary = await self._generate_summary(content)

            # Use summary as the main content (original may be too long)
            store_content = summary or content[:2000]

            return await self.add_knowledge(
                content=store_content,
                source_type="user_feed_url",
                category=category,
                tickers=tickers,
                tags=tags,
                metadata={"source_url": url, "original_length": len(content)},
                summary=summary,
            )

        except Exception as e:
            logger.error(f"Error adding from URL: {e}")
            return None

    # ==================== SEARCH METHODS ====================

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
        category: Optional[str] = None,
        tickers: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        Semantic search: vectorize query, find most similar entries.
        Returns list of dicts with content, similarity score, and metadata.
        """
        try:
            # Generate query embedding
            query_embedding = await self.embedding.embed_text(query)
            if query_embedding is None:
                logger.error("Failed to embed search query")
                return []

            # Use Supabase RPC for vector similarity search
            db = get_db()

            # Build the RPC call for cosine similarity search
            # Supabase pgvector: use match_knowledge function or raw SQL
            params = {
                "query_embedding": str(query_embedding),
                "match_count": top_k,
            }

            if source_type:
                params["filter_source_type"] = source_type
            if category:
                params["filter_category"] = category

            # Try RPC call first (requires a Supabase function)
            try:
                result = db.rpc("match_knowledge", params).execute()
                if result.data:
                    return result.data
            except Exception:
                # Fallback: manual query with ordering
                pass

            # Fallback: fetch recent entries and do client-side ranking
            query_builder = db.table("knowledge_base").select("*")

            if source_type:
                query_builder = query_builder.eq("source_type", source_type)
            if category:
                query_builder = query_builder.eq("category", category)
            if tickers:
                query_builder = query_builder.contains("tickers", tickers)

            query_builder = query_builder.order(
                "created_at", desc=True
            ).limit(top_k * 3)

            result = query_builder.execute()

            if not result.data:
                return []

            # Client-side: return most recent relevant entries
            entries = []
            for row in result.data[:top_k]:
                entries.append({
                    "id": row["id"],
                    "content": row["content"],
                    "summary": row.get("summary"),
                    "source_type": row["source_type"],
                    "category": row.get("category"),
                    "tickers": row.get("tickers", []),
                    "tags": row.get("tags", []),
                    "relevance_date": row.get("relevance_date"),
                    "created_at": row.get("created_at"),
                })

            return entries

        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return []

    async def search_by_ticker(
        self, ticker: str, top_k: int = 10
    ) -> List[dict]:
        """Retrieve all knowledge entries for a specific ticker."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("*")
                .contains("tickers", [ticker])
                .order("relevance_date", desc=True)
                .limit(top_k)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error searching by ticker {ticker}: {e}")
            return []

    async def get_context_for_signal(
        self, ticker: str, event_type: Optional[str] = None
    ) -> str:
        """
        Build RAG context string for AI prompt augmentation.
        Combines: ticker history + event type stats + sector trends.
        """
        context_parts = []

        # 1. Ticker-specific knowledge
        ticker_knowledge = await self.search_by_ticker(ticker, top_k=5)
        if ticker_knowledge:
            context_parts.append(f"=== {ticker} 历史知识 ===")
            for entry in ticker_knowledge:
                summary = entry.get("summary") or entry.get("content", "")[:200]
                context_parts.append(f"- [{entry.get('relevance_date', '')}] {summary}")

        # 2. Event type statistics
        if event_type:
            event_knowledge = await self.search(
                query=f"{event_type} 事件统计 胜率",
                top_k=3,
                source_type="auto_news_outcome",
            )
            if event_knowledge:
                context_parts.append(f"\n=== {event_type} 事件统计 ===")
                for entry in event_knowledge:
                    context_parts.append(
                        f"- {entry.get('summary') or entry.get('content', '')[:200]}"
                    )

        # 3. Recent sector/macro context
        sector_knowledge = await self.search(
            query=f"{ticker} 板块 行业趋势",
            top_k=2,
            source_type="auto_sector_rotation",
        )
        if sector_knowledge:
            context_parts.append("\n=== 板块趋势 ===")
            for entry in sector_knowledge:
                context_parts.append(
                    f"- {entry.get('summary') or entry.get('content', '')[:200]}"
                )

        return "\n".join(context_parts) if context_parts else ""

    async def get_rag_score_adjustment(self, ticker: str) -> float:
        """
        Compute RAG-based score adjustment for rotation scoring.
        Priority: AI sentiment score (from AISentimentCollector) → keyword fallback.
        Returns: float in [-3.0, +3.0]
          positive = bullish intel, negative = bearish intel, 0 = no intel
        """
        try:
            # 优先使用 AI 情绪评分（来自 AISentimentCollector）
            ai_score = await self._get_ai_sentiment(ticker)
            if ai_score is not None:
                return ai_score * 3.0  # [-1,+1] → [-3,+3]

            # 回退到关键词匹配
            return await self._keyword_score_adjustment(ticker)

        except Exception as e:
            logger.error(f"Error computing RAG adjustment for {ticker}: {e}")
            return 0.0

    async def _get_ai_sentiment(self, ticker: str) -> Optional[float]:
        """
        Query the latest AI sentiment score for a ticker.
        Returns: float in [-1.0, +1.0] or None if not available/low confidence.
        """
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("content, metadata, created_at")
                .eq("source_type", "auto_ai_sentiment")
                .contains("tickers", [ticker])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if not result.data:
                return None

            entry = result.data[0]
            meta = entry.get("metadata")
            if isinstance(meta, str):
                meta = json.loads(meta)

            if not meta:
                return None

            # Extract score and confidence from metadata
            score = meta.get("score")
            confidence = meta.get("confidence", 0.0)

            # Only use if confidence > 0.3
            if score is not None and confidence > 0.3:
                logger.debug(
                    f"AI sentiment for {ticker}: score={score}, "
                    f"confidence={confidence}"
                )
                return float(score)

            return None

        except Exception as e:
            logger.error(f"Error getting AI sentiment for {ticker}: {e}")
            return None

    async def _keyword_score_adjustment(self, ticker: str) -> float:
        """
        Fallback: keyword-based score adjustment from knowledge entries.
        Returns: float in [-3.0, +3.0]
        """
        try:
            entries = await self.search_by_ticker(ticker, top_k=5)
            if not entries:
                return 0.0

            positive_keywords = [
                "bullish", "outperform", "buy", "upgrade", "beat",
                "看好", "利好", "上调", "突破", "增长", "超预期",
                "positive", "strong", "accelerat",
            ]
            negative_keywords = [
                "bearish", "underperform", "sell", "downgrade", "miss",
                "看空", "利空", "下调", "风险", "下跌", "低于预期",
                "negative", "weak", "decline", "warning",
            ]

            score = 0.0
            for entry in entries:
                text = (
                    (entry.get("summary") or "") +
                    (entry.get("content") or "")
                ).lower()

                for kw in positive_keywords:
                    if kw in text:
                        score += 0.3
                        break
                for kw in negative_keywords:
                    if kw in text:
                        score -= 0.3
                        break

            return max(-3.0, min(3.0, score))

        except Exception as e:
            logger.error(f"Error in keyword score adjustment for {ticker}: {e}")
            return 0.0

    # ==================== MANAGEMENT METHODS ====================

    async def get_stats(self) -> KnowledgeStats:
        """Get knowledge base statistics."""
        try:
            db = get_db()

            # Total count
            total_result = db.table("knowledge_base").select(
                "id", count="exact"
            ).execute()
            total = total_result.count or 0

            # By source type
            all_entries = db.table("knowledge_base").select(
                "source_type, category"
            ).execute()

            by_source = {}
            by_category = {}
            for row in (all_entries.data or []):
                src = row.get("source_type", "unknown")
                by_source[src] = by_source.get(src, 0) + 1

                cat = row.get("category") or "uncategorized"
                by_category[cat] = by_category.get(cat, 0) + 1

            # Latest entry
            latest = (
                db.table("knowledge_base")
                .select("created_at")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            latest_date = None
            if latest.data:
                latest_date = latest.data[0].get("created_at")

            return KnowledgeStats(
                total_entries=total,
                by_source_type=by_source,
                by_category=by_category,
                latest_entry_date=latest_date,
            )

        except Exception as e:
            logger.error(f"Error getting knowledge stats: {e}")
            return KnowledgeStats()

    async def get_recent(self, limit: int = 20) -> List[dict]:
        """Get most recent knowledge entries."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("id, content, summary, source_type, category, tickers, tags, relevance_date, created_at")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting recent knowledge: {e}")
            return []

    async def delete_entry(self, entry_id: str) -> bool:
        """Delete a knowledge entry by ID."""
        try:
            db = get_db()
            db.table("knowledge_base").delete().eq("id", entry_id).execute()
            logger.info(f"Deleted knowledge entry: {entry_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting knowledge entry: {e}")
            return False

    async def cleanup_expired(self) -> int:
        """Remove expired knowledge entries. Returns count of deleted entries."""
        try:
            db = get_db()
            now = datetime.utcnow().isoformat()

            # Find expired entries
            result = (
                db.table("knowledge_base")
                .select("id")
                .lt("expires_at", now)
                .execute()
            )

            if not result.data:
                return 0

            count = len(result.data)
            db.table("knowledge_base").delete().lt("expires_at", now).execute()

            logger.info(f"Cleaned up {count} expired knowledge entries")
            return count

        except Exception as e:
            logger.error(f"Error cleaning up expired knowledge: {e}")
            return 0

    # ==================== PRIVATE HELPERS ====================

    async def _generate_summary(self, content: str) -> Optional[str]:
        """Use OpenAI to generate a concise summary."""
        try:
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": settings.openai_chat_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一个金融分析师。请用中文将以下内容总结为200字以内的摘要，"
                            "保留关键数据和结论。如果内容中提到股票代码，请保留。"
                        ),
                    },
                    {"role": "user", "content": content[:4000]},
                ],
                "temperature": 0.3,
                "max_tokens": 300,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.openai_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return None

    async def _fetch_url_content(self, url: str) -> Optional[str]:
        """Fetch and extract text content from a URL."""
        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "StockQueen/2.0 Knowledge Collector"},
                )
                response.raise_for_status()
                html = response.text

            # Simple text extraction (strip HTML tags)
            import re

            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            return text[:10000] if text else None

        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return None

    @staticmethod
    def _extract_tickers(text: str) -> List[str]:
        """Extract stock tickers from text using regex."""
        import re

        # Match 1-5 uppercase letters that look like tickers
        candidates = re.findall(r"\b([A-Z]{1,5})\b", text)

        # Filter common English words
        stop_words = {
            "THE", "AND", "FOR", "NOT", "ARE", "BUT", "ALL", "CAN", "HAS",
            "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "HAD", "HOT", "OIL",
            "OLD", "RED", "SIT", "TOP", "TWO", "WAR", "BIG", "END", "NEW",
            "NOW", "TRY", "USE", "WHO", "BOY", "DID", "GET", "HIS", "HOW",
            "MAN", "SAY", "SHE", "TOO", "ETF", "IPO", "CEO", "CFO", "FDA",
            "SEC", "NYSE", "ATR", "RSI", "API", "URL", "RAG", "NLP", "AI",
        }

        tickers = []
        seen = set()
        for t in candidates:
            if t not in stop_words and t not in seen and len(t) >= 2:
                tickers.append(t)
                seen.add(t)

        return tickers[:10]  # Max 10 tickers per entry


# Convenience functions

_knowledge_service: Optional[KnowledgeService] = None


def get_knowledge_service() -> KnowledgeService:
    """Get or create knowledge service singleton"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
