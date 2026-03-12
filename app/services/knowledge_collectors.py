"""
StockQueen V2.1 - Knowledge Collectors
8 automated data collectors that populate the RAG knowledge base.

Original 4:
1. SignalOutcomeCollector       - tracks signal P&L at 1d/5d/20d
2. NewsOutcomeCollector         - correlates news events with subsequent price moves
3. PatternStatCollector         - statistical summary of technical patterns
4. SectorRotationCollector      - records weekly sector/ETF ranking changes

V2.1 AI-enhanced 4:
5. EarningsReportCollector      - SEC EDGAR 10-Q/10-K/8-K → GPT analysis
6. AISentimentCollector         - holistic AI sentiment scoring per ticker
7. ETFFlowCollector             - daily ETF fund flow tracking
8. InstitutionalHoldingsCollector - 13F institutional holdings changes
"""

import logging
import asyncio
import json
import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta, date

import httpx
import yfinance as yf
import pandas as pd

from app.config import settings
from app.database import get_db
from app.services.knowledge_service import get_knowledge_service

# ============================================================
# SEC EDGAR shared utilities
# ============================================================

SEC_HEADERS = {
    "User-Agent": "StockQueen/2.0 (stockqueen@example.com)",
    "Accept-Encoding": "gzip, deflate",
}
SEC_BASE = "https://data.sec.gov"
SEC_EFTS = "https://efts.sec.gov/LATEST"
SEC_RATE_LIMIT = 0.12  # 120ms between requests (< 10 req/sec)

_CIK_CACHE: Dict[str, str] = {}


async def _get_cik_mapping() -> Dict[str, str]:
    """Load SEC ticker→CIK mapping (cached after first call)."""
    global _CIK_CACHE
    if _CIK_CACHE:
        return _CIK_CACHE

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=SEC_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        for entry in data.values():
            ticker = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                _CIK_CACHE[ticker] = cik

        logging.getLogger(__name__).info(
            f"SEC CIK mapping loaded: {len(_CIK_CACHE)} tickers"
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to load CIK mapping: {e}")

    return _CIK_CACHE

logger = logging.getLogger(__name__)


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

        # Fetch historical data from entry date
        loop = asyncio.get_event_loop()
        hist = await loop.run_in_executor(
            None,
            lambda: yf.download(
                ticker,
                start=(entry_date - timedelta(days=1)).strftime("%Y-%m-%d"),
                end=(datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
            ),
        )

        if hist.empty:
            return

        # Handle MultiIndex columns from yfinance
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

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
                    # Fetch 5 days of data after event
                    pub_date = datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    )
                    loop = asyncio.get_event_loop()
                    hist = await loop.run_in_executor(
                        None,
                        lambda t=ticker, d=pub_date: yf.download(
                            t,
                            start=d.strftime("%Y-%m-%d"),
                            end=(d + timedelta(days=7)).strftime("%Y-%m-%d"),
                            progress=False,
                        ),
                    )

                    if hist.empty or len(hist) < 2:
                        continue

                    if isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = hist.columns.get_level_values(0)

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
            # Download 6 months of history for all tickers
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    tickers, period="6mo", progress=False, group_by="ticker"
                ),
            )

            if data.empty:
                return results

            pattern_stats = {
                "ma20_breakout_volume": [],  # Close > MA20, volume > avg
                "ma50_breakdown": [],        # Close < MA50
            }

            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = data
                    else:
                        df = data[ticker].dropna()

                    if df.empty or len(df) < 55:
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

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    tickers, period="1mo", progress=False, group_by="ticker"
                ),
            )

            if data.empty:
                return results

            # Calculate 1-week and 1-month returns for each sector ETF
            scores = {}
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = data
                    else:
                        df = data[ticker].dropna()

                    if df.empty or len(df) < 5:
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
# 5. Earnings Report Collector (SEC EDGAR → GPT Analysis)
# ============================================================

class EarningsReportCollector:
    """
    Fetch recent 10-Q/10-K/8-K filings from SEC EDGAR for mid-cap stocks,
    extract financial data via XBRL, and use GPT-4o-mini to analyze.
    """

    FILING_TYPES = {"10-Q", "10-K", "8-K"}
    LOOKBACK_DAYS = 7  # check filings from last 7 days

    async def run(self) -> dict:
        results = {"processed": 0, "skipped": 0, "errors": 0}
        ks = get_knowledge_service()

        from app.config.rotation_watchlist import MIDCAP_STOCKS
        tickers = [s["ticker"] for s in MIDCAP_STOCKS]

        cik_map = await _get_cik_mapping()
        if not cik_map:
            logger.error("EarningsReportCollector: CIK mapping empty, aborting")
            return results

        cutoff = (date.today() - timedelta(days=self.LOOKBACK_DAYS)).isoformat()

        async with httpx.AsyncClient(timeout=30.0, headers=SEC_HEADERS) as client:
            for ticker in tickers:
                try:
                    cik = cik_map.get(ticker)
                    if not cik:
                        continue

                    # 1. Get recent filings
                    await asyncio.sleep(SEC_RATE_LIMIT)
                    resp = await client.get(
                        f"{SEC_BASE}/submissions/CIK{cik}.json"
                    )
                    if resp.status_code != 200:
                        continue

                    submissions = resp.json()
                    recent = submissions.get("filings", {}).get("recent", {})
                    forms = recent.get("form", [])
                    dates = recent.get("filingDate", [])
                    accessions = recent.get("accessionNumber", [])

                    new_filings = []
                    for i, (form, fdate, acc) in enumerate(
                        zip(forms, dates, accessions)
                    ):
                        if form in self.FILING_TYPES and fdate >= cutoff:
                            new_filings.append({
                                "form": form,
                                "date": fdate,
                                "accession": acc,
                            })

                    if not new_filings:
                        results["skipped"] += 1
                        continue

                    # 2. Check duplicates
                    existing = await ks.search_by_ticker(ticker, top_k=10)
                    existing_accessions = set()
                    for entry in existing:
                        meta = entry.get("metadata") or {}
                        if isinstance(meta, str):
                            try:
                                meta = json.loads(meta)
                            except Exception:
                                meta = {}
                        if meta.get("accession_number"):
                            existing_accessions.add(meta["accession_number"])

                    new_filings = [
                        f for f in new_filings
                        if f["accession"] not in existing_accessions
                    ]
                    if not new_filings:
                        results["skipped"] += 1
                        continue

                    # 3. Get XBRL financial facts
                    await asyncio.sleep(SEC_RATE_LIMIT)
                    facts_resp = await client.get(
                        f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
                    )
                    facts_text = ""
                    if facts_resp.status_code == 200:
                        facts = facts_resp.json()
                        facts_text = self._extract_key_facts(facts, ticker)

                    # 4. GPT analysis
                    for filing in new_filings[:3]:  # max 3 filings per ticker
                        analysis = await self._analyze_with_gpt(
                            ticker, filing, facts_text
                        )
                        if analysis:
                            await ks.add_knowledge(
                                content=analysis,
                                source_type="auto_earnings_report",
                                category="fundamental",
                                tickers=[ticker],
                                tags=["earnings", filing["form"].lower(),
                                      "sec_filing"],
                                relevance_date=filing["date"],
                                expires_at=(
                                    datetime.utcnow() + timedelta(days=90)
                                ).isoformat(),
                                metadata={
                                    "filing_type": filing["form"],
                                    "filing_date": filing["date"],
                                    "accession_number": filing["accession"],
                                    "cik": cik,
                                },
                            )
                            results["processed"] += 1

                except Exception as e:
                    logger.error(f"EarningsReportCollector error for {ticker}: {e}")
                    results["errors"] += 1

        logger.info(f"EarningsReportCollector: done. {results}")
        return results

    def _extract_key_facts(self, facts: dict, ticker: str) -> str:
        """Extract revenue, EPS, net income from XBRL companyfacts."""
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        lines = [f"[{ticker} SEC XBRL 财务数据]"]

        concepts = {
            "Revenues": "营收",
            "RevenueFromContractWithCustomerExcludingAssessedTax": "合同营收",
            "NetIncomeLoss": "净利润",
            "EarningsPerShareBasic": "基本EPS",
            "EarningsPerShareDiluted": "稀释EPS",
            "GrossProfit": "毛利润",
            "OperatingIncomeLoss": "营业利润",
        }

        for concept, label in concepts.items():
            data = us_gaap.get(concept, {})
            units = data.get("units", {})
            # Try USD first, then USD/shares for EPS
            values = units.get("USD", units.get("USD/shares", []))
            if values:
                recent = sorted(values, key=lambda x: x.get("end", ""))[-3:]
                for v in recent:
                    period = v.get("end", "?")
                    val = v.get("val", 0)
                    if abs(val) > 1_000_000:
                        lines.append(f"  {label}: ${val/1_000_000:.1f}M ({period})")
                    else:
                        lines.append(f"  {label}: {val} ({period})")

        return "\n".join(lines[:30])  # cap at 30 lines

    async def _analyze_with_gpt(
        self, ticker: str, filing: dict, facts_text: str
    ) -> Optional[str]:
        """Use GPT-4o-mini to analyze a SEC filing."""
        if not settings.openai_api_key:
            return None

        prompt = f"""分析{ticker}的SEC {filing['form']}文件（{filing['date']}提交）。

以下是XBRL提取的关键财务数据：
{facts_text}

请用中文简洁分析（200字内）：
1. 营收和利润趋势（同比变化方向）
2. 关键财务指标亮点或风险
3. 对股价的潜在影响（利好/利空/中性）
4. 一句话总结：该财报对投资决策的影响"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.openai_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_chat_model,
                        "messages": [
                            {"role": "system",
                             "content": "你是一位SEC文件分析专家。用中文分析财报数据，给出简洁的投资参考意见。"},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500,
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"GPT analysis failed for {ticker}: {e}")
            return None


# ============================================================
# 6. AI Sentiment Collector (GPT holistic scoring)
# ============================================================

class AISentimentCollector:
    """
    Aggregate recent knowledge per ticker, use GPT-4o-mini
    to produce a holistic sentiment score [-1.0, +1.0].
    Groups tickers by sector to reduce API calls.
    """

    async def run(self) -> dict:
        results = {"scored": 0, "skipped": 0, "errors": 0}
        ks = get_knowledge_service()

        if not settings.openai_api_key:
            logger.warning("AISentimentCollector: no OpenAI API key, skipping")
            return results

        from app.config.rotation_watchlist import (
            OFFENSIVE_ETFS, DEFENSIVE_ETFS, MIDCAP_STOCKS,
        )

        # Group by sector
        groups: Dict[str, list] = {}
        for item in MIDCAP_STOCKS:
            sector = item.get("sector", "other")
            groups.setdefault(sector, []).append(item["ticker"])
        groups["etf_offensive"] = [e["ticker"] for e in OFFENSIVE_ETFS]
        groups["etf_defensive"] = [e["ticker"] for e in DEFENSIVE_ETFS]

        for group_name, tickers in groups.items():
            try:
                # Gather knowledge context for the group
                group_context = []
                for ticker in tickers:
                    entries = await ks.search_by_ticker(ticker, top_k=5)
                    if entries:
                        summaries = []
                        for e in entries[:3]:
                            s = e.get("summary") or e.get("content", "")[:100]
                            summaries.append(f"  - {s}")
                        group_context.append(
                            f"[{ticker}]\n" + "\n".join(summaries)
                        )

                if not group_context:
                    results["skipped"] += len(tickers)
                    continue

                # Call GPT for batch scoring
                scores = await self._batch_score(
                    group_name, tickers, "\n\n".join(group_context)
                )

                # Write scores to knowledge base
                for score_entry in scores:
                    ticker = score_entry.get("ticker", "")
                    if ticker not in tickers:
                        continue
                    score = max(-1.0, min(1.0, float(score_entry.get("score", 0))))
                    confidence = max(0.0, min(1.0, float(
                        score_entry.get("confidence", 0.5)
                    )))
                    reasoning = score_entry.get("reasoning", "")

                    direction = "看多" if score > 0.1 else "看空" if score < -0.1 else "中性"
                    content = (
                        f"{ticker} AI情绪评分: {score:.2f} ({direction}), "
                        f"置信度{confidence:.0%}。{reasoning}"
                    )

                    await ks.add_knowledge(
                        content=content,
                        source_type="auto_ai_sentiment",
                        category="research",
                        tickers=[ticker],
                        tags=["ai_sentiment", "daily", direction],
                        relevance_date=date.today().isoformat(),
                        expires_at=(
                            datetime.utcnow() + timedelta(days=2)
                        ).isoformat(),
                        metadata={
                            "score": score,
                            "confidence": confidence,
                            "reasoning": reasoning,
                            "group": group_name,
                        },
                    )
                    results["scored"] += 1

            except Exception as e:
                logger.error(
                    f"AISentimentCollector error for group {group_name}: {e}"
                )
                results["errors"] += 1

        logger.info(f"AISentimentCollector: done. {results}")
        return results

    async def _batch_score(
        self, group_name: str, tickers: list, context: str
    ) -> list:
        """Call GPT-4o-mini to score a group of tickers."""
        ticker_list = ", ".join(tickers)
        prompt = f"""你是一位量化分析师。根据以下知识库信息，为每只股票给出情绪评分。

板块: {group_name}
股票: {ticker_list}

最近知识库信息:
{context[:3000]}

请为每只股票返回JSON数组，格式:
[{{"ticker": "XXX", "score": 0.5, "confidence": 0.8, "reasoning": "简要原因"}}]

评分规则:
- score: -1.0(极度看空) 到 +1.0(极度看多), 0=中性
- confidence: 0.0-1.0, 信息越充分越高
- 如果某只股票没有任何相关信息，score=0, confidence=0.1

只返回JSON数组，不要其他文字。"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{settings.openai_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_chat_model,
                        "messages": [
                            {"role": "system",
                             "content": "你是量化分析师。只返回JSON数组。"},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1000,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
                # Extract JSON from response
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    return json.loads(match.group())
        except Exception as e:
            logger.error(f"GPT batch scoring failed for {group_name}: {e}")

        return []


# ============================================================
# 7. ETF Fund Flow Collector
# ============================================================

class ETFFlowCollector:
    """
    Track daily ETF fund flows for offensive ETFs.
    Uses stockanalysis.com as primary source.
    """

    async def run(self) -> dict:
        results = {"tracked": 0, "errors": 0}
        ks = get_knowledge_service()

        from app.config.rotation_watchlist import OFFENSIVE_ETFS
        etfs = [e["ticker"] for e in OFFENSIVE_ETFS]

        flow_data = {}

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0",
            },
            follow_redirects=True,
        ) as client:
            for ticker in etfs:
                try:
                    await asyncio.sleep(3)  # polite scraping
                    resp = await client.get(
                        f"https://stockanalysis.com/etf/{ticker.lower()}/",
                    )
                    if resp.status_code != 200:
                        continue

                    # Try to extract fund flow from page text
                    text = resp.text
                    flow_info = self._parse_flow_data(text, ticker)
                    if flow_info:
                        flow_data[ticker] = flow_info

                except Exception as e:
                    logger.warning(f"ETFFlowCollector: {ticker} fetch error: {e}")
                    results["errors"] += 1

        # If scraping failed, use yfinance totalAssets as fallback
        if len(flow_data) < 3:
            logger.info("ETFFlowCollector: scraping limited, using yfinance fallback")
            for ticker in etfs:
                if ticker in flow_data:
                    continue
                try:
                    info = yf.Ticker(ticker).info
                    total_assets = info.get("totalAssets", 0)
                    if total_assets:
                        flow_data[ticker] = {
                            "total_assets": total_assets,
                            "source": "yfinance",
                        }
                except Exception:
                    pass

        # Generate summary and write to knowledge base
        if flow_data:
            # Sort by assets/flow
            lines = []
            for ticker, data in sorted(flow_data.items()):
                assets = data.get("total_assets", 0)
                if assets > 0:
                    lines.append(
                        f"  {ticker}: 总资产${assets/1e9:.1f}B"
                    )
                flow = data.get("flow_1w", "N/A")
                if flow != "N/A":
                    lines.append(f"  {ticker}: 周资金流{flow}")

            content = (
                f"ETF资金流向跟踪 ({date.today().isoformat()}):\n"
                + "\n".join(lines[:20])
            )

            await ks.add_knowledge(
                content=content,
                source_type="auto_etf_flow",
                category="fund_flow",
                tickers=list(flow_data.keys()),
                tags=["etf_flow", "daily", "fund_flow"],
                relevance_date=date.today().isoformat(),
                expires_at=(datetime.utcnow() + timedelta(days=7)).isoformat(),
                metadata={
                    "etf_count": len(flow_data),
                    "data": {k: v for k, v in flow_data.items()},
                },
            )
            results["tracked"] = len(flow_data)

        logger.info(f"ETFFlowCollector: done. {results}")
        return results

    def _parse_flow_data(self, html: str, ticker: str) -> Optional[dict]:
        """Parse ETF flow data from stockanalysis.com HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Try to find assets under management
            data = {}
            text = soup.get_text()

            # Look for "Assets Under Management" or "Net Assets"
            import re
            assets_match = re.search(
                r'(?:Assets|Net Assets|AUM)[:\s]*\$?([\d,.]+)\s*(B|M|T)',
                text, re.IGNORECASE,
            )
            if assets_match:
                value = float(assets_match.group(1).replace(",", ""))
                unit = assets_match.group(2).upper()
                multiplier = {"T": 1e12, "B": 1e9, "M": 1e6}.get(unit, 1)
                data["total_assets"] = value * multiplier

            # Look for fund flow mentions
            flow_match = re.search(
                r'(?:Fund Flow|Inflow|Outflow)[:\s]*[+-]?\$?([\d,.]+)\s*(B|M)',
                text, re.IGNORECASE,
            )
            if flow_match:
                data["flow_1w"] = flow_match.group(0)

            data["source"] = "stockanalysis"
            return data if len(data) > 1 else None
        except Exception:
            return None


# ============================================================
# 8. Institutional Holdings Collector (13F)
# ============================================================

class InstitutionalHoldingsCollector:
    """
    Track 13F-HR institutional holdings changes for mid-cap stocks.
    Quarterly filings, run weekly to catch new filings.
    """

    async def run(self) -> dict:
        results = {"processed": 0, "skipped": 0, "errors": 0}
        ks = get_knowledge_service()

        from app.config.rotation_watchlist import MIDCAP_STOCKS
        tickers = [s["ticker"] for s in MIDCAP_STOCKS]

        cik_map = await _get_cik_mapping()
        if not cik_map:
            logger.error("InstitutionalHoldingsCollector: CIK mapping empty")
            return results

        cutoff_90d = (date.today() - timedelta(days=90)).isoformat()

        async with httpx.AsyncClient(timeout=30.0, headers=SEC_HEADERS) as client:
            for ticker in tickers:
                try:
                    cik = cik_map.get(ticker)
                    if not cik:
                        results["skipped"] += 1
                        continue

                    await asyncio.sleep(SEC_RATE_LIMIT)

                    # Search for 13F filings mentioning this company
                    resp = await client.get(
                        f"{SEC_EFTS}/search-index",
                        params={
                            "q": f'"{ticker}"',
                            "forms": "13F-HR",
                            "dateRange": "custom",
                            "startdt": cutoff_90d,
                            "enddt": date.today().isoformat(),
                        },
                    )
                    if resp.status_code != 200:
                        continue

                    search_data = resp.json()
                    hits = search_data.get("hits", {}).get("hits", [])

                    if not hits:
                        results["skipped"] += 1
                        continue

                    # Check if already processed
                    existing = await ks.search_by_ticker(ticker, top_k=5)
                    existing_13f_dates = set()
                    for entry in existing:
                        meta = entry.get("metadata") or {}
                        if isinstance(meta, str):
                            try:
                                meta = json.loads(meta)
                            except Exception:
                                meta = {}
                        if meta.get("source_type") == "auto_13f_holdings":
                            existing_13f_dates.add(meta.get("latest_filing_date"))

                    # Get the latest filing date
                    latest_date = ""
                    filer_names = []
                    for hit in hits[:10]:
                        source = hit.get("_source", {})
                        filed = source.get("file_date", "")
                        name = source.get("display_names", ["Unknown"])[0]
                        if filed > latest_date:
                            latest_date = filed
                        filer_names.append(name)

                    if latest_date in existing_13f_dates:
                        results["skipped"] += 1
                        continue

                    # Generate summary
                    unique_filers = list(set(filer_names))[:10]
                    content = (
                        f"{ticker} 机构持仓更新 (截至{latest_date}):\n"
                        f"近90天有{len(hits)}份13F报告提及{ticker}。\n"
                        f"涉及机构: {', '.join(unique_filers[:5])}"
                        + (f" 等共{len(unique_filers)}家" if len(unique_filers) > 5 else "")
                    )

                    # GPT enhancement if enough data
                    if len(hits) >= 3 and settings.openai_api_key:
                        enhanced = await self._gpt_summarize(
                            ticker, content, len(hits)
                        )
                        if enhanced:
                            content = enhanced

                    await ks.add_knowledge(
                        content=content,
                        source_type="auto_13f_holdings",
                        category="institutional",
                        tickers=[ticker],
                        tags=["13f", "institutional", "quarterly"],
                        relevance_date=latest_date or date.today().isoformat(),
                        expires_at=(
                            datetime.utcnow() + timedelta(days=90)
                        ).isoformat(),
                        metadata={
                            "filing_count": len(hits),
                            "latest_filing_date": latest_date,
                            "filer_count": len(unique_filers),
                            "source_type": "auto_13f_holdings",
                        },
                    )
                    results["processed"] += 1

                except Exception as e:
                    logger.error(
                        f"InstitutionalHoldingsCollector error for {ticker}: {e}"
                    )
                    results["errors"] += 1

        logger.info(f"InstitutionalHoldingsCollector: done. {results}")
        return results

    async def _gpt_summarize(
        self, ticker: str, raw_content: str, filing_count: int
    ) -> Optional[str]:
        """Use GPT to create a better Chinese summary."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.openai_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_chat_model,
                        "messages": [
                            {"role": "system",
                             "content": "你是一位机构持仓分析师。用中文简洁分析机构持仓变化对股价的潜在影响。"},
                            {"role": "user",
                             "content": f"分析{ticker}的最新机构持仓情况（100字内）:\n{raw_content}"},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 300,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"GPT 13F summary failed for {ticker}: {e}")
            return None


# ============================================================
# Convenience runner for all collectors
# ============================================================

async def run_all_collectors() -> dict:
    """Run all 8 collectors. Used for manual trigger endpoint."""
    results = {}

    # Original 4
    results["signal_outcome"] = await SignalOutcomeCollector().run()
    results["news_outcome"] = await NewsOutcomeCollector().run()
    results["pattern_stat"] = await PatternStatCollector().run()
    results["sector_rotation"] = await SectorRotationCollector().run()

    # V2.1 AI-enhanced 4
    results["earnings_report"] = await EarningsReportCollector().run()
    results["ai_sentiment"] = await AISentimentCollector().run()
    results["etf_flow"] = await ETFFlowCollector().run()
    results["institutional_holdings"] = await InstitutionalHoldingsCollector().run()

    logger.info(f"All 8 collectors completed: {results}")
    return results
