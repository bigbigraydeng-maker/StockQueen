"""
StockQueen C2 - News Scanner Service
Daily after-hours AI event signal generation.

Pipeline:
1. Get scan universe: Tiger positions + top rotation candidates
2. Fetch AV NEWS_SENTIMENT per ticker (past 24h)
3. Classify each article with DeepSeek (general stock events)
4. Filter: relevance > 0.3, strong sentiment, not already processed
5. Send Feishu summary + persist to event_signals table
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type definitions for general stock events (not pharma-only)
# ---------------------------------------------------------------------------

STOCK_EVENT_TYPES = [
    "earnings_beat",        # 财报超预期
    "earnings_miss",        # 财报不及预期
    "analyst_upgrade",      # 分析师升级/买入评级
    "analyst_downgrade",    # 分析师降级/卖出评级
    "guidance_raise",       # 业绩指引上调
    "guidance_cut",         # 业绩指引下调
    "fda_approval",         # FDA 批准
    "fda_rejection",        # FDA 拒绝/CRL
    "ma_activity",          # 并购传言/收购
    "management_change",    # 管理层变动（CEO/CFO）
    "buyback",              # 股票回购
    "macro_risk",           # 宏观风险（关税/制裁）
    "other_positive",       # 其他利多
    "other_negative",       # 其他利空
    "noise",                # 噪音/无操作价值
]

EVENT_EMOJI = {
    "earnings_beat":     "✅",
    "earnings_miss":     "❌",
    "analyst_upgrade":   "📈",
    "analyst_downgrade": "📉",
    "guidance_raise":    "🚀",
    "guidance_cut":      "⚠️",
    "fda_approval":      "💊",
    "fda_rejection":     "🚫",
    "ma_activity":       "🤝",
    "management_change": "👤",
    "buyback":           "💰",
    "macro_risk":        "🌍",
    "other_positive":    "🟢",
    "other_negative":    "🔴",
    "noise":             "⚪",
}

# Minimum signal strength to include in push (suppress noise)
MIN_SIGNAL_STRENGTH = 0.30
# Minimum relevance score from AV ticker_sentiment
MIN_RELEVANCE_SCORE = 0.30
# Max articles to send per Feishu message
MAX_EVENTS_PER_PUSH = 12
# News lookback window in hours
LOOKBACK_HOURS = 26


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

class NewsEventScanner:
    """After-hours AI event signal scanner."""

    async def run_daily_scan(self) -> dict:
        """
        Main entry point. Run after market close (NZT 09:50 Tue-Sat).
        Returns summary dict with counts.
        """
        result = {"scanned": 0, "events": 0, "sent": False, "errors": 0}
        logger.info("[NewsScanner] Starting daily event scan")

        try:
            # 1. Get tickers to scan
            tickers = await self._get_scan_universe()
            if not tickers:
                logger.warning("[NewsScanner] No tickers to scan")
                return result
            logger.info(f"[NewsScanner] Scanning {len(tickers)} tickers: {tickers[:10]}...")

            # 2. Fetch + classify events
            events = await self._fetch_and_classify(tickers)
            result["scanned"] = len(tickers)
            result["events"] = len(events)

            if not events:
                logger.info("[NewsScanner] No significant events found")
                return result

            # 3. Persist to DB
            await self._save_events(events)
            result["sent"] = True

        except Exception as e:
            logger.error(f"[NewsScanner] Daily scan failed: {e}", exc_info=True)
            result["errors"] += 1

        logger.info(f"[NewsScanner] Done: {result}")
        return result

    # ------------------------------------------------------------------
    # Step 1: Build scan universe
    # ------------------------------------------------------------------

    async def _get_scan_universe(self) -> list[str]:
        """
        Returns tickers to scan today:
          - Current Tiger positions (always included)
          - Top N tickers from latest rotation snapshot
        Capped at 60 to stay within AV rate limits.
        """
        tickers: set[str] = set()

        # (a) Current Tiger live positions
        try:
            from app.services.order_service import get_tiger_trade_client
            client = get_tiger_trade_client()
            positions = await client.get_positions()
            for p in positions:
                t = p.get("ticker", "")
                if t:
                    tickers.add(t)
            logger.info(f"[NewsScanner] Tiger positions: {sorted(tickers)}")
        except Exception as e:
            logger.warning(f"[NewsScanner] Could not fetch Tiger positions: {e}")

        # (b) Top tickers from latest rotation snapshot
        try:
            db = get_db()
            snap = (
                db.table("rotation_snapshots")
                .select("selected_tickers, scores")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if snap.data:
                row = snap.data[0]
                # selected_tickers: list of holding tickers
                selected = row.get("selected_tickers") or []
                if isinstance(selected, list):
                    tickers.update(selected)
                # scores: list of {ticker, score, ...} — take top 40
                all_scores = row.get("scores") or []
                if isinstance(all_scores, list):
                    sorted_scores = sorted(
                        all_scores, key=lambda x: x.get("score", 0), reverse=True
                    )
                    for item in sorted_scores[:40]:
                        t = item.get("ticker", "")
                        if t:
                            tickers.add(t)
        except Exception as e:
            logger.warning(f"[NewsScanner] Could not fetch rotation snapshot: {e}")

        # Fallback: use rotation watchlist directly
        if not tickers:
            try:
                from app.config.rotation_watchlist import OFFENSIVE_ETFS, LARGECAP_STOCKS, MIDCAP_STOCKS
                for pool in [OFFENSIVE_ETFS, LARGECAP_STOCKS, MIDCAP_STOCKS]:
                    for item in pool[:20]:
                        tickers.add(item["ticker"])
            except Exception as e:
                logger.warning(f"[NewsScanner] Could not load rotation watchlist: {e}")

        # Cap at 60 tickers
        return list(tickers)[:60]

    # ------------------------------------------------------------------
    # Step 2: Fetch news + classify
    # ------------------------------------------------------------------

    async def _fetch_and_classify(self, tickers: list[str]) -> list[dict]:
        """
        For each ticker:
          1. Pull last LOOKBACK_HOURS of news from AV
          2. Filter by relevance_score and time
          3. Classify with DeepSeek
          4. Deduplicate (skip already-processed URLs)
        Returns list of event dicts, sorted by signal_strength desc.
        """
        from app.services.alphavantage_client import get_av_client
        from app.services.ai_service import DeepSeekStockClassifier

        av = get_av_client()
        classifier = DeepSeekStockClassifier()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

        seen_urls: set[str] = set()
        events: list[dict] = []

        for ticker in tickers:
            try:
                articles = await av.get_news_sentiment(tickers=[ticker], limit=20)
                if not articles:
                    continue

                for article in articles:
                    url = article.get("url", "")

                    # Skip duplicate URLs within this run
                    if url in seen_urls:
                        continue

                    # Time filter
                    pub_str = article.get("published", "")
                    if pub_str:
                        try:
                            # AV format: "20241215T163000"
                            pub_dt = datetime.strptime(pub_str[:15], "%Y%m%dT%H%M%S")
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                            if pub_dt < cutoff:
                                continue
                        except Exception:
                            pass

                    # Find this ticker's relevance + sentiment
                    ticker_data = None
                    for ts in article.get("ticker_sentiments", []):
                        if ts.get("ticker") == ticker:
                            ticker_data = ts
                            break
                    if not ticker_data:
                        continue

                    relevance = ticker_data.get("relevance_score", 0)
                    sentiment = ticker_data.get("sentiment_score", 0)

                    if relevance < MIN_RELEVANCE_SCORE:
                        continue
                    if abs(sentiment) < 0.15:
                        continue

                    # Check DB dedup
                    if await self._is_already_processed(url):
                        seen_urls.add(url)
                        continue

                    seen_urls.add(url)

                    # Classify with DeepSeek
                    title = article.get("title", "")
                    summary = article.get("summary", "")
                    classification = await classifier.classify(title, summary, ticker)

                    if not classification or classification["event_type"] == "noise":
                        continue

                    # Compute signal strength = relevance * |sentiment| * direction_multiplier
                    direction_mult = 1.0 if classification["direction"] == "bullish" else -1.0
                    signal_strength = relevance * abs(sentiment) * direction_mult

                    if abs(signal_strength) < MIN_SIGNAL_STRENGTH:
                        continue

                    events.append({
                        "date": datetime.now(timezone.utc).date().isoformat(),
                        "ticker": ticker,
                        "event_type": classification["event_type"],
                        "direction": classification["direction"],
                        "headline": title[:200],
                        "summary": summary[:400] if summary else "",
                        "signal_strength": round(signal_strength, 3),
                        "relevance_score": round(relevance, 3),
                        "sentiment_score": round(sentiment, 3),
                        "source": article.get("source", ""),
                        "url": url,
                        "published": pub_str,
                    })

            except Exception as e:
                logger.error(f"[NewsScanner] Error processing {ticker}: {e}")

        # Sort by |signal_strength| descending, keep top MAX_EVENTS_PER_PUSH
        events.sort(key=lambda x: abs(x["signal_strength"]), reverse=True)
        return events[:MAX_EVENTS_PER_PUSH]

    # ------------------------------------------------------------------
    # Step 3: Dedup check
    # ------------------------------------------------------------------

    async def _is_already_processed(self, url: str) -> bool:
        """Check if this article URL was already stored in event_signals."""
        if not url:
            return False
        try:
            db = get_db()
            result = (
                db.table("event_signals")
                .select("id")
                .eq("url", url)
                .limit(1)
                .execute()
            )
            return bool(result.data)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Step 4: Persist
    # ------------------------------------------------------------------

    async def _save_events(self, events: list[dict]) -> None:
        """Upsert events to event_signals table."""
        try:
            db = get_db()
            for ev in events:
                try:
                    db.table("event_signals").upsert(
                        {
                            "date": ev["date"],
                            "ticker": ev["ticker"],
                            "event_type": ev["event_type"],
                            "direction": ev["direction"],
                            "headline": ev["headline"],
                            "summary": ev.get("summary", ""),
                            "signal_strength": ev["signal_strength"],
                            "relevance_score": ev["relevance_score"],
                            "sentiment_score": ev["sentiment_score"],
                            "source": ev.get("source", ""),
                            "url": ev.get("url", ""),
                            "published": ev.get("published", ""),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                        on_conflict="url",
                    ).execute()
                except Exception as e:
                    logger.error(f"[NewsScanner] DB save error for {ev['ticker']}: {e}")
        except Exception as e:
            logger.error(f"[NewsScanner] DB connection error: {e}")



# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_scanner: Optional[NewsEventScanner] = None


def get_news_scanner() -> NewsEventScanner:
    global _scanner
    if _scanner is None:
        _scanner = NewsEventScanner()
    return _scanner
