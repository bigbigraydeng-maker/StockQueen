"""
StockQueen V1 - Task Scheduler
Scheduled tasks for daily operations
"""

import asyncio
import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import pytz

from app.config import settings
from app.services.news_service import run_news_fetcher
from app.services.ai_service import run_ai_classification
from app.services.market_service import run_market_data_fetch
from app.services.signal_service import run_signal_generation, run_geopolitical_scan
from app.services.signal_service import run_confirmation_engine
from app.services.notification_service import (
    notify_signals_ready, notify_geopolitical_signals,
    notify_rotation_summary, notify_rotation_entry, notify_rotation_exit,
    notify_midweek_replacement,
)

logger = logging.getLogger(__name__)


class TaskScheduler:
    """APScheduler wrapper for StockQueen tasks"""
    
    def __init__(self):
        self.timezone = pytz.timezone(settings.timezone)
        self.scheduler = AsyncIOScheduler(
            timezone=self.timezone,
            job_defaults={"misfire_grace_time": 3600},  # Render 重启后1小时内仍补跑
        )
        self._setup_jobs()
    
    def _setup_jobs(self):
        """Setup scheduled jobs

        ===== 时区对照 (3月 NZ夏令时 NZDT=UTC+13, 美国夏令时 EDT=UTC-4) =====
        美股开盘 09:30 EDT = 次日 02:30 NZT
        美股收盘 16:00 EDT = 次日 09:00 NZT

        关键原则:
        - 收盘数据任务 → 09:15+ NZT (美股收盘后15分钟, 等数据落地)
        - 盘中监控任务 → 03:00-08:00 NZT (美股交易时段)
        - 周度轮动 → 周六 10:00 NZT (周五收盘后, 用完整一周数据)
        - 每日入场/退出 → 周二-周六 09:30 NZT (前一交易日收盘后)

        NZ日历 vs 美股交易日:
        周二早上 NZT → 周一美股收盘数据
        周三早上 NZT → 周二美股收盘数据
        周四早上 NZT → 周三美股收盘数据
        周五早上 NZT → 周四美股收盘数据
        周六早上 NZT → 周五美股收盘数据
        """

        # ===== 美股收盘后任务 (09:15-10:00 NZT = 收盘后15-60分钟) =====

        # Job 1: Market Data Fetch (Tue-Sat 09:15 NZT = 美股收盘后15分钟)
        self.scheduler.add_job(
            self._run_market_data_pipeline,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=15),
            id="market_data_pipeline",
            name="Market Data Fetch (post-close)",
            replace_existing=True
        )

        # Job 1b: Regime Change Monitor (Tue-Sat 09:20 NZT = 收盘数据到位后立即检测)
        self.scheduler.add_job(
            self._run_regime_monitor,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=20),
            id="regime_monitor",
            name="Regime Change Monitor (daily post-close)",
            replace_existing=True
        )

        # Job 2: D+1 Confirmation Engine (Tue-Sat 09:30 NZT)
        self.scheduler.add_job(
            self._run_confirmation_engine,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=30),
            id="confirmation_engine",
            name="D+1 Confirmation Check",
            replace_existing=True
        )

        # Job 3: Daily Entry Check (Tue-Sat 09:40 NZT = 收盘数据到位后)
        self.scheduler.add_job(
            self._run_daily_entry_check,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=40),
            id="daily_entry_check",
            name="Daily Entry Check (post-close)",
            replace_existing=True
        )

        # Job 4: Daily Exit Check (Tue-Sat 09:45 NZT)
        self.scheduler.add_job(
            self._run_daily_exit_check,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=45),
            id="daily_exit_check",
            name="Daily Exit Check (post-close)",
            replace_existing=True
        )

        # Job 4e: ML Exit Scorer Signal Collection (Tue-Sat 09:46 NZT = exit check 后1分钟)
        # 信号采集模式: 对所有活跃仓位运行 ML 推理并记录信号 (不执行交易)
        self.scheduler.add_job(
            self._run_exit_scorer,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=46),
            id="exit_scorer",
            name="ML Exit Scorer Signal Collection (Tranche B)",
            replace_existing=True
        )

        # Job 4f: Mid-week Replacement Check (Tue-Sat 09:47 NZT = exit check 后2分钟)
        # 检查是否有空槽，从本周备选名单补位（ATR漂移验证）
        self.scheduler.add_job(
            self._run_midweek_replacement,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=47),
            id="midweek_replacement",
            name="Mid-week Replacement Check (post-exit)",
            replace_existing=True
        )

        # Job 4d: Sub-Strategy Signal Scan — MR + ED 候选信号扫描 (Tue-Sat 09:50 NZT)
        # 在 entry/exit check 之后运行，结果缓存供 Dashboard 展示
        self.scheduler.add_job(
            self._run_sub_strategy_scan,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=50),
            id="sub_strategy_scan",
            name="Sub-Strategy Signal Scan (MR+ED post-close)",
            replace_existing=True
        )

        # Job 4b: Sync Tiger Order Status (Tue-Sat, every 30 min during trading hours NZT 01:00-09:30)
        self.scheduler.add_job(
            self._run_sync_tiger_orders,
            trigger=CronTrigger(day_of_week='tue-sat', hour='1-9', minute='*/30'),
            id="sync_tiger_orders",
            name="Sync Tiger Order Status",
            replace_existing=True
        )

        # Job 4c: Intraday Full-Watchlist Price Scan (Tue-Sat, every 20 min NZT 02:30-08:40 = EDT 09:30-15:40)
        # Fetches GLOBAL_QUOTE for 180+ tickers; result cached in memory for instant UI display
        self.scheduler.add_job(
            self._run_intraday_price_scan,
            trigger=CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/20'),
            id="intraday_price_scan",
            name="Intraday Full-Watchlist Price Scan (every 20min)",
            replace_existing=True
        )

        # Job 5: Signal Outcome Tracker (Tue-Sat 09:50 NZT)
        self.scheduler.add_job(
            self._run_signal_outcome_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=50),
            id="signal_outcome_collector",
            name="Signal Outcome Tracker",
            replace_existing=True
        )

        # Job 5b: After-Hours AI Event Signal Scan (Tue-Sat 09:55 NZT = 美股收盘后55分钟)
        self.scheduler.add_job(
            self._run_event_signal_scan,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=55),
            id="event_signal_scan",
            name="After-Hours AI Event Signal Scan (C2)",
            replace_existing=True
        )

        # Job 6: News Outcome Correlator (Tue-Sat 10:00 NZT)
        self.scheduler.add_job(
            self._run_news_outcome_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=10, minute=0),
            id="news_outcome_collector",
            name="News Outcome Correlator",
            replace_existing=True
        )

        # ===== 美股盘中任务 (02:30-09:00 NZT = EDT 09:30-16:00) =====

        # Job 20: Intraday Trailing Stop Monitor (every 5 min during market hours)
        self.scheduler.add_job(
            self._run_intraday_trailing_stop,
            trigger=CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/5'),
            id="intraday_trailing_stop",
            name="Intraday Trailing Stop Monitor (5min)",
            replace_existing=True
        )

        # Job 21: Unfilled Order Management (every 15 min during market hours)
        self.scheduler.add_job(
            self._run_manage_unfilled_orders,
            trigger=CronTrigger(day_of_week='tue-sat', hour='2-8', minute='*/15'),
            id="manage_unfilled_orders",
            name="Unfilled Order Manager (15min)",
            replace_existing=True
        )

        # Job 7: News Fetch + AI Classification (Tue-Sat 03:30 NZT = EDT 10:30 盘中)
        self.scheduler.add_job(
            self._run_news_pipeline,
            trigger=CronTrigger(day_of_week='tue-sat', hour=3, minute=30),
            id="news_pipeline",
            name="News Fetch and AI Classification (intraday)",
            replace_existing=True
        )

        # Job 8: Geopolitical Crisis Scan - 盘中 (Tue-Sat 04:00 NZT = EDT 11:00)
        self.scheduler.add_job(
            self._run_geopolitical_scan,
            trigger=CronTrigger(day_of_week='tue-sat', hour=4, minute=0),
            id="geopolitical_scan_intraday",
            name="Geopolitical Crisis Scan (intraday)",
            replace_existing=True
        )

        # Job 9: Geopolitical Crisis Scan - 临近收盘 (Tue-Sat 07:30 NZT = EDT 14:30)
        self.scheduler.add_job(
            self._run_geopolitical_scan,
            trigger=CronTrigger(day_of_week='tue-sat', hour=7, minute=30),
            id="geopolitical_scan_preclose",
            name="Geopolitical Crisis Scan (pre-close)",
            replace_existing=True
        )

        # ===== 周度任务 =====

        # Job 14: Weekly Rotation (周六 10:00 NZT = 周五美股收盘后1小时, 用完整一周数据)
        self.scheduler.add_job(
            self._run_weekly_rotation,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=0),
            id="weekly_rotation",
            name="Weekly Momentum Rotation (after Fri close)",
            replace_existing=True
        )

        # Job 15: Pattern Statistics (周六 10:30 NZT)
        self.scheduler.add_job(
            self._run_pattern_stat_collector,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=30),
            id="pattern_stat_collector",
            name="Technical Pattern Statistics (weekly)",
            replace_existing=True
        )

        # Job 16: Sector Rotation Recorder (周六 10:30 NZT)
        self.scheduler.add_job(
            self._run_sector_rotation_collector,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=30),
            id="sector_rotation_collector",
            name="Sector Rotation Recorder (weekly)",
            replace_existing=True
        )

        # Job 14b: Refresh Yearly Performance JSON (周六 10:15 NZT = rotation后15分钟, 用最新快照数据刷新静态JSON)
        self.scheduler.add_job(
            self._run_refresh_yearly_performance,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=15),
            id="refresh_yearly_performance",
            name="Refresh Yearly Performance JSON (post-rotation)",
            replace_existing=True
        )

        # Job 14c: Refresh Equity Curve JSON (周六 10:20 NZT = rotation后20分钟)
        self.scheduler.add_job(
            self._run_refresh_equity_curve,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=20),
            id="refresh_equity_curve",
            name="Refresh Equity Curve JSON (post-rotation)",
            replace_existing=True
        )

        # Job 17: Backtest Pre-compute 已移至 GitHub Actions
        # (.github/workflows/backtest-precompute.yml 每周六 22:00 UTC 触发)
        # 在服务器进程内运行 CPU 密集型预计算会阻塞事件循环，导致其他请求 499

        # Job 20: Newsletter Generation & Send (周六 12:00 NZT = rotation + precompute后，数据完整)
        self.scheduler.add_job(
            self._run_newsletter_generation,
            trigger=CronTrigger(day_of_week='sat', hour=12, minute=0),
            id="newsletter_generation",
            name="Weekly Newsletter Generation & Send",
            replace_existing=True
        )

        # ===== 月度任务 =====

        # Job 18: Auto Parameter Tuning (每月1日 12:00 NZT = 非交易时段, 用上月完整数据)
        self.scheduler.add_job(
            self._run_auto_param_tune,
            trigger=CronTrigger(day=1, hour=12, minute=0),
            id="auto_param_tune",
            name="Monthly Auto Parameter Tuning",
            replace_existing=True
        )

        # Job 18b: ML-V3A Monthly Retrain (每月1日 13:00 NZT = param tune 后1小时)
        # 滑动18个月训练窗口，保持模型对最新市场环境的感知
        self.scheduler.add_job(
            self._run_ml_monthly_retrain,
            trigger=CronTrigger(day=1, hour=13, minute=0),
            id="ml_monthly_retrain",
            name="ML-V3A Monthly Retrain (sliding 18-month window)",
            replace_existing=True
        )

        # ===== 维护任务 =====

        # Job 13: Knowledge Cleanup (每天 15:00 NZT = 下午, 非交易时段)
        self.scheduler.add_job(
            self._run_knowledge_cleanup,
            trigger=CronTrigger(hour=15, minute=0),
            id="knowledge_cleanup",
            name="Knowledge Base Cleanup",
            replace_existing=True
        )

        # ===== AI 增强收集器 (10:15-11:30 NZT = 收盘后1-2小时, 数据充分落地) =====

        # Job 14: AI Sentiment Scorer (Tue-Sat 10:15 NZT = 在所有收集器之后聚合)
        self.scheduler.add_job(
            self._run_ai_sentiment_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=10, minute=15),
            id="ai_sentiment_collector",
            name="AI Sentiment Scorer (post-collectors)",
            replace_existing=True
        )

        # Job 15: ETF Fund Flow Tracker (Tue-Sat 10:30 NZT)
        self.scheduler.add_job(
            self._run_etf_flow_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=10, minute=30),
            id="etf_flow_collector",
            name="ETF Fund Flow Tracker",
            replace_existing=True
        )

        # Job 16: Earnings Report Analyzer (Tue-Sat 11:00 NZT = SEC数据延迟较大)
        self.scheduler.add_job(
            self._run_earnings_report_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=11, minute=0),
            id="earnings_report_collector",
            name="Earnings Report Analyzer (SEC EDGAR)",
            replace_existing=True
        )

        # Job 17: 13F Institutional Holdings (Saturday 11:30 NZT = 周度检查)
        self.scheduler.add_job(
            self._run_institutional_holdings_collector,
            trigger=CronTrigger(day_of_week='sat', hour=11, minute=30),
            id="institutional_holdings_collector",
            name="13F Institutional Holdings (weekly)",
            replace_existing=True
        )

        # Job 18: Dynamic Universe Refresh (周六 09:00 NZT = 轮动前1小时刷新选股池)
        self.scheduler.add_job(
            self._run_universe_refresh,
            trigger=CronTrigger(day_of_week='sat', hour=9, minute=0),
            id="universe_refresh",
            name="Dynamic Universe Refresh (weekly, before rotation)",
            replace_existing=True
        )

        # ===== FMP 基本面批量采集（周六 09:30 NZT = 轮动前30分钟，FMP高级版覆盖完整动态池）=====
        # 4 个 Job 并行运行，各自独立写入 knowledge_base 不同 source_type

        # Job 22a: Fundamental Data Collector (公司概况 + TTM比率)
        self.scheduler.add_job(
            self._run_fundamental_data_collector,
            trigger=CronTrigger(day_of_week='sat', hour=9, minute=30),
            id="fundamental_data_collector",
            name="FMP Fundamental Data Collector (profile + ratios-ttm, full pool)",
            replace_existing=True
        )

        # Job 22b: Earnings Calendar Collector (历史EPS + beat率)
        self.scheduler.add_job(
            self._run_earnings_calendar_collector,
            trigger=CronTrigger(day_of_week='sat', hour=9, minute=30),
            id="earnings_calendar_collector",
            name="FMP Earnings Calendar Collector (EPS + beat rate, full pool)",
            replace_existing=True
        )

        # Job 22c: Income Growth Collector (季度收入表)
        self.scheduler.add_job(
            self._run_income_growth_collector,
            trigger=CronTrigger(day_of_week='sat', hour=9, minute=30),
            id="income_growth_collector",
            name="FMP Income Growth Collector (quarterly income, full pool)",
            replace_existing=True
        )

        # Job 22d: Cash Flow Health Collector (季度现金流)
        self.scheduler.add_job(
            self._run_cashflow_health_collector,
            trigger=CronTrigger(day_of_week='sat', hour=9, minute=30),
            id="cashflow_health_collector",
            name="FMP Cash Flow Health Collector (quarterly cashflow, full pool)",
            replace_existing=True
        )

        logger.info("Scheduled jobs configured (V3.3 - FMP fundamental collectors added, full dynamic pool coverage)")

    async def _run_news_pipeline(self):
        """Run news fetch and AI classification"""
        logger.info("=" * 50)
        logger.info("Starting News Pipeline")
        logger.info("=" * 50)
        
        try:
            # Step 1: Fetch news
            news_result = await run_news_fetcher()
            logger.info(f"News fetch result: {news_result}")
            
            # Step 2: AI classification
            ai_result = await run_ai_classification()
            logger.info(f"AI classification result: {ai_result}")
            
            logger.info("News pipeline completed successfully")
            
        except Exception as e:
            logger.error(f"Error in news pipeline: {e}", exc_info=True)
    
    async def _run_regime_monitor(self):
        """Check regime daily and alert on change."""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Regime Monitor skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("=" * 50)
        logger.info("Starting Regime Change Monitor")
        logger.info("=" * 50)

        try:
            from app.services.regime_monitor import check_regime_and_alert
            result = await check_regime_and_alert()
            status = result.get("status", "unknown")
            regime = result.get("regime", "?")
            logger.info(f"Regime monitor result: status={status}, regime={regime}")
            if status == "changed":
                logger.warning(
                    f"REGIME CHANGED: {result.get('previous')} → {regime} "
                    f"(score={result.get('score')})"
                )
        except Exception as e:
            logger.error(f"Error in regime monitor: {e}", exc_info=True)

    async def _run_sub_strategy_scan(self):
        """每日盘后扫描 MR + ED 子策略候选信号，结果缓存供 Dashboard 展示。"""
        logger.info("=" * 50)
        logger.info("Starting Sub-Strategy Signal Scan (MR + ED)")
        logger.info("=" * 50)
        try:
            from app.services.portfolio_manager import run_and_cache_daily_signals
            result = await run_and_cache_daily_signals()
            logger.info(
                f"Sub-strategy scan done: regime={result.get('regime')} "
                f"MR_candidates={len(result.get('mr_candidates', []))} "
                f"ED_candidates={len(result.get('ed_candidates', []))}"
            )
        except Exception as e:
            logger.error(f"Error in sub-strategy scan: {e}", exc_info=True)

    @staticmethod
    def _market_jobs_paused() -> bool:
        """环境变量 PAUSE_MARKET_DATA_JOBS=true 时暂停所有行情相关任务。"""
        return os.environ.get("PAUSE_MARKET_DATA_JOBS", "false").lower() == "true"

    async def _run_market_data_pipeline(self):
        """Run market data fetch and signal generation"""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Market Data Pipeline skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("=" * 50)
        logger.info("Starting Market Data Pipeline")
        logger.info("=" * 50)

        try:
            # Step 1: Fetch market data
            market_result = await run_market_data_fetch()
            logger.info(f"Market data result: {market_result}")
            
            # Step 2: Generate signals
            signals = await run_signal_generation()
            logger.info(f"Signal generation result: {len(signals)} signals generated")
            
            # Step 3: Send notification if signals were generated
            if signals:
                notification_result = await notify_signals_ready(signals)
                logger.info(f"Signal notification sent: {notification_result}")
            
            logger.info("Market data pipeline completed successfully")
            
        except Exception as e:
            logger.error(f"Error in market data pipeline: {e}", exc_info=True)
    
    async def _run_geopolitical_scan(self):
        """Run geopolitical crisis scan (Hormuz crisis)"""
        logger.info("=" * 50)
        logger.info("Starting Geopolitical Crisis Scan")
        logger.info("=" * 50)

        try:
            signals = await run_geopolitical_scan()
            logger.info(f"Geopolitical scan result: {len(signals)} signals generated")

            if signals:
                notification_result = await notify_geopolitical_signals(signals)
                logger.info(f"Geopolitical notification sent: {notification_result}")

            logger.info("Geopolitical scan completed successfully")

        except Exception as e:
            logger.error(f"Error in geopolitical scan: {e}", exc_info=True)

    async def _run_confirmation_engine(self):
        """Run D+1 confirmation engine"""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Confirmation Engine skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("=" * 50)
        logger.info("Starting Confirmation Engine")
        logger.info("=" * 50)
        
        try:
            result = await run_confirmation_engine()
            logger.info(f"Confirmation engine result: {result}")
            
        except Exception as e:
            logger.error(f"Error in confirmation engine: {e}", exc_info=True)
    
    # ===== RAG Knowledge Collector Handlers =====

    async def _run_signal_outcome_collector(self):
        """Track signal outcomes (1d/5d/20d returns)"""
        logger.info("Starting Signal Outcome Collector")
        try:
            from app.services.knowledge_collectors import SignalOutcomeCollector
            result = await SignalOutcomeCollector().run()
            logger.info(f"Signal outcome collector: {result}")
        except Exception as e:
            logger.error(f"Error in signal outcome collector: {e}", exc_info=True)

    async def _run_news_outcome_collector(self):
        """Correlate news events with price movements"""
        logger.info("Starting News Outcome Collector")
        try:
            from app.services.knowledge_collectors import NewsOutcomeCollector
            result = await NewsOutcomeCollector().run()
            logger.info(f"News outcome collector: {result}")
        except Exception as e:
            logger.error(f"Error in news outcome collector: {e}", exc_info=True)

    async def _run_pattern_stat_collector(self):
        """Compute technical pattern statistics"""
        logger.info("Starting Pattern Stat Collector")
        try:
            from app.services.knowledge_collectors import PatternStatCollector
            result = await PatternStatCollector().run()
            logger.info(f"Pattern stat collector: {result}")
        except Exception as e:
            logger.error(f"Error in pattern stat collector: {e}", exc_info=True)

    async def _run_sector_rotation_collector(self):
        """Record sector/ETF rotation rankings"""
        logger.info("Starting Sector Rotation Collector")
        try:
            from app.services.knowledge_collectors import SectorRotationCollector
            result = await SectorRotationCollector().run()
            logger.info(f"Sector rotation collector: {result}")
        except Exception as e:
            logger.error(f"Error in sector rotation collector: {e}", exc_info=True)

    async def _run_knowledge_cleanup(self):
        """Clean up expired knowledge entries"""
        logger.info("Starting Knowledge Cleanup")
        try:
            from app.services.knowledge_service import get_knowledge_service
            ks = get_knowledge_service()
            count = await ks.cleanup_expired()
            logger.info(f"Knowledge cleanup: removed {count} expired entries")
        except Exception as e:
            logger.error(f"Error in knowledge cleanup: {e}", exc_info=True)

    # ===== C2: After-Hours Event Signal Scanner =====

    async def _run_event_signal_scan(self):
        """Run after-hours AI event signal scan (C2)."""
        logger.info("Starting after-hours AI event signal scan")
        try:
            from app.services.news_scanner_service import get_news_scanner
            result = await get_news_scanner().run_daily_scan()
            logger.info(f"Event signal scan: {result}")
        except Exception as e:
            logger.error(f"Error in event signal scan: {e}", exc_info=True)

    # ===== AI Enhanced Collector Handlers =====

    async def _run_ai_sentiment_collector(self):
        """Run AI sentiment scoring across all tickers"""
        logger.info("Starting AI Sentiment Collector")
        try:
            from app.services.knowledge_collectors import AISentimentCollector
            result = await AISentimentCollector().run()
            logger.info(f"AI sentiment collector: {result}")
        except Exception as e:
            logger.error(f"Error in AI sentiment collector: {e}", exc_info=True)

    async def _run_etf_flow_collector(self):
        """Track ETF fund flows"""
        logger.info("Starting ETF Flow Collector")
        try:
            from app.services.knowledge_collectors import ETFFlowCollector
            result = await ETFFlowCollector().run()
            logger.info(f"ETF flow collector: {result}")
        except Exception as e:
            logger.error(f"Error in ETF flow collector: {e}", exc_info=True)

    async def _run_earnings_report_collector(self):
        """Analyze earnings reports from SEC EDGAR"""
        logger.info("Starting Earnings Report Collector")
        try:
            from app.services.knowledge_collectors import EarningsReportCollector
            result = await EarningsReportCollector().run()
            logger.info(f"Earnings report collector: {result}")
        except Exception as e:
            logger.error(f"Error in earnings report collector: {e}", exc_info=True)

    async def _run_institutional_holdings_collector(self):
        """Check 13F institutional holdings filings"""
        logger.info("Starting Institutional Holdings Collector")
        try:
            from app.services.knowledge_collectors import InstitutionalHoldingsCollector
            result = await InstitutionalHoldingsCollector().run()
            logger.info(f"Institutional holdings collector: {result}")
        except Exception as e:
            logger.error(f"Error in institutional holdings collector: {e}", exc_info=True)

    async def _run_universe_refresh(self):
        """Weekly dynamic universe refresh — runs before rotation"""
        logger.info("=" * 50)
        logger.info("Starting Dynamic Universe Refresh")
        logger.info("=" * 50)
        try:
            from app.services.universe_service import UniverseService
            svc = UniverseService()
            result = await svc.refresh_universe(concurrency=5)
            count = result.get("final_count", 0)
            logger.info(f"Universe refresh complete: {count} tickers")

            # Notify via Feishu
            from app.services.feishu_service import send_feishu_message
            await send_feishu_message(
                f"🌐 动态选股池刷新完成\n"
                f"总扫描: {result.get('total_screened', '?')}\n"
                f"最终入选: {count} 只\n"
                f"筛选耗时: {result.get('elapsed_seconds', 0):.0f}s"
            )
        except Exception as e:
            logger.error(f"Error in universe refresh: {e}", exc_info=True)

    # ===== FMP 基本面批量采集 Handlers =====

    async def _run_fundamental_data_collector(self):
        """FMP 批量拉取公司概况 + TTM比率（完整动态池）"""
        logger.info("Starting FMP Fundamental Data Collector")
        try:
            from app.services.knowledge_collectors import FundamentalDataCollector
            result = await FundamentalDataCollector().run()
            logger.info(f"Fundamental data collector: {result}")
        except Exception as e:
            logger.error(f"Error in fundamental data collector: {e}", exc_info=True)

    async def _run_earnings_calendar_collector(self):
        """FMP 批量拉取历史EPS + beat率（完整动态池）"""
        logger.info("Starting FMP Earnings Calendar Collector")
        try:
            from app.services.knowledge_collectors import EarningsCalendarCollector
            result = await EarningsCalendarCollector().run()
            logger.info(f"Earnings calendar collector: {result}")
        except Exception as e:
            logger.error(f"Error in earnings calendar collector: {e}", exc_info=True)

    async def _run_income_growth_collector(self):
        """FMP 批量拉取季度收入表（完整动态池）"""
        logger.info("Starting FMP Income Growth Collector")
        try:
            from app.services.knowledge_collectors import IncomeGrowthCollector
            result = await IncomeGrowthCollector().run()
            logger.info(f"Income growth collector: {result}")
        except Exception as e:
            logger.error(f"Error in income growth collector: {e}", exc_info=True)

    async def _run_cashflow_health_collector(self):
        """FMP 批量拉取季度现金流（完整动态池）"""
        logger.info("Starting FMP Cash Flow Health Collector")
        try:
            from app.services.knowledge_collectors import CashFlowHealthCollector
            result = await CashFlowHealthCollector().run()
            logger.info(f"Cash flow health collector: {result}")
        except Exception as e:
            logger.error(f"Error in cashflow health collector: {e}", exc_info=True)

    # ===== Auto-Tuning Handlers =====

    async def _run_auto_param_tune(self):
        """Monthly auto parameter tuning using last 6 months of data"""
        logger.info("=" * 50)
        logger.info("Starting Monthly Auto Parameter Tuning")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_auto_param_tune
            result = await run_auto_param_tune()
            logger.info(f"Auto param tune result: top_n={result.get('top_n')}, "
                        f"holding_bonus={result.get('holding_bonus')}, "
                        f"sharpe={result.get('sharpe')}")
        except Exception as e:
            logger.error(f"Error in auto param tune: {e}", exc_info=True)

    async def _run_ml_monthly_retrain(self):
        """ML-V3A 月度重训（滑动18个月窗口，保持模型新鲜）"""
        logger.info("=" * 50)
        logger.info("Starting ML-V3A Monthly Retrain")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_ml_retrain
            result = await run_ml_retrain(months_lookback=18)
            if "error" in result:
                logger.error(f"ML retrain failed: {result['error']}")
            else:
                logger.info(
                    f"ML retrain done: {result.get('n_samples')} samples, "
                    f"corr={result.get('correlation')}, "
                    f"elapsed={result.get('elapsed_seconds')}s"
                )
        except Exception as e:
            logger.error(f"Error in ML monthly retrain: {e}", exc_info=True)

    # ===== Rotation Handlers =====

    async def _run_weekly_rotation(self):
        """Run weekly momentum rotation"""
        logger.info("=" * 50)
        logger.info("Starting Weekly Rotation")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_rotation
            result = await run_rotation(trigger_source="scheduler")
            logger.info(f"Weekly rotation result: {result.get('selected', [])}")

            if result.get("selected"):
                await notify_rotation_summary(result)
        except Exception as e:
            logger.error(f"Error in weekly rotation: {e}", exc_info=True)

    async def _run_daily_entry_check(self):
        """Run daily entry check for pending positions"""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Daily Entry Check skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("Starting Daily Entry Check")
        try:
            from app.services.rotation_service import run_daily_entry_check
            signals = await run_daily_entry_check()
            logger.info(f"Daily entry check: {len(signals)} entry signals")

            for sig in signals:
                await notify_rotation_entry(sig)
        except Exception as e:
            logger.error(f"Error in daily entry check: {e}", exc_info=True)

    async def _run_daily_exit_check(self):
        """Run daily exit check for active positions"""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Daily Exit Check skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("Starting Daily Exit Check")
        try:
            from app.services.rotation_service import run_daily_exit_check
            signals = await run_daily_exit_check()
            logger.info(f"Daily exit check: {len(signals)} exit signals")

            for sig in signals:
                await notify_rotation_exit(sig)
        except Exception as e:
            logger.error(f"Error in daily exit check: {e}", exc_info=True)

    async def _run_exit_scorer(self):
        """ML Exit Scorer — signal collection mode (no trade execution)."""
        logger.info("Starting ML Exit Scorer Signal Collection")
        try:
            from app.services.exit_scorer import run_exit_scorer_signals
            signals = await run_exit_scorer_signals()
            if signals:
                tickers = [s["ticker"] for s in signals]
                logger.warning(
                    f"Exit scorer: {len(signals)} EXIT signal(s) fired → {tickers} "
                    f"(signal-collection mode, no trade executed)"
                )
            else:
                logger.info("Exit scorer: no exit signals above threshold")
        except Exception as e:
            logger.error(f"Error in exit scorer: {e}", exc_info=True)

    async def _run_midweek_replacement(self):
        """Find backup candidates for any open position slots after mid-week exits."""
        logger.info("Starting Mid-week Replacement Check")
        try:
            from app.services.rotation_service import run_midweek_replacement
            replacements = await run_midweek_replacement()
            logger.info(f"Mid-week replacement: {len(replacements)} replacement(s) queued")

            if replacements:
                await notify_midweek_replacement(replacements)
        except Exception as e:
            logger.error(f"Error in midweek replacement: {e}", exc_info=True)

    async def _run_sync_tiger_orders(self):
        """Sync Tiger order status (filled/cancelled) for open orders"""
        logger.info("Starting Tiger order sync")
        try:
            from app.services.order_service import sync_tiger_orders
            result = await sync_tiger_orders()
            logger.info(f"Tiger order sync: {result}")
        except Exception as e:
            logger.error(f"Error syncing Tiger orders: {e}")

    # ===== Newsletter Handler =====

    async def _run_newsletter_generation(self):
        """Generate and send weekly newsletter after rotation + backtest complete"""
        logger.info("=" * 50)
        logger.info("Starting Weekly Newsletter Generation")
        logger.info("=" * 50)
        try:
            import sys
            import os
            # 确保项目根目录在 path 中
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from scripts.newsletter.data_fetcher import DataFetcher
            from scripts.newsletter.renderer import NewsletterRenderer
            from scripts.newsletter.social_generator import SocialGenerator
            from scripts.newsletter.sender import NewsletterSender

            # 1) 获取数据（使用本地 API 避免外部网络请求）
            api_base = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")
            fetcher = DataFetcher(api_base=api_base)
            data = await fetcher.fetch_all()
            logger.info(f"[NEWSLETTER] Data fetched: {len(data.get('positions', []))} positions, "
                        f"regime={data.get('market_regime')}")

            # 2) 渲染邮件
            renderer = NewsletterRenderer()
            newsletters = renderer.render_all(data)
            logger.info(f"[NEWSLETTER] Rendered: {', '.join(f'{k}={len(v)}chars' for k, v in newsletters.items())}")

            # 3) 生成社交媒体内容
            social = SocialGenerator()
            social_content = social.generate_all(data)
            logger.info(f"[NEWSLETTER] Social content: {len(social_content)} platforms")

            # 4) 保存到 output 目录
            from pathlib import Path
            output_dir = Path(project_root) / "output"
            nl_dir = output_dir / "newsletters"
            social_dir = output_dir / "social"
            nl_dir.mkdir(parents=True, exist_ok=True)
            social_dir.mkdir(parents=True, exist_ok=True)

            for name, html in newsletters.items():
                with open(nl_dir / f"{name}.html", "w", encoding="utf-8") as f:
                    f.write(html)

            ext_map = {"wechat-zh": ".md"}
            for name, content in social_content.items():
                ext = ext_map.get(name, ".txt")
                with open(social_dir / f"{name}{ext}", "w", encoding="utf-8") as f:
                    f.write(content)

            # 5) 发送邮件（如果配置了 RESEND）
            sender = NewsletterSender()
            if sender.validate_config():
                audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
                if audience_id:
                    results = sender.send_all_newsletters(
                        newsletters,
                        audience_id=audience_id,
                        week_number=data["week_number"],
                        year=data["year"],
                    )
                    logger.info(f"[NEWSLETTER] Send results: {results}")
                else:
                    logger.warning("[NEWSLETTER] RESEND_AUDIENCE_ID not set, skipping email send")
            else:
                logger.warning("[NEWSLETTER] Resend not configured, content saved but not sent")

            logger.info("[NEWSLETTER] Weekly newsletter generation complete!")

        except Exception as e:
            logger.error(f"Error in newsletter generation: {e}", exc_info=True)

    # ===== Intraday Price Scan Handler =====

    async def _run_intraday_price_scan(self):
        """Scan live quotes for full watchlist (180+ tickers) and cache results"""
        if self._market_jobs_paused():
            logger.info("[PAUSED] Intraday Price Scan skipped (PAUSE_MARKET_DATA_JOBS=true)")
            return
        logger.info("Starting Intraday Price Scan")
        try:
            from app.services.rotation_service import run_intraday_price_scan
            result = await run_intraday_price_scan()
            logger.info(
                f"Intraday price scan complete: {result.get('total', 0)} tickers, "
                f"{result.get('alerts', 0)} alerts, {result.get('failed', 0)} failed"
            )
        except Exception as e:
            logger.error(f"Error in intraday price scan: {e}", exc_info=True)

    async def _run_intraday_trailing_stop(self):
        """Real-time trailing stop check using Tiger live prices"""
        try:
            from app.services.order_service import run_intraday_trailing_stop
            result = await run_intraday_trailing_stop()
            if result.get("triggered", 0) > 0:
                logger.warning(f"[TRAILING] Exits triggered: {result}")
            else:
                logger.debug(f"[TRAILING] {result}")
        except Exception as e:
            logger.error(f"Error in intraday trailing stop: {e}", exc_info=True)

    async def _run_manage_unfilled_orders(self):
        """Check and resubmit unfilled orders as MKT"""
        try:
            from app.services.order_service import manage_unfilled_orders
            result = await manage_unfilled_orders()
            if result.get("resubmitted", 0) > 0:
                logger.info(f"[UNFILLED] Resubmitted: {result}")
        except Exception as e:
            logger.error(f"Error in unfilled order management: {e}", exc_info=True)

    # ===== Yearly Performance Auto-refresh Handler =====

    async def _run_refresh_yearly_performance(self):
        """Auto-refresh yearly-performance.json from DB after rotation"""
        logger.info("Starting Yearly Performance JSON Refresh")
        try:
            from app.routers.web import refresh_yearly_performance_json
            result = await refresh_yearly_performance_json()
            logger.info(f"Yearly performance refresh: {result}")
        except Exception as e:
            logger.error(f"Error refreshing yearly performance: {e}")

    async def _run_refresh_equity_curve(self):
        """Auto-refresh equity-curve.json from DB after rotation"""
        logger.info("Starting Equity Curve JSON Refresh")
        try:
            from app.routers.web import refresh_equity_curve_json
            result = await refresh_equity_curve_json()
            logger.info(f"Equity curve refresh: {result}")
        except Exception as e:
            logger.error(f"Error refreshing equity curve: {e}")

    # ===== Backtest Pre-compute Handler =====

    async def _run_backtest_precompute(self):
        """Pre-compute 25 backtest combos, store in cache for instant page load"""
        logger.info("=" * 50)
        logger.info("Starting Weekly Backtest Pre-compute (25 combos)")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_rotation_backtest
            import time as _time

            start_date = "2018-01-01"
            end_date = "2026-03-15"
            top_n_values = [2, 3, 4, 5, 6]
            bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

            from app.routers.web import _cache_set, _BACKTEST_TTL, _make_json_safe

            regime_versions = ["v1", "v2"]
            total = len(top_n_values) * len(bonus_values) * len(regime_versions)
            count = 0
            t0 = _time.time()

            # Fetch data with extra lookback for custom date range slicing.
            # The 25 preset combos still use start_date (2022-07-01) for cache keys,
            # but _PREFETCHED_FULL needs data from earlier for momentum/MA lookback.
            from app.services.rotation_service import _fetch_backtest_data, set_prefetched_full
            prefetch_start = "2017-01-01"  # 6mo lookback before 2018-01-01 default start_date
            prefetched = await _fetch_backtest_data(prefetch_start, end_date)
            if "error" in prefetched:
                logger.error(f"Backtest pre-compute: data fetch failed: {prefetched['error']}")
                return

            # Cache full-range data for custom date range slicing
            set_prefetched_full(prefetched, prefetch_start, end_date)

            # Persist bt_fundamentals to Supabase so OHLCV-only startup can restore them
            if prefetched.get("bt_fundamentals"):
                from app.routers.web import _cache_set, _make_json_safe
                await asyncio.to_thread(
                    _cache_set, "bt_fund:latest",
                    _make_json_safe(prefetched["bt_fundamentals"]), 86400 * 30
                )
                logger.info(f"Cached bt_fundamentals to Supabase ({len(prefetched['bt_fundamentals'])} tickers)")

            for rv in regime_versions:
                for tn in top_n_values:
                    for hb in bonus_values:
                        count += 1
                        try:
                            # 在线程池中运行 CPU 密集型回测，避免阻塞主事件循环
                            def _run_combo(_tn=tn, _hb=hb, _rv=rv):
                                return asyncio.run(run_rotation_backtest(
                                    start_date=start_date,
                                    end_date=end_date,
                                    top_n=_tn,
                                    holding_bonus=_hb,
                                    _prefetched=prefetched,
                                    regime_version=_rv,
                                ))
                            result = await asyncio.to_thread(_run_combo)
                            if "error" not in result:
                                # V1 uses legacy key (no suffix); V2 appends :v2
                                if rv == "v1":
                                    cache_key = f"bt_v2:{start_date}:{end_date}:{tn}:{hb}"
                                else:
                                    cache_key = f"bt_v2:{start_date}:{end_date}:{tn}:{hb}:{rv}"
                                safe_result = _make_json_safe(result)
                                await asyncio.to_thread(_cache_set, cache_key, safe_result, _BACKTEST_TTL)
                                logger.info(f"  [{count}/{total}] {rv}/Top{tn}/HB{hb} → Sharpe={result.get('sharpe_ratio', 0):.2f}")
                            else:
                                logger.warning(f"  [{count}/{total}] {rv}/Top{tn}/HB{hb} → error: {result['error']}")
                        except Exception as e:
                            logger.warning(f"  [{count}/{total}] {rv}/Top{tn}/HB{hb} → exception: {e}")

            total_time = _time.time() - t0
            logger.info(f"Backtest pre-compute complete: {count} combos in {total_time:.0f}s")

        except Exception as e:
            logger.error(f"Error in backtest pre-compute: {e}", exc_info=True)
            import traceback
            logger.error(traceback.format_exc())

    def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info(f"Scheduler started in timezone: {settings.timezone}")
    
    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")


# Global scheduler instance
scheduler = TaskScheduler()


def get_scheduler_logs(limit: int = 30) -> list[dict]:
    """返回调度器中已配置任务的计划信息"""
    jobs = []
    try:
        for job in scheduler.scheduler.get_jobs():
            next_run = job.next_run_time
            trigger_str = str(job.trigger) if job.trigger else "--"
            jobs.append({
                "id": job.id,
                "name": job.name or job.id,
                "trigger": trigger_str,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "paused",
            })
        # Sort by next run time (soonest first), paused jobs last
        jobs.sort(key=lambda j: j["next_run"] if j["next_run"] != "paused" else "zzzz")
    except Exception as e:
        logger.error(f"Error getting scheduler jobs: {e}")
    return jobs[:limit]


if __name__ == "__main__":
    import asyncio
    print("StockQueen Scheduler 启动...")
    
    # Create event loop first
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        scheduler.start()
        loop.run_forever()
    except KeyboardInterrupt:
        print("Scheduler 正在关闭...")
        scheduler.shutdown()
    finally:
        loop.close()
