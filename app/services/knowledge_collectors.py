"""
StockQueen V2.3 - Knowledge Collectors
4 automated data collectors that populate the RAG knowledge base.
Uses Alpha Vantage for market data (replaces yfinance).

1. SignalOutcomeCollector  - tracks signal P&L at 1d/5d/20d
2. NewsOutcomeCollector    - correlates news events with subsequent price moves
3. PatternStatCollector    - statistical summary of technical patterns
4. SectorRotationCollector - records weekly sector/ETF ranking changes
"""

import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta, date

import pandas as pd

from app.database import get_db
from app.services.knowledge_service import get_knowledge_service
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)


def _get_dynamic_universe_tickers() -> list:
    """
    获取动态选股池完整 ticker 列表（约1578只）。
    优先从 UniverseService 读取；失败时回退到 MIDCAP_STOCKS 静态列表。
    """
    try:
        from app.services.universe_service import UniverseService
        tickers = UniverseService().get_current_universe()
        if tickers:
            logger.info(f"[FMP] 动态选股池加载成功: {len(tickers)} 只")
            return tickers
    except Exception as e:
        logger.warning(f"[FMP] 动态选股池不可用，回退到 MIDCAP_STOCKS: {e}")
    from app.config.rotation_watchlist import MIDCAP_STOCKS
    return [s["ticker"] for s in MIDCAP_STOCKS]


# ============================================================
# 1. Signal Outcome Collector
# ============================================================

class SignalOutcomeCollector:
    """
    Tracks the actual outcome of every executed signal.
    Runs daily: checks 1d/5d/20d price after each signal's entry date.
    Writes both signal_outcomes table and knowledge_base.
    """

    async def run(self) -> dict:
        """Main entry point. Called by scheduler daily."""
        results = {"processed": 0, "errors": 0}
        logger.info("SignalOutcomeCollector: starting")

        try:
            db = get_db()

            # Find signals that have been executed but not yet tracked
            # (confirmed or executed signals with entry_price)
            signals = (
                db.table("signals")
                .select("*")
                .in_("status", ["confirmed", "trade", "executed", "closed"])
                .not_.is_("entry_price", "null")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )

            if not signals.data:
                logger.info("SignalOutcomeCollector: no signals to track")
                return results

            # Check which signals already have outcomes
            signal_ids = [s["id"] for s in signals.data]
            existing = (
                db.table("signal_outcomes")
                .select("signal_id")
                .in_("signal_id", signal_ids)
                .execute()
            )
            tracked_ids = {r["signal_id"] for r in (existing.data or [])}

            for signal in signals.data:
                if signal["id"] in tracked_ids:
                    continue

                try:
                    await self._track_signal(signal)
                    results["processed"] += 1
                except Exception as e:
                    logger.error(f"Error tracking signal {signal['id']}: {e}")
                    results["errors"] += 1

        except Exception as e:
            logger.error(f"SignalOutcomeCollector error: {e}")

        logger.info(f"SignalOutcomeCollector: done. {results}")
        return results

    async def _track_signal(self, signal: dict):
        """Track a single signal's outcome."""
        ticker = signal["ticker"]
        entry_date_str = signal.get("confirmed_at") or signal["created_at"]
        entry_price = float(signal["entry_price"])

        # Parse entry date
        if isinstance(entry_date_str, str):
            entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
        else:
            entry_date = entry_date_str

        # Fetch historical data from entry date via Alpha Vantage
        av = get_av_client()
        start_str = (entry_date - timedelta(days=1)).strftime("%Y-%m-%d")
        end_str = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        hist = await av.get_daily_history_range(ticker, start_str, end_str)

        if hist is None or hist.empty:
            return

        closes = hist["Close"]
        days_available = len(closes)

        # Calculate returns at different horizons
        price_1d = float(closes.iloc[min(1, days_available - 1)]) if days_available > 1 else None
        price_5d = float(closes.iloc[min(5, days_available - 1)]) if days_available > 5 else None
        price_20d = float(closes.iloc[min(20, days_available - 1)]) if days_available > 20 else None

        return_1d = ((price_1d / entry_price) - 1) if price_1d else None
        return_5d = ((price_5d / entry_price) - 1) if price_5d else None
        return_20d = ((price_20d / entry_price) - 1) if price_20d else None

        # Save to signal_outcomes table
        db = get_db()
        outcome_data = {
            "signal_id": signal["id"],
            "ticker": ticker,
            "direction": signal["direction"],
            "entry_price": entry_price,
            "entry_date": entry_date.isoformat(),
            "price_1d": price_1d,
            "price_5d": price_5d,
            "price_20d": price_20d,
            "return_1d": return_1d,
            "return_5d": return_5d,
            "return_20d": return_20d,
        }
        db.table("signal_outcomes").insert(outcome_data).execute()

        # Generate natural language summary and add to knowledge base
        direction_cn = "做多" if signal["direction"] == "long" else "做空"
        parts = [
            f"{entry_date.strftime('%Y-%m-%d')} {ticker} {direction_cn}信号：",
            f"入场价${entry_price:.2f}",
        ]
        if return_1d is not None:
            parts.append(f"1天后${price_1d:.2f}({return_1d:+.1%})")
        if return_5d is not None:
            parts.append(f"5天后${price_5d:.2f}({return_5d:+.1%})")
        if return_20d is not None:
            parts.append(f"20天后${price_20d:.2f}({return_20d:+.1%})")

        content = "，".join(parts) + "。"

        ks = get_knowledge_service()
        await ks.add_knowledge(
            content=content,
            source_type="auto_signal_result",
            category="trade_result",
            tickers=[ticker],
            tags=["signal_outcome", signal["direction"]],
            relevance_date=entry_date.strftime("%Y-%m-%d"),
            metadata={
                "signal_id": signal["id"],
                "return_1d": return_1d,
                "return_5d": return_5d,
                "return_20d": return_20d,
            },
        )


# ============================================================
# 2. News Outcome Collector
# ============================================================

class NewsOutcomeCollector:
    """
    Correlates classified news events with subsequent price movements.
    Builds statistics: "FDA_Approval events average +12.3% on day 1".
    """

    async def run(self) -> dict:
        """Main entry point. Called by scheduler daily."""
        results = {"processed": 0, "errors": 0}
        logger.info("NewsOutcomeCollector: starting")

        try:
            db = get_db()

            # Get AI-classified events from the last 30 days
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            ai_events = (
                db.table("ai_events")
                .select("*, events!inner(ticker, title, published_at)")
                .eq("is_valid_event", True)
                .gte("created_at", cutoff)
                .limit(50)
                .execute()
            )

            if not ai_events.data:
                logger.info("NewsOutcomeCollector: no recent events")
                return results

            # Group by event_type and compute stats
            type_stats: Dict[str, list] = {}
            av = get_av_client()

            for event in ai_events.data:
                ticker = event.get("ticker") or (
                    event.get("events", {}).get("ticker")
                )
                if not ticker:
                    continue

                event_type = event["event_type"]
                published = event.get("events", {}).get("published_at")
                if not published:
                    continue

                try:
                    # Fetch 7 days of data after event via Alpha Vantage
                    pub_date = datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    )
                    start_str = pub_date.strftime("%Y-%m-%d")
                    end_str = (pub_date + timedelta(days=7)).strftime("%Y-%m-%d")
                    hist = await av.get_daily_history_range(ticker, start_str, end_str)

                    if hist is None or hist.empty or len(hist) < 2:
                        continue

                    closes = hist["Close"]
                    day0 = float(closes.iloc[0])
                    day1 = float(closes.iloc[min(1, len(closes) - 1)])

                    return_1d = (day1 / day0) - 1

                    if event_type not in type_stats:
                        type_stats[event_type] = []
                    type_stats[event_type].append(return_1d)

                    results["processed"] += 1

                except Exception as e:
                    logger.error(f"NewsOutcome error for {ticker}: {e}")
                    results["errors"] += 1

            # Generate summary statistics per event type
            ks = get_knowledge_service()
            for event_type, returns in type_stats.items():
                if len(returns) < 2:
                    continue

                avg_return = sum(returns) / len(returns)
                win_rate = sum(1 for r in returns if r > 0) / len(returns)

                content = (
                    f"{event_type}事件统计（最近{len(returns)}次）："
                    f"平均1日涨幅{avg_return:+.1%}，"
                    f"胜率{win_rate:.0%}。"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_news_outcome",
                    category="news_analysis",
                    tags=["event_stats", event_type.lower()],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "event_type": event_type,
                        "sample_count": len(returns),
                        "avg_return_1d": avg_return,
                        "win_rate": win_rate,
                    },
                    # Expire after 30 days (will be refreshed)
                    expires_at=(
                        datetime.utcnow() + timedelta(days=30)
                    ).isoformat(),
                )

        except Exception as e:
            logger.error(f"NewsOutcomeCollector error: {e}")

        logger.info(f"NewsOutcomeCollector: done. {results}")
        return results


# ============================================================
# 3. Pattern Statistics Collector
# ============================================================

class PatternStatCollector:
    """
    Scans watchlist stocks for common technical patterns and records
    their subsequent performance statistics.
    Patterns: MA20 breakout with volume, MA50 breakdown, etc.
    """

    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        """Main entry point. Called by scheduler weekly."""
        results = {"patterns_found": 0, "errors": 0}
        logger.info("PatternStatCollector: starting")

        if not tickers:
            # Use a representative set of liquid tickers
            tickers = [
                "SPY", "QQQ", "IWM", "XLK", "XLE", "XLV",
                "SOXX", "GLD", "TLT",
            ]

        try:
            # Download 6 months of history for all tickers via Alpha Vantage
            av = get_av_client()
            all_data = await av.batch_get_daily_history(tickers, days=180)

            if not all_data:
                return results

            pattern_stats = {
                "ma20_breakout_volume": [],  # Close > MA20, volume > avg
                "ma50_breakdown": [],        # Close < MA50
            }

            for ticker in tickers:
                try:
                    df = all_data.get(ticker)
                    if df is None or df.empty or len(df) < 55:
                        continue

                    closes = df["Close"]
                    volumes = df["Volume"]

                    ma20 = closes.rolling(20).mean()
                    ma50 = closes.rolling(50).mean()
                    avg_vol = volumes.rolling(20).mean()

                    # Scan for MA20 breakout with volume
                    for i in range(51, len(df) - 5):
                        # Pattern: previous day below MA20, today above, with volume
                        if (
                            closes.iloc[i - 1] < ma20.iloc[i - 1]
                            and closes.iloc[i] > ma20.iloc[i]
                            and volumes.iloc[i] > avg_vol.iloc[i] * 1.5
                        ):
                            # Measure 5-day forward return
                            if i + 5 < len(df):
                                fwd_return = (
                                    closes.iloc[i + 5] / closes.iloc[i]
                                ) - 1
                                pattern_stats["ma20_breakout_volume"].append(
                                    fwd_return
                                )

                        # Pattern: breakdown below MA50
                        if (
                            closes.iloc[i - 1] > ma50.iloc[i - 1]
                            and closes.iloc[i] < ma50.iloc[i]
                        ):
                            if i + 5 < len(df):
                                fwd_return = (
                                    closes.iloc[i + 5] / closes.iloc[i]
                                ) - 1
                                pattern_stats["ma50_breakdown"].append(fwd_return)

                except Exception as e:
                    logger.error(f"Pattern scan error for {ticker}: {e}")
                    results["errors"] += 1

            # Generate and store statistics
            ks = get_knowledge_service()

            for pattern_name, returns in pattern_stats.items():
                if len(returns) < 5:
                    continue

                avg = sum(returns) / len(returns)
                win_rate = sum(1 for r in returns if r > 0) / len(returns)
                results["patterns_found"] += len(returns)

                pattern_label = {
                    "ma20_breakout_volume": "放量突破MA20",
                    "ma50_breakdown": "跌破MA50",
                }.get(pattern_name, pattern_name)

                content = (
                    f"技术形态统计 — {pattern_label}："
                    f"过去6个月在{len(tickers)}只标的中出现{len(returns)}次，"
                    f"5日后平均涨幅{avg:+.1%}，胜率{win_rate:.0%}。"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_pattern_stat",
                    category="technical",
                    tags=["pattern_stat", pattern_name],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "pattern": pattern_name,
                        "sample_count": len(returns),
                        "avg_5d_return": avg,
                        "win_rate": win_rate,
                        "tickers_scanned": tickers,
                    },
                    expires_at=(
                        datetime.utcnow() + timedelta(days=14)
                    ).isoformat(),
                )

        except Exception as e:
            logger.error(f"PatternStatCollector error: {e}")

        logger.info(f"PatternStatCollector: done. {results}")
        return results


# ============================================================
# 4. Sector Rotation Collector
# ============================================================

class SectorRotationCollector:
    """
    Records weekly ETF/sector momentum rankings.
    Tracks rank changes to detect sector rotation trends.
    """

    SECTOR_ETFS = {
        "XLK": "科技", "XLF": "金融", "XLE": "能源", "XLV": "医疗",
        "XLI": "工业", "XLC": "通讯", "SOXX": "半导体", "IBB": "生物科技",
        "QQQ": "纳斯达克", "IWM": "小盘股", "VWO": "新兴市场",
        "TLT": "国债", "GLD": "黄金",
    }

    async def run(self) -> dict:
        """Main entry point. Called by scheduler weekly."""
        results = {"sectors_tracked": 0, "errors": 0}
        logger.info("SectorRotationCollector: starting")

        try:
            tickers = list(self.SECTOR_ETFS.keys())

            # Fetch 1 month of history via Alpha Vantage
            av = get_av_client()
            all_data = await av.batch_get_daily_history(tickers, days=30)

            if not all_data:
                return results

            # Calculate 1-week and 1-month returns for each sector ETF
            scores = {}
            for ticker in tickers:
                try:
                    df = all_data.get(ticker)
                    if df is None or df.empty or len(df) < 5:
                        continue

                    closes = df["Close"]
                    return_1w = (closes.iloc[-1] / closes.iloc[-5]) - 1 if len(closes) >= 5 else 0
                    return_1m = (closes.iloc[-1] / closes.iloc[0]) - 1

                    scores[ticker] = {
                        "name": self.SECTOR_ETFS[ticker],
                        "return_1w": float(return_1w),
                        "return_1m": float(return_1m),
                        "score": float(return_1w * 0.4 + return_1m * 0.6),
                    }
                    results["sectors_tracked"] += 1

                except Exception as e:
                    logger.error(f"Sector rotation error for {ticker}: {e}")
                    results["errors"] += 1

            if not scores:
                return results

            # Rank by score
            ranked = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

            # Build summary text
            lines = [f"本周板块动量排名（{date.today().isoformat()}）："]
            for i, (ticker, info) in enumerate(ranked, 1):
                lines.append(
                    f"{i}. {info['name']}({ticker}) "
                    f"1周{info['return_1w']:+.1%} "
                    f"1月{info['return_1m']:+.1%} "
                    f"评分{info['score']:.2f}"
                )

            content = "\n".join(lines)

            # Get last week's ranking for comparison
            ks = get_knowledge_service()
            prev_entries = await ks.search(
                query="板块动量排名",
                top_k=1,
                source_type="auto_sector_rotation",
            )

            # Detect notable changes
            if prev_entries:
                prev_meta = prev_entries[0].get("metadata") or {}
                if isinstance(prev_meta, str):
                    import json
                    prev_meta = json.loads(prev_meta)
                prev_ranking = prev_meta.get("ranking", {})

                changes = []
                for i, (ticker, info) in enumerate(ranked, 1):
                    prev_rank = prev_ranking.get(ticker)
                    if prev_rank and abs(prev_rank - i) >= 3:
                        direction = "升至" if i < prev_rank else "降至"
                        changes.append(
                            f"{info['name']}({ticker})从第{prev_rank}{direction}第{i}"
                        )

                if changes:
                    content += "\n\n显著变化：" + "；".join(changes)

            # Store ranking metadata
            ranking_meta = {ticker: i for i, (ticker, _) in enumerate(ranked, 1)}

            await ks.add_knowledge(
                content=content,
                source_type="auto_sector_rotation",
                category="sector",
                tickers=[t for t, _ in ranked[:5]],
                tags=["sector_rotation", "weekly_ranking"],
                relevance_date=date.today().isoformat(),
                metadata={
                    "ranking": ranking_meta,
                    "scores": {t: s["score"] for t, s in scores.items()},
                },
                expires_at=(
                    datetime.utcnow() + timedelta(days=14)
                ).isoformat(),
            )

        except Exception as e:
            logger.error(f"SectorRotationCollector error: {e}")

        logger.info(f"SectorRotationCollector: done. {results}")
        return results


# ============================================================
# 5. AI Sentiment Collector
# ============================================================

class AISentimentCollector:
    """
    Aggregates news sentiment per ticker using Alpha Vantage NEWS_SENTIMENT API
    + DeepSeek AI summary. Stores results as 'auto_ai_sentiment' in knowledge_base
    for use by get_rag_score_adjustment() in rotation scoring.

    Pipeline:
    1. Fetch recent news sentiment from Alpha Vantage (per ticker batch)
    2. Aggregate sentiment scores from AV's NLP
    3. Optionally enrich with DeepSeek analysis for top movers
    4. Store normalized score [-1, +1] + confidence [0, 1] in knowledge_base
    """

    # Fallback list when no rotation snapshot is available
    TICKERS_TO_SCORE = [
        # Key ETFs
        "SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLC",
        "SOXX", "IBB", "TLT", "GLD",
        # Top mid-cap growth + AI
        "CRWD", "NET", "DDOG", "SNOW", "ZS", "MDB", "PANW",
        "PLTR", "BILL", "HUBS", "VEEV", "CELH", "TOST",
        # Chinese ADRs + hot names
        "PDD", "BABA", "NIO", "LI", "FUTU",
        "SOFI", "HOOD", "AFRM", "RKLB",
    ]

    async def _get_top_tickers_from_snapshot(self, limit: int = 100) -> List[str]:
        """Pull top-scored tickers from the latest rotation snapshot.
        Falls back to empty list if snapshot not available."""
        try:
            db = get_db()
            result = (
                db.table("rotation_snapshots")
                .select("scores")
                .order("snapshot_date", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return []
            scores = result.data[0].get("scores") or []
            top = sorted(scores, key=lambda s: s.get("score", 0), reverse=True)[:limit]
            return [s["ticker"] for s in top if s.get("ticker")]
        except Exception as e:
            logger.warning(f"AISentiment: could not fetch snapshot tickers: {e}")
            return []

    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        """Main entry point. Called by scheduler daily after market close."""
        results = {"scored": 0, "errors": 0, "no_data": 0}
        logger.info("AISentimentCollector: starting")

        if tickers:
            target_tickers = tickers
        else:
            # Prefer dynamic top-100 from latest rotation snapshot
            dynamic = await self._get_top_tickers_from_snapshot(limit=100)
            if dynamic:
                logger.info(f"AISentiment: using {len(dynamic)} tickers from rotation snapshot")
                target_tickers = dynamic
            else:
                logger.info("AISentiment: no snapshot found, using fallback list")
                target_tickers = self.TICKERS_TO_SCORE
        av = get_av_client()
        ks = get_knowledge_service()

        # Query one ticker at a time — AV's tickers param is AND filter,
        # so multi-ticker queries return 0 articles (must mention ALL tickers).
        all_ticker_scores: Dict[str, List[float]] = {}

        for idx, ticker in enumerate(target_tickers):
            try:
                articles = await av.get_news_sentiment(
                    tickers=[ticker], limit=30
                )
                if not articles:
                    results["no_data"] += 1
                    continue

                # Aggregate sentiment from articles mentioning this ticker
                for article in articles:
                    for ts in article.get("ticker_sentiments", []):
                        if ts["ticker"] != ticker:
                            continue
                        relevance = ts.get("relevance_score", 0)
                        sentiment = ts.get("sentiment_score", 0)
                        # Weight by relevance
                        if relevance >= 0.1:
                            if ticker not in all_ticker_scores:
                                all_ticker_scores[ticker] = []
                            all_ticker_scores[ticker].append(
                                sentiment * relevance
                            )

                if (idx + 1) % 10 == 0:
                    logger.info(f"AISentiment progress: {idx + 1}/{len(target_tickers)}")

            except Exception as e:
                logger.error(f"AISentiment error for {ticker}: {e}")
                results["errors"] += 1

        # Compute and store aggregated sentiment per ticker
        for ticker in target_tickers:
            try:
                scores = all_ticker_scores.get(ticker, [])

                if not scores:
                    results["no_data"] += 1
                    continue

                # Weighted average sentiment
                avg_sentiment = sum(scores) / len(scores)
                # Confidence based on sample size (more articles = higher)
                confidence = min(len(scores) / 10.0, 1.0)
                # Clamp to [-1, +1]
                avg_sentiment = max(-1.0, min(1.0, avg_sentiment))

                # Determine label
                if avg_sentiment > 0.15:
                    label = "看多"
                elif avg_sentiment < -0.15:
                    label = "看空"
                else:
                    label = "中性"

                content = (
                    f"{ticker} AI情绪评分: {avg_sentiment:+.3f} ({label}), "
                    f"基于{len(scores)}条新闻, "
                    f"置信度{confidence:.1%}. "
                    f"日期: {date.today().isoformat()}"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_ai_sentiment",
                    category="sentiment",
                    tickers=[ticker],
                    tags=["ai_sentiment", label],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "score": avg_sentiment,
                        "confidence": confidence,
                        "article_count": len(scores),
                        "label": label,
                        "date": date.today().isoformat(),
                    },
                    expires_at=(
                        datetime.utcnow() + timedelta(days=3)
                    ).isoformat(),
                )
                results["scored"] += 1

                logger.info(
                    f"  {ticker}: sentiment={avg_sentiment:+.3f} "
                    f"conf={confidence:.1%} ({len(scores)} articles) → {label}"
                )

            except Exception as e:
                logger.error(f"AISentiment store error for {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"AISentimentCollector: done. {results}")
        return results


# ============================================================
# 6. Fundamental Data Collector (AV OVERVIEW)
# ============================================================

class FundamentalDataCollector:
    """
    【FMP 高级版重写】批量获取公司概况 + TTM 比率。
    覆盖完整动态选股池（~1578只），高并发50x，约30秒完成全量。
    Runs weekly (fundamentals change slowly, 7-day cache TTL).
    """
    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        from app.services.fmp_client import batch_get_profiles, batch_get_ratios
        results = {"collected": 0, "errors": 0, "skipped": 0}
        logger.info("FundamentalDataCollector (FMP): starting")

        target = tickers or _get_dynamic_universe_tickers()
        ks = get_knowledge_service()

        # 批量并发拉取（FMP 高级版 50 并发）
        profiles = await batch_get_profiles(target, concurrency=50)
        ratios   = await batch_get_ratios(target, concurrency=50)

        for ticker in target:
            prof = profiles.get(ticker)
            rat  = ratios.get(ticker)

            if not prof and not rat:
                results["skipped"] += 1
                continue

            try:
                pe  = rat.get("pe_ratio_ttm")  if rat else prof.get("pe_ratio") if prof else None
                peg = rat.get("peg_ratio_ttm") if rat else None
                roe = rat.get("roe_ttm")       if rat else None
                pm  = rat.get("profit_margin_ttm") if rat else None
                gm  = rat.get("gross_margin_ttm")  if rat else None
                sector   = prof.get("sector", "N/A")   if prof else "N/A"
                industry = prof.get("industry", "N/A") if prof else "N/A"

                def _fmt(v, pct=False):
                    if v is None: return "N/A"
                    return f"{v:.1%}" if pct else f"{v:.2f}"

                content = (
                    f"{ticker} 基本面: PE={_fmt(pe)} "
                    f"PEG={_fmt(peg)} "
                    f"ROE={_fmt(roe, pct=True)} "
                    f"净利率={_fmt(pm, pct=True)} "
                    f"毛利率={_fmt(gm, pct=True)} "
                    f"行业={sector}/{industry} "
                    f"日期: {date.today().isoformat()}"
                )

                metadata = {}
                if prof: metadata.update(prof)
                if rat:  metadata.update(rat)
                metadata["date"] = date.today().isoformat()

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_fundamental",
                    category="fundamental",
                    tickers=[ticker],
                    tags=["fundamental", "overview"],
                    relevance_date=date.today().isoformat(),
                    metadata=metadata,
                    expires_at=(datetime.utcnow() + timedelta(days=90)).isoformat(),
                )
                results["collected"] += 1

            except Exception as e:
                logger.error(f"Fundamental write error {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"FundamentalDataCollector (FMP): done. {results}")
        return results


# ============================================================
# 7. Earnings Calendar Collector (AV EARNINGS)
# ============================================================

class EarningsCalendarCollector:
    """
    【FMP 高级版重写】批量获取历史季度 EPS 数据。
    覆盖完整动态选股池（~1578只），高并发50x。
    Tracks beat rate, surprise magnitude, upcoming earnings dates.
    """
    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        from app.services.fmp_client import batch_get_earnings
        results = {"collected": 0, "errors": 0, "upcoming": 0}
        logger.info("EarningsCalendarCollector (FMP): starting")

        target = tickers or _get_dynamic_universe_tickers()
        ks = get_knowledge_service()

        # 批量并发拉取
        all_earnings = await batch_get_earnings(target, concurrency=50)

        for ticker, earnings in all_earnings.items():
            try:
                quarters = earnings.get("quarterly", [])
                if not quarters:
                    continue

                # Compute beat rate over last 4 quarters
                beats = sum(1 for q in quarters[:4]
                            if q.get("reported_eps") is not None
                            and q.get("estimated_eps") is not None
                            and q["reported_eps"] > q["estimated_eps"])
                total = sum(1 for q in quarters[:4]
                            if q.get("reported_eps") is not None
                            and q.get("estimated_eps") is not None)
                beat_rate = beats / total if total > 0 else 0

                # Latest actual quarter (skip future entries)
                actual_quarters = [q for q in quarters if not q.get("is_future")]
                latest = actual_quarters[0] if actual_quarters else {}
                surprise = latest.get("surprise_pct", 0) or 0

                # Check for upcoming earnings
                upcoming = False
                for q in quarters:
                    if q.get("is_future") and q.get("date", "") > date.today().isoformat():
                        upcoming = True
                        results["upcoming"] += 1
                        break

                label = "beat" if surprise > 0 else "miss" if surprise < 0 else "inline"
                content = (
                    f"{ticker} 盈利: 最新EPS={latest.get('reported_eps','N/A')} "
                    f"vs预期={latest.get('estimated_eps','N/A')} "
                    f"惊喜={surprise:+.1f}% ({label}) "
                    f"4季beat率={beat_rate:.0%} "
                    f"{'即将发财报!' if upcoming else ''} "
                    f"日期: {date.today().isoformat()}"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_earnings_cal",
                    category="earnings",
                    tickers=[ticker],
                    tags=["earnings", label],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "beat_rate": beat_rate,
                        "latest_surprise_pct": surprise,
                        "upcoming_earnings": upcoming,
                        "quarters": actual_quarters[:4],
                        "date": date.today().isoformat(),
                    },
                    expires_at=(datetime.utcnow() + timedelta(days=7)).isoformat(),
                )
                results["collected"] += 1

            except Exception as e:
                logger.error(f"Earnings write error {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"EarningsCalendarCollector (FMP): done. {results}")
        return results


# ============================================================
# 8. ETF Flow Collector (pseudo-flow from OHLCV, no extra API)
# ============================================================

class ETFFlowCollector:
    """
    Estimates fund flow using price_change * volume (Money Flow Index approach).
    No additional API calls needed — uses existing OHLCV data.
    """

    TRACK_TICKERS = [
        "SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI",
        "XLC", "SOXX", "IBB", "ARKK", "VWO", "EFA",
        "TLT", "GLD", "SHY",
    ]

    async def run(self) -> dict:
        results = {"collected": 0, "errors": 0}
        logger.info("ETFFlowCollector: starting")

        av = get_av_client()
        ks = get_knowledge_service()

        for ticker in self.TRACK_TICKERS:
            try:
                data = await av.get_history_arrays(ticker, days=30)
                if data is None or len(data["close"]) < 21:
                    continue

                closes = data["close"]
                volumes = data["volume"]

                # Compute money flow: sum(price_change * volume) over windows
                price_changes = (closes[1:] - closes[:-1]) / closes[:-1]
                money_flow = price_changes * volumes[1:]

                flow_5d = float(sum(money_flow[-5:])) if len(money_flow) >= 5 else 0
                flow_20d = float(sum(money_flow[-20:])) if len(money_flow) >= 20 else 0

                # Volume ratio (today vs 20-day avg)
                avg_vol_20 = float(volumes[-20:].mean()) if len(volumes) >= 20 else 1
                vol_ratio = float(volumes[-1]) / avg_vol_20 if avg_vol_20 > 0 else 1.0

                trend = "inflow" if flow_5d > 0 else "outflow"

                content = (
                    f"{ticker} 资金流: 5日={'净流入' if flow_5d > 0 else '净流出'} "
                    f"20日={'净流入' if flow_20d > 0 else '净流出'} "
                    f"量比={vol_ratio:.2f}x "
                    f"日期: {date.today().isoformat()}"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_etf_flow",
                    category="flow",
                    tickers=[ticker],
                    tags=["etf_flow", trend],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "flow_5d": flow_5d,
                        "flow_20d": flow_20d,
                        "vol_ratio": vol_ratio,
                        "trend": trend,
                        "date": date.today().isoformat(),
                    },
                    expires_at=(datetime.utcnow() + timedelta(days=3)).isoformat(),
                )
                results["collected"] += 1

            except Exception as e:
                logger.error(f"ETFFlow error {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"ETFFlowCollector: done. {results}")
        return results


# ============================================================
# 9. Income Growth Collector (AV INCOME_STATEMENT)
# ============================================================

class IncomeGrowthCollector:
    """
    【FMP 高级版重写】批量获取季度收入表，追踪营收/利润趋势。
    覆盖完整动态选股池（~1578只），高并发50x。
    """
    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        from app.services.fmp_client import batch_get_income
        results = {"collected": 0, "errors": 0}
        logger.info("IncomeGrowthCollector (FMP): starting")

        target = tickers or _get_dynamic_universe_tickers()
        ks = get_knowledge_service()

        all_income = await batch_get_income(target, concurrency=50)

        for ticker, income in all_income.items():
            try:
                quarters = income.get("quarterly", [])
                if len(quarters) < 2:
                    continue

                revenues = [q.get("revenue") for q in quarters[:4] if q.get("revenue")]
                rev_trend = "growing" if len(revenues) >= 2 and revenues[0] > revenues[1] else "flat_or_declining"

                consecutive_growth = 0
                for i in range(len(revenues) - 1):
                    if revenues[i] > revenues[i + 1]:
                        consecutive_growth += 1
                    else:
                        break

                latest_q = quarters[0]
                rev = latest_q.get("revenue") or 0
                gm  = latest_q.get("gross_margin") or 0
                net = latest_q.get("net_income")

                content = (
                    f"{ticker} 收入趋势: Q收入=${rev:,.0f} "
                    f"毛利率={gm:.1%} "
                    f"连续{consecutive_growth}季增长 "
                    f"净利=${net:,.0f} " if net is not None else
                    f"{ticker} 收入趋势: Q收入=${rev:,.0f} "
                    f"毛利率={gm:.1%} "
                    f"连续{consecutive_growth}季增长 "
                    f"日期: {date.today().isoformat()}"
                )
                # 重新组合（避免 f-string 中三元复杂嵌套）
                content = (
                    f"{ticker} 收入趋势: Q收入=${rev:,.0f} "
                    f"毛利率={gm:.1%} "
                    f"连续{consecutive_growth}季增长 "
                    + (f"净利=${net:,.0f} " if net is not None else "")
                    + f"日期: {date.today().isoformat()}"
                )

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_income_growth",
                    category="fundamental",
                    tickers=[ticker],
                    tags=["income", rev_trend],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "quarterly": quarters[:4],
                        "consecutive_growth": consecutive_growth,
                        "gross_margin": gm,
                        "rev_trend": rev_trend,
                        "date": date.today().isoformat(),
                    },
                    expires_at=(datetime.utcnow() + timedelta(days=90)).isoformat(),
                )
                results["collected"] += 1

            except Exception as e:
                logger.error(f"Income write error {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"IncomeGrowthCollector (FMP): done. {results}")
        return results


# ============================================================
# 10. Cash Flow Health Collector (AV CASH_FLOW)
# ============================================================

class CashFlowHealthCollector:
    """
    【FMP 高级版重写】批量获取季度现金流，评估财务健康度。
    覆盖完整动态选股池（~1578只），高并发50x。
    """
    async def run(self, tickers: Optional[List[str]] = None) -> dict:
        from app.services.fmp_client import batch_get_cashflow
        results = {"collected": 0, "errors": 0}
        logger.info("CashFlowHealthCollector (FMP): starting")

        target = tickers or _get_dynamic_universe_tickers()
        ks = get_knowledge_service()

        all_cf = await batch_get_cashflow(target, concurrency=50)

        for ticker, cf in all_cf.items():
            try:
                quarters = cf.get("quarterly", [])
                if not quarters:
                    continue

                latest = quarters[0]
                fcf   = latest.get("free_cashflow")
                op_cf = latest.get("operating_cashflow")

                health = "healthy" if fcf and fcf > 0 else "warning" if op_cf and op_cf > 0 else "critical"

                if op_cf is not None and fcf is not None:
                    content = (
                        f"{ticker} 现金流: 营运CF=${op_cf:,.0f} "
                        f"FCF=${fcf:,.0f} "
                        f"健康度={health} "
                        f"日期: {date.today().isoformat()}"
                    )
                else:
                    content = f"{ticker} 现金流: 数据不完整 日期: {date.today().isoformat()}"

                await ks.add_knowledge(
                    content=content,
                    source_type="auto_cashflow",
                    category="fundamental",
                    tickers=[ticker],
                    tags=["cashflow", health],
                    relevance_date=date.today().isoformat(),
                    metadata={
                        "quarterly": quarters[:4],
                        "latest_fcf": fcf,
                        "latest_op_cf": op_cf,
                        "health": health,
                        "date": date.today().isoformat(),
                    },
                    expires_at=(datetime.utcnow() + timedelta(days=90)).isoformat(),
                )
                results["collected"] += 1

            except Exception as e:
                logger.error(f"CashFlow write error {ticker}: {e}")
                results["errors"] += 1

        logger.info(f"CashFlowHealthCollector (FMP): done. {results}")
        return results


# ============================================================
# 11. Earnings Report Collector (SEC EDGAR — placeholder)
# ============================================================

class EarningsReportCollector:
    """
    SEC EDGAR 财报全文分析（未来功能）。
    当前版本：无操作 stub，防止 scheduler 导入报错。
    TODO: 接入 SEC EDGAR XBRL API，解析 10-Q/10-K 关键段落并写入 RAG。
    """
    async def run(self) -> dict:
        logger.info("EarningsReportCollector: stub — no-op (SEC EDGAR integration pending)")
        return {"status": "stub", "collected": 0}


# ============================================================
# 12. Institutional Holdings Collector (13F — placeholder)
# ============================================================

class InstitutionalHoldingsCollector:
    """
    13F 机构持仓变化追踪（未来功能）。
    当前版本：无操作 stub，防止 scheduler 导入报错。
    TODO: 接入 FMP /stable/institutional-ownership 或 SEC EDGAR 13F，
          追踪 Berkshire/Soros 等大机构的季度仓位变化。
    """
    async def run(self) -> dict:
        logger.info("InstitutionalHoldingsCollector: stub — no-op (13F integration pending)")
        return {"status": "stub", "collected": 0}


# ============================================================
# 13. Sector Performance Collector (local ETF proxy)
# ============================================================

class SectorPerformanceCollector:
    """
    Computes sector performance using ETF proxies.
    AV's SECTOR endpoint is deprecated, so we calculate locally.
    """

    SECTOR_ETFS = {
        "Technology": "XLK",
        "Financials": "XLF",
        "Energy": "XLE",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Communication Services": "XLC",
        "Semiconductors": "SOXX",
        "Biotech": "IBB",
    }

    async def run(self) -> dict:
        results = {"collected": 0, "errors": 0}
        logger.info("SectorPerformanceCollector: starting")

        av = get_av_client()
        ks = get_knowledge_service()

        sector_returns = {}
        for sector, etf in self.SECTOR_ETFS.items():
            try:
                data = await av.get_history_arrays(etf, days=30)
                if data is None or len(data["close"]) < 22:
                    continue

                closes = data["close"]
                ret_1w = float((closes[-1] / closes[-6]) - 1) if len(closes) > 6 else 0
                ret_1m = float((closes[-1] / closes[-22]) - 1) if len(closes) > 22 else 0

                sector_returns[sector] = {
                    "etf": etf,
                    "ret_1w": round(ret_1w, 4),
                    "ret_1m": round(ret_1m, 4),
                }

            except Exception as e:
                logger.error(f"SectorPerf error {sector}/{etf}: {e}")
                results["errors"] += 1

        if sector_returns:
            # Rank sectors by 1-month return
            ranked = sorted(sector_returns.items(), key=lambda x: x[1]["ret_1m"], reverse=True)
            top_sectors = [f"{s}({d['ret_1m']:+.1%})" for s, d in ranked[:3]]
            bottom_sectors = [f"{s}({d['ret_1m']:+.1%})" for s, d in ranked[-3:]]

            content = (
                f"板块表现: 领涨={', '.join(top_sectors)} "
                f"落后={', '.join(bottom_sectors)} "
                f"日期: {date.today().isoformat()}"
            )

            await ks.add_knowledge(
                content=content,
                source_type="auto_sector_perf",
                category="sector",
                tickers=[d["etf"] for d in sector_returns.values()],
                tags=["sector_performance"],
                relevance_date=date.today().isoformat(),
                metadata={
                    "sectors": sector_returns,
                    "date": date.today().isoformat(),
                },
                expires_at=(datetime.utcnow() + timedelta(days=3)).isoformat(),
            )
            results["collected"] = len(sector_returns)

        logger.info(f"SectorPerformanceCollector: done. {results}")
        return results


# ============================================================
# Convenience runner for all collectors
# ============================================================

async def run_all_collectors() -> dict:
    """Run all collectors. Used for manual trigger endpoint."""
    results = {}

    # Core collectors (daily)
    results["signal_outcome"] = await SignalOutcomeCollector().run()
    results["news_outcome"] = await NewsOutcomeCollector().run()
    results["pattern_stat"] = await PatternStatCollector().run()
    results["sector_rotation"] = await SectorRotationCollector().run()
    results["ai_sentiment"] = await AISentimentCollector().run()
    results["etf_flow"] = await ETFFlowCollector().run()
    results["sector_perf"] = await SectorPerformanceCollector().run()

    # FMP fundamental collectors (weekly, covers full dynamic pool)
    results["fundamental"] = await FundamentalDataCollector().run()
    results["earnings_cal"] = await EarningsCalendarCollector().run()
    results["income_growth"] = await IncomeGrowthCollector().run()
    results["cashflow_health"] = await CashFlowHealthCollector().run()

    # Stubs (future integrations)
    results["earnings_report"] = await EarningsReportCollector().run()
    results["institutional"] = await InstitutionalHoldingsCollector().run()

    logger.info(f"All collectors completed: {results}")
    return results
