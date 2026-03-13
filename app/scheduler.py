"""
StockQueen V2.4 - Task Scheduler
Scheduled tasks for daily operations with activity logging
"""

import logging
import time
from collections import deque
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
)

logger = logging.getLogger(__name__)


# ============================================================
# SCHEDULER ACTIVITY LOG — in-memory ring buffer for frontend
# ============================================================

_MAX_LOG_ENTRIES = 100  # keep last 100 job runs

# Each entry: {job_id, job_name, status, started_at, finished_at, duration_s, message}
_scheduler_logs: deque = deque(maxlen=_MAX_LOG_ENTRIES)


def _log_job_start(job_id: str, job_name: str) -> dict:
    """Record job start, returns entry dict to be updated on completion."""
    entry = {
        "job_id": job_id,
        "job_name": job_name,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "duration_s": None,
        "message": "",
        "_start_ts": time.time(),
    }
    _scheduler_logs.appendleft(entry)
    return entry


def _log_job_finish(entry: dict, status: str = "success", message: str = ""):
    """Update job entry with completion info."""
    entry["status"] = status
    entry["finished_at"] = datetime.now().isoformat()
    entry["duration_s"] = round(time.time() - entry.pop("_start_ts", time.time()), 1)
    entry["message"] = message


def get_scheduler_logs(limit: int = 50) -> list[dict]:
    """Get recent scheduler activity logs for frontend display."""
    return list(_scheduler_logs)[:limit]


class TaskScheduler:
    """APScheduler wrapper for StockQueen tasks"""
    
    def __init__(self):
        self.timezone = pytz.timezone(settings.timezone)
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
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

        # Job 5: Signal Outcome Tracker (Tue-Sat 09:50 NZT)
        self.scheduler.add_job(
            self._run_signal_outcome_collector,
            trigger=CronTrigger(day_of_week='tue-sat', hour=9, minute=50),
            id="signal_outcome_collector",
            name="Signal Outcome Tracker",
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

        # ===== 美股盘中任务 (03:00-08:00 NZT = EDT 10:00-15:00) =====

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

        # Job 10: Weekly Rotation (周六 10:00 NZT = 周五美股收盘后1小时, 用完整一周数据)
        self.scheduler.add_job(
            self._run_weekly_rotation,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=0),
            id="weekly_rotation",
            name="Weekly Momentum Rotation (after Fri close)",
            replace_existing=True
        )

        # Job 11: Pattern Statistics (周六 10:30 NZT)
        self.scheduler.add_job(
            self._run_pattern_stat_collector,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=30),
            id="pattern_stat_collector",
            name="Technical Pattern Statistics (weekly)",
            replace_existing=True
        )

        # Job 12: Sector Rotation Recorder (周六 10:30 NZT)
        self.scheduler.add_job(
            self._run_sector_rotation_collector,
            trigger=CronTrigger(day_of_week='sat', hour=10, minute=30),
            id="sector_rotation_collector",
            name="Sector Rotation Recorder (weekly)",
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

        logger.info("Scheduled jobs configured (V2.1 - AI enhanced, aligned to US market hours)")

    async def _run_news_pipeline(self):
        """Run news fetch and AI classification"""
        log = _log_job_start("news_pipeline", "新闻抓取+AI分类")
        logger.info("=" * 50)
        logger.info("Starting News Pipeline")
        logger.info("=" * 50)

        try:
            news_result = await run_news_fetcher()
            logger.info(f"News fetch result: {news_result}")
            ai_result = await run_ai_classification()
            logger.info(f"AI classification result: {ai_result}")
            logger.info("News pipeline completed successfully")
            _log_job_finish(log, "success", f"新闻抓取+AI分类完成")
        except Exception as e:
            logger.error(f"Error in news pipeline: {e}")
            _log_job_finish(log, "failed", str(e))
    
    async def _run_market_data_pipeline(self):
        """Run market data fetch and signal generation"""
        log = _log_job_start("market_data_pipeline", "市场数据+信号生成")
        logger.info("=" * 50)
        logger.info("Starting Market Data Pipeline")
        logger.info("=" * 50)

        try:
            market_result = await run_market_data_fetch()
            logger.info(f"Market data result: {market_result}")
            signals = await run_signal_generation()
            logger.info(f"Signal generation result: {len(signals)} signals generated")
            if signals:
                notification_result = await notify_signals_ready(signals)
                logger.info(f"Signal notification sent: {notification_result}")
            logger.info("Market data pipeline completed successfully")
            _log_job_finish(log, "success", f"生成 {len(signals)} 个信号")
        except Exception as e:
            logger.error(f"Error in market data pipeline: {e}")
            _log_job_finish(log, "failed", str(e))
    
    async def _run_geopolitical_scan(self):
        """Run geopolitical crisis scan (Hormuz crisis)"""
        log = _log_job_start("geopolitical_scan", "地缘政治扫描")
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
            _log_job_finish(log, "success", f"扫描完成, {len(signals)} 个信号")
        except Exception as e:
            logger.error(f"Error in geopolitical scan: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_confirmation_engine(self):
        """Run D+1 confirmation engine"""
        log = _log_job_start("confirmation_engine", "D+1确认引擎")
        logger.info("=" * 50)
        logger.info("Starting Confirmation Engine")
        logger.info("=" * 50)

        try:
            result = await run_confirmation_engine()
            logger.info(f"Confirmation engine result: {result}")
            _log_job_finish(log, "success", f"确认完成")
        except Exception as e:
            logger.error(f"Error in confirmation engine: {e}")
            _log_job_finish(log, "failed", str(e))
    
    # ===== RAG Knowledge Collector Handlers =====

    async def _run_signal_outcome_collector(self):
        """Track signal outcomes (1d/5d/20d returns)"""
        log = _log_job_start("signal_outcome", "信号结果追踪")
        try:
            from app.services.knowledge_collectors import SignalOutcomeCollector
            result = await SignalOutcomeCollector().run()
            logger.info(f"Signal outcome collector: {result}")
            _log_job_finish(log, "success", f"追踪完成: {result}")
        except Exception as e:
            logger.error(f"Error in signal outcome collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_news_outcome_collector(self):
        """Correlate news events with price movements"""
        log = _log_job_start("news_outcome", "新闻事件关联")
        try:
            from app.services.knowledge_collectors import NewsOutcomeCollector
            result = await NewsOutcomeCollector().run()
            logger.info(f"News outcome collector: {result}")
            _log_job_finish(log, "success", f"关联完成: {result}")
        except Exception as e:
            logger.error(f"Error in news outcome collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_pattern_stat_collector(self):
        """Compute technical pattern statistics"""
        log = _log_job_start("pattern_stat", "技术形态统计")
        try:
            from app.services.knowledge_collectors import PatternStatCollector
            result = await PatternStatCollector().run()
            logger.info(f"Pattern stat collector: {result}")
            _log_job_finish(log, "success", f"统计完成: {result}")
        except Exception as e:
            logger.error(f"Error in pattern stat collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_sector_rotation_collector(self):
        """Record sector/ETF rotation rankings"""
        log = _log_job_start("sector_rotation", "板块轮动记录")
        try:
            from app.services.knowledge_collectors import SectorRotationCollector
            result = await SectorRotationCollector().run()
            logger.info(f"Sector rotation collector: {result}")
            _log_job_finish(log, "success", f"记录完成: {result}")
        except Exception as e:
            logger.error(f"Error in sector rotation collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_knowledge_cleanup(self):
        """Clean up expired knowledge entries"""
        log = _log_job_start("knowledge_cleanup", "知识库清理")
        try:
            from app.services.knowledge_service import get_knowledge_service
            ks = get_knowledge_service()
            count = await ks.cleanup_expired()
            logger.info(f"Knowledge cleanup: removed {count} expired entries")
            _log_job_finish(log, "success", f"清理 {count} 条过期条目")
        except Exception as e:
            logger.error(f"Error in knowledge cleanup: {e}")
            _log_job_finish(log, "failed", str(e))

    # ===== AI Enhanced Collector Handlers =====

    async def _run_ai_sentiment_collector(self):
        """Run AI sentiment scoring across all tickers"""
        log = _log_job_start("ai_sentiment", "AI情绪评分")
        try:
            from app.services.knowledge_collectors import AISentimentCollector
            result = await AISentimentCollector().run()
            logger.info(f"AI sentiment collector: {result}")
            _log_job_finish(log, "success", f"评分完成: {result}")
        except Exception as e:
            logger.error(f"Error in AI sentiment collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_etf_flow_collector(self):
        """Track ETF fund flows"""
        log = _log_job_start("etf_flow", "ETF资金流")
        try:
            from app.services.knowledge_collectors import ETFFlowCollector
            result = await ETFFlowCollector().run()
            logger.info(f"ETF flow collector: {result}")
            _log_job_finish(log, "success", f"采集完成: {result}")
        except Exception as e:
            logger.error(f"Error in ETF flow collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_earnings_report_collector(self):
        """Analyze earnings reports from SEC EDGAR"""
        log = _log_job_start("earnings_report", "财报分析(SEC)")
        try:
            from app.services.knowledge_collectors import EarningsReportCollector
            result = await EarningsReportCollector().run()
            logger.info(f"Earnings report collector: {result}")
            _log_job_finish(log, "success", f"分析完成: {result}")
        except Exception as e:
            logger.error(f"Error in earnings report collector: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_institutional_holdings_collector(self):
        """Check 13F institutional holdings filings"""
        log = _log_job_start("institutional", "13F机构持仓")
        try:
            from app.services.knowledge_collectors import InstitutionalHoldingsCollector
            result = await InstitutionalHoldingsCollector().run()
            logger.info(f"Institutional holdings collector: {result}")
            _log_job_finish(log, "success", f"检查完成: {result}")
        except Exception as e:
            logger.error(f"Error in institutional holdings collector: {e}")
            _log_job_finish(log, "failed", str(e))

    # ===== Rotation Handlers =====

    async def _run_weekly_rotation(self):
        """Run weekly momentum rotation"""
        log = _log_job_start("weekly_rotation", "周度轮动评分")
        logger.info("=" * 50)
        logger.info("Starting Weekly Rotation")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_rotation
            result = await run_rotation()
            selected = result.get('selected', [])
            logger.info(f"Weekly rotation result: {selected}")
            if selected:
                await notify_rotation_summary(result)
            _log_job_finish(log, "success", f"选中: {', '.join(selected)}")
        except Exception as e:
            logger.error(f"Error in weekly rotation: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_daily_entry_check(self):
        """Run daily entry check for pending positions"""
        log = _log_job_start("daily_entry", "每日入场检查")
        try:
            from app.services.rotation_service import run_daily_entry_check
            signals = await run_daily_entry_check()
            logger.info(f"Daily entry check: {len(signals)} entry signals")
            for sig in signals:
                await notify_rotation_entry(sig)
            _log_job_finish(log, "success", f"{len(signals)} 个入场信号")
        except Exception as e:
            logger.error(f"Error in daily entry check: {e}")
            _log_job_finish(log, "failed", str(e))

    async def _run_daily_exit_check(self):
        """Run daily exit check for active positions"""
        log = _log_job_start("daily_exit", "每日退出检查")
        try:
            from app.services.rotation_service import run_daily_exit_check
            signals = await run_daily_exit_check()
            logger.info(f"Daily exit check: {len(signals)} exit signals")
            for sig in signals:
                await notify_rotation_exit(sig)
            _log_job_finish(log, "success", f"{len(signals)} 个退出信号")
        except Exception as e:
            logger.error(f"Error in daily exit check: {e}")
            _log_job_finish(log, "failed", str(e))

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
