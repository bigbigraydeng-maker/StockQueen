"""
StockQueen V2 - Knowledge Service
RAG knowledge base: write, search, and manage knowledge entries.
Uses Supabase pgvector for vector similarity search.
"""

import json
import logging
import re
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

    # Chunking thresholds
    CHUNK_THRESHOLD = 1000    # Only chunk content longer than this
    CHUNK_SIZE = 600          # Target chunk size in chars
    CHUNK_OVERLAP = 100       # Overlap between consecutive chunks

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
        Add a knowledge entry with automatic chunking for long content.
        Short content (<1000 chars): single entry with embedding.
        Long content: parent entry (no embedding) + chunk entries (each with embedding).
        """
        try:
            # Auto-extract tickers if not provided
            if not tickers:
                tickers = self._extract_tickers(content)

            # Auto-generate summary if not provided and content is long
            if not summary and len(content) > 300:
                summary = await self._generate_summary(content)

            rel_date = relevance_date or date.today().isoformat()
            meta_json = json.dumps(metadata) if metadata else None

            chunks = self._chunk_text(content)

            db = get_db()

            if len(chunks) <= 1:
                # === SHORT CONTENT PATH (unchanged behavior) ===
                embedding = await self.embedding.embed_text(content)
                if embedding is None:
                    logger.error("Failed to generate embedding, storing without vector")

                data = {
                    "content": content,
                    "summary": summary,
                    "source_type": source_type,
                    "category": category,
                    "tickers": tickers or [],
                    "tags": tags or [],
                    "relevance_date": rel_date,
                    "metadata": meta_json,
                }
                if expires_at:
                    data["expires_at"] = expires_at
                if embedding:
                    data["embedding"] = str(embedding)

                result = db.table("knowledge_base").insert(data).execute()
                if result.data:
                    logger.info(
                        f"Knowledge added: {source_type} | "
                        f"tickers={tickers} | {content[:60]}..."
                    )
                    return KnowledgeEntry(**result.data[0])
                return None

            else:
                # === LONG CONTENT PATH (chunked) ===
                # 1. Insert parent entry (no embedding — only chunks are searchable)
                parent_data = {
                    "content": content[:10000],  # store full text for reference
                    "summary": summary,
                    "source_type": source_type,
                    "category": category,
                    "tickers": tickers or [],
                    "tags": tags or [],
                    "relevance_date": rel_date,
                    "metadata": meta_json,
                    # embedding=NULL → parent excluded from vector search
                }
                if expires_at:
                    parent_data["expires_at"] = expires_at

                parent_result = db.table("knowledge_base").insert(parent_data).execute()
                if not parent_result.data:
                    logger.error("Failed to insert parent entry")
                    return None

                parent_id = parent_result.data[0]["id"]
                logger.info(
                    f"Parent entry created: {parent_id} | {len(chunks)} chunks | "
                    f"{source_type} | tickers={tickers}"
                )

                # 2. Batch embed all chunks
                embeddings = await self.embedding.embed_batch(chunks)

                # 3. Insert chunk rows
                chunk_rows = []
                for i, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
                    chunk_data = {
                        "content": chunk_text,
                        "source_type": source_type,
                        "category": category,
                        "tickers": tickers or [],
                        "tags": tags or [],
                        "relevance_date": rel_date,
                        "metadata": meta_json,
                        "parent_id": parent_id,
                        "chunk_index": i,
                    }
                    if expires_at:
                        chunk_data["expires_at"] = expires_at
                    if emb:
                        chunk_data["embedding"] = str(emb)
                    chunk_rows.append(chunk_data)

                # Bulk insert chunks
                if chunk_rows:
                    db.table("knowledge_base").insert(chunk_rows).execute()
                    logger.info(f"Inserted {len(chunk_rows)} chunks for parent {parent_id}")

                return KnowledgeEntry(**parent_result.data[0])

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
        Fetch URL content, summarize, and add FULL content to knowledge base.
        Long content will be automatically chunked by add_knowledge().
        Summary is preserved on the parent entry for UI display.
        """
        try:
            # Fetch URL content
            content = await self._fetch_url_content(url)
            if not content:
                logger.error(f"Failed to fetch URL: {url}")
                return None

            # Generate summary via DeepSeek
            summary = await self._generate_summary(content)

            # Store FULL content (not just summary) — add_knowledge will chunk it
            return await self.add_knowledge(
                content=content,
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
        Semantic search with chunk-aware deduplication.
        If multiple chunks from the same parent match, only the best-scoring one is kept.
        Returns list of dicts with content, similarity score, and metadata.
        """
        try:
            # Generate query embedding
            query_embedding = await self.embedding.embed_text(query)
            if query_embedding is None:
                logger.error("Failed to embed search query")
                return []

            db = get_db()

            # Request more results to account for chunk deduplication
            fetch_count = top_k * 3

            params = {
                "query_embedding": str(query_embedding),
                "match_count": fetch_count,
            }
            if source_type:
                params["filter_source_type"] = source_type
            if category:
                params["filter_category"] = category

            raw_results = []

            # Try RPC call first
            try:
                result = db.rpc("match_knowledge", params).execute()
                if result.data:
                    raw_results = result.data
            except Exception:
                pass

            # Fallback: manual query
            if not raw_results:
                query_builder = db.table("knowledge_base").select("*")
                query_builder = query_builder.is_("parent_id", "null")  # exclude chunks in fallback
                if source_type:
                    query_builder = query_builder.eq("source_type", source_type)
                if category:
                    query_builder = query_builder.eq("category", category)
                if tickers:
                    query_builder = query_builder.contains("tickers", tickers)
                query_builder = query_builder.order("created_at", desc=True).limit(fetch_count)
                result = query_builder.execute()
                if result.data:
                    raw_results = result.data

            if not raw_results:
                return []

            # Deduplicate: for chunks from same parent, keep highest similarity
            seen_parents = {}  # parent_id -> best result
            final = []

            for row in raw_results:
                pid = row.get("parent_id")
                if pid:
                    # This is a chunk — deduplicate by parent
                    if pid in seen_parents:
                        continue
                    seen_parents[pid] = True
                    # Fetch parent summary for display context
                    try:
                        parent = (
                            db.table("knowledge_base")
                            .select("summary, content")
                            .eq("id", str(pid))
                            .limit(1)
                            .execute()
                        )
                        if parent.data:
                            row["parent_summary"] = parent.data[0].get("summary")
                    except Exception:
                        pass
                final.append(row)
                if len(final) >= top_k:
                    break

            return final

        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return []

    async def search_by_ticker(
        self, ticker: str, top_k: int = 10
    ) -> List[dict]:
        """Retrieve all knowledge entries for a specific ticker (excludes chunks)."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("*")
                .contains("tickers", [ticker])
                .is_("parent_id", "null")  # only standalone/parent entries
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
        Multi-factor RAG-based score adjustment for rotation scoring.
        Aggregates signals from multiple knowledge sources:
          - AI sentiment (weight 0.25)
          - Fundamental quality (weight 0.25)
          - Earnings quality (weight 0.20)
          - Cash flow health (weight 0.15)
          - Keyword fallback (weight 0.15)
        Returns: float in [-3.0, +3.0]
        """
        try:
            total = 0.0
            total_weight = 0.0

            # 1. AI sentiment (from AISentimentCollector)
            ai_score = await self._get_ai_sentiment(ticker)
            if ai_score is not None:
                total += ai_score * 0.25
                total_weight += 0.25

            # 2. Fundamental quality (from FundamentalDataCollector)
            fund_score = await self._get_factor_score(ticker, "auto_fundamental")
            if fund_score is not None:
                total += fund_score * 0.25
                total_weight += 0.25

            # 3. Earnings quality (from EarningsCalendarCollector)
            earn_score = await self._get_earnings_score(ticker)
            if earn_score is not None:
                total += earn_score * 0.20
                total_weight += 0.20

            # 4. Cash flow health (from CashFlowHealthCollector)
            cf_score = await self._get_cashflow_score(ticker)
            if cf_score is not None:
                total += cf_score * 0.15
                total_weight += 0.15

            # 5. Keyword fallback
            if total_weight < 0.5:
                kw_score = await self._keyword_score_adjustment(ticker)
                kw_normalized = kw_score / 3.0  # [-3,+3] → [-1,+1]
                total += kw_normalized * 0.15
                total_weight += 0.15

            if total_weight == 0:
                return 0.0

            # Normalize to [-1,+1] then scale to [-3,+3]
            normalized = total / total_weight
            return normalized * 3.0

        except Exception as e:
            logger.error(f"Error computing RAG adjustment for {ticker}: {e}")
            return 0.0

    async def _get_factor_score(self, ticker: str, source_type: str) -> Optional[float]:
        """Generic factor score extractor from knowledge_base metadata."""
        try:
            from app.services.multi_factor_scorer import score_fundamental
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("metadata")
                .eq("source_type", source_type)
                .contains("tickers", [ticker])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None

            meta = result.data[0].get("metadata")
            if isinstance(meta, str):
                meta = json.loads(meta)
            if not meta:
                return None

            # Use MultiFactorScorer to evaluate
            factor = score_fundamental(meta)
            return factor.get("score", 0.0) if factor.get("available") else None

        except Exception as e:
            logger.debug(f"Factor score not available for {ticker}/{source_type}: {e}")
            return None

    async def _get_earnings_score(self, ticker: str) -> Optional[float]:
        """Extract earnings quality score from knowledge_base."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("metadata")
                .eq("source_type", "auto_earnings_cal")
                .contains("tickers", [ticker])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None

            meta = result.data[0].get("metadata")
            if isinstance(meta, str):
                meta = json.loads(meta)
            if not meta:
                return None

            score = 0.0
            beat_rate = meta.get("beat_rate", 0)
            surprise = meta.get("latest_surprise_pct", 0)

            if beat_rate >= 0.75:
                score += 0.4
            elif beat_rate < 0.25:
                score -= 0.3

            if surprise and surprise > 10:
                score += 0.3
            elif surprise and surprise < -10:
                score -= 0.3

            return max(-1.0, min(1.0, score))

        except Exception:
            return None

    async def _get_cashflow_score(self, ticker: str) -> Optional[float]:
        """Extract cash flow health score from knowledge_base."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("metadata")
                .eq("source_type", "auto_cashflow")
                .contains("tickers", [ticker])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None

            meta = result.data[0].get("metadata")
            if isinstance(meta, str):
                meta = json.loads(meta)
            if not meta:
                return None

            health = meta.get("health", "")
            if health == "healthy":
                return 0.5
            elif health == "warning":
                return 0.0
            elif health == "critical":
                return -0.5
            return None

        except Exception:
            return None

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

    # ==================== MULTI-FACTOR DATA PROVIDER ====================

    async def get_factor_data_for_scorer(self, ticker: str) -> dict:
        """
        Retrieve raw factor data from knowledge base for MultiFactorScorer.
        Used by rotation_service to pass structured data to compute_multi_factor_score().

        Returns dict with keys:
            overview, earnings_data, cashflow_data, sentiment_value, sector_returns
        """
        result = {}

        # 1. Fundamental overview (from auto_fundamental)
        overview = await self._get_kb_metadata(ticker, "auto_fundamental")
        if overview:
            result["overview"] = overview

        # 2. Earnings data (from auto_earnings_cal)
        earnings_meta = await self._get_kb_metadata(ticker, "auto_earnings_cal")
        if earnings_meta and earnings_meta.get("quarters"):
            result["earnings_data"] = {"quarterly": earnings_meta["quarters"]}

        # 3. Cash flow data (from auto_cashflow)
        cashflow_meta = await self._get_kb_metadata(ticker, "auto_cashflow")
        if cashflow_meta and cashflow_meta.get("quarterly"):
            result["cashflow_data"] = {"quarterly": cashflow_meta["quarterly"]}

        # 4. Sentiment value (from auto_ai_sentiment)
        sentiment = await self._get_ai_sentiment(ticker)
        if sentiment is not None:
            result["sentiment_value"] = sentiment

        # 5. Sector returns (from auto_sector_perf)
        sector_meta = await self._get_kb_metadata(None, "auto_sector_perf")
        if sector_meta and sector_meta.get("sectors"):
            # Convert {sector: {ret_1m: ...}} → {sector: ret_1m}
            sector_rets = {}
            for sec, data in sector_meta["sectors"].items():
                if isinstance(data, dict):
                    sector_rets[sec] = data.get("ret_1m", 0)
                else:
                    sector_rets[sec] = 0
            result["sector_returns"] = sector_rets

        return result

    async def _get_kb_metadata(self, ticker: Optional[str],
                                source_type: str) -> Optional[dict]:
        """Get latest metadata from knowledge_base for a source type."""
        try:
            db = get_db()
            query = (
                db.table("knowledge_base")
                .select("metadata")
                .eq("source_type", source_type)
            )
            if ticker:
                query = query.contains("tickers", [ticker])
            result = query.order("created_at", desc=True).limit(1).execute()
            if not result.data:
                return None

            meta = result.data[0].get("metadata")
            if isinstance(meta, str):
                meta = json.loads(meta)
            return meta
        except Exception:
            return None

    # ==================== MANAGEMENT METHODS ====================

    async def get_stats(self) -> KnowledgeStats:
        """Get knowledge base statistics (excludes chunk rows)."""
        try:
            db = get_db()

            # Total count (exclude chunks)
            total_result = db.table("knowledge_base").select(
                "id", count="exact"
            ).is_("parent_id", "null").execute()
            total = total_result.count or 0

            # By source type (exclude chunks)
            all_entries = db.table("knowledge_base").select(
                "source_type, category"
            ).is_("parent_id", "null").execute()

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
        """Get most recent knowledge entries (excludes chunk rows)."""
        try:
            db = get_db()
            result = (
                db.table("knowledge_base")
                .select("id, content, summary, source_type, category, tickers, tags, relevance_date, created_at")
                .is_("parent_id", "null")  # only standalone/parent entries
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

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP,
    ) -> List[str]:
        """
        Split long text into overlapping chunks for independent embedding.
        Returns [text] unchanged if below CHUNK_THRESHOLD.
        Split priority: paragraph > sentence > space > hard cut.
        """
        if len(text) <= self.CHUNK_THRESHOLD:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            if end >= len(text):
                # Last chunk — take everything remaining
                chunks.append(text[start:].strip())
                break

            # Find best split point within [end-100, end+100]
            search_start = max(start, end - 100)
            search_end = min(len(text), end + 100)
            window = text[search_start:search_end]

            split_pos = None

            # Priority 1: paragraph break
            para_idx = window.rfind("\n\n")
            if para_idx != -1:
                split_pos = search_start + para_idx + 2

            # Priority 2: sentence end (. ! ? 。！？)
            if split_pos is None:
                for delim in [". ", "。", "! ", "！", "? ", "？"]:
                    idx = window.rfind(delim)
                    if idx != -1:
                        split_pos = search_start + idx + len(delim)
                        break

            # Priority 3: space / comma
            if split_pos is None:
                for delim in [" ", ", ", "，"]:
                    idx = window.rfind(delim)
                    if idx != -1:
                        split_pos = search_start + idx + len(delim)
                        break

            # Priority 4: hard cut
            if split_pos is None:
                split_pos = end

            chunk = text[start:split_pos].strip()
            if chunk:
                chunks.append(chunk)

            # Next chunk starts with overlap from current chunk's end
            start = max(split_pos - overlap, start + 1)

        logger.info(f"Text chunked: {len(text)} chars → {len(chunks)} chunks (~{chunk_size} chars each)")
        return chunks

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
        """Fetch and extract text content from a URL.
        Uses browser-like headers + BeautifulSoup for robust extraction."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
            }

            async with httpx.AsyncClient(
                timeout=30.0, follow_redirects=True, http2=True
            ) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                html = response.text

            if not html or len(html.strip()) < 100:
                logger.warning(f"URL returned very short content ({len(html)} chars): {url}")
                return None

            # Use BeautifulSoup for robust HTML parsing
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")

                # Remove non-content elements
                for tag in soup.find_all(["script", "style", "nav", "footer",
                                          "aside", "noscript", "iframe"]):
                    tag.decompose()

                # Try to find main content area
                content_el = (
                    soup.find("article") or
                    soup.find("main") or
                    soup.find(class_=lambda c: c and any(
                        k in str(c).lower() for k in ["post-content", "article", "entry-content", "blog-post"]
                    )) or
                    soup.find("body")
                )

                text = content_el.get_text(separator=" ", strip=True) if content_el else soup.get_text(separator=" ", strip=True)

            except ImportError:
                # Fallback to regex if BeautifulSoup not available
                import re
                html_content = html
                for tag in ["script", "style", "nav", "header", "footer", "aside"]:
                    html_content = re.sub(
                        rf"<{tag}[^>]*>.*?</{tag}>", "", html_content, flags=re.DOTALL
                    )
                text = re.sub(r"<[^>]+>", " ", html_content)

            # Clean up whitespace
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) < 50:
                logger.warning(f"Extracted text too short ({len(text)} chars) from {url}")
                return None

            logger.info(f"URL fetched successfully: {url} ({len(text)} chars extracted)")
            return text[:10000]

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code} fetching URL {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return None

    @staticmethod
    def _extract_tickers(text: str) -> List[str]:
        """Extract stock tickers from text using regex."""

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
