"""
StockQueen V1 - Task Scheduler
Scheduled tasks for daily operations
"""

import logging
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

        # Job 4b: Sync Tiger Order Status (Tue-Sat, every 30 min during trading hours NZT 01:00-09:30)
        self.scheduler.add_job(
            self._run_sync_tiger_orders,
            trigger=CronTrigger(day_of_week='tue-sat', hour='1-9', minute='*/30'),
            id="sync_tiger_orders",
            name="Sync Tiger Order Status",
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

        # Job 19: Backtest Pre-compute (周六 11:00 NZT = rotation后1小时, 预计算25种参数组合)
        self.scheduler.add_job(
            self._run_backtest_precompute,
            trigger=CronTrigger(day_of_week='sat', hour=11, minute=0),
            id="backtest_precompute",
            name="Backtest Pre-compute (25 combos, weekly cache refresh)",
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

        logger.info("Scheduled jobs configured (V3.1 - AI enhanced + auto param tuning, aligned to US market hours)")

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
            logger.error(f"Error in news pipeline: {e}")
    
    async def _run_market_data_pipeline(self):
        """Run market data fetch and signal generation"""
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
            logger.error(f"Error in market data pipeline: {e}")
    
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
            logger.error(f"Error in geopolitical scan: {e}")

    async def _run_confirmation_engine(self):
        """Run D+1 confirmation engine"""
        logger.info("=" * 50)
        logger.info("Starting Confirmation Engine")
        logger.info("=" * 50)
        
        try:
            result = await run_confirmation_engine()
            logger.info(f"Confirmation engine result: {result}")
            
        except Exception as e:
            logger.error(f"Error in confirmation engine: {e}")
    
    # ===== RAG Knowledge Collector Handlers =====

    async def _run_signal_outcome_collector(self):
        """Track signal outcomes (1d/5d/20d returns)"""
        logger.info("Starting Signal Outcome Collector")
        try:
            from app.services.knowledge_collectors import SignalOutcomeCollector
            result = await SignalOutcomeCollector().run()
            logger.info(f"Signal outcome collector: {result}")
        except Exception as e:
            logger.error(f"Error in signal outcome collector: {e}")

    async def _run_news_outcome_collector(self):
        """Correlate news events with price movements"""
        logger.info("Starting News Outcome Collector")
        try:
            from app.services.knowledge_collectors import NewsOutcomeCollector
            result = await NewsOutcomeCollector().run()
            logger.info(f"News outcome collector: {result}")
        except Exception as e:
            logger.error(f"Error in news outcome collector: {e}")

    async def _run_pattern_stat_collector(self):
        """Compute technical pattern statistics"""
        logger.info("Starting Pattern Stat Collector")
        try:
            from app.services.knowledge_collectors import PatternStatCollector
            result = await PatternStatCollector().run()
            logger.info(f"Pattern stat collector: {result}")
        except Exception as e:
            logger.error(f"Error in pattern stat collector: {e}")

    async def _run_sector_rotation_collector(self):
        """Record sector/ETF rotation rankings"""
        logger.info("Starting Sector Rotation Collector")
        try:
            from app.services.knowledge_collectors import SectorRotationCollector
            result = await SectorRotationCollector().run()
            logger.info(f"Sector rotation collector: {result}")
        except Exception as e:
            logger.error(f"Error in sector rotation collector: {e}")

    async def _run_knowledge_cleanup(self):
        """Clean up expired knowledge entries"""
        logger.info("Starting Knowledge Cleanup")
        try:
            from app.services.knowledge_service import get_knowledge_service
            ks = get_knowledge_service()
            count = await ks.cleanup_expired()
            logger.info(f"Knowledge cleanup: removed {count} expired entries")
        except Exception as e:
            logger.error(f"Error in knowledge cleanup: {e}")

    # ===== AI Enhanced Collector Handlers =====

    async def _run_ai_sentiment_collector(self):
        """Run AI sentiment scoring across all tickers"""
        logger.info("Starting AI Sentiment Collector")
        try:
            from app.services.knowledge_collectors import AISentimentCollector
            result = await AISentimentCollector().run()
            logger.info(f"AI sentiment collector: {result}")
        except Exception as e:
            logger.error(f"Error in AI sentiment collector: {e}")

    async def _run_etf_flow_collector(self):
        """Track ETF fund flows"""
        logger.info("Starting ETF Flow Collector")
        try:
            from app.services.knowledge_collectors import ETFFlowCollector
            result = await ETFFlowCollector().run()
            logger.info(f"ETF flow collector: {result}")
        except Exception as e:
            logger.error(f"Error in ETF flow collector: {e}")

    async def _run_earnings_report_collector(self):
        """Analyze earnings reports from SEC EDGAR"""
        logger.info("Starting Earnings Report Collector")
        try:
            from app.services.knowledge_collectors import EarningsReportCollector
            result = await EarningsReportCollector().run()
            logger.info(f"Earnings report collector: {result}")
        except Exception as e:
            logger.error(f"Error in earnings report collector: {e}")

    async def _run_institutional_holdings_collector(self):
        """Check 13F institutional holdings filings"""
        logger.info("Starting Institutional Holdings Collector")
        try:
            from app.services.knowledge_collectors import InstitutionalHoldingsCollector
            result = await InstitutionalHoldingsCollector().run()
            logger.info(f"Institutional holdings collector: {result}")
        except Exception as e:
            logger.error(f"Error in institutional holdings collector: {e}")

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
            logger.error(f"Error in auto param tune: {e}")

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
            logger.error(f"Error in weekly rotation: {e}")

    async def _run_daily_entry_check(self):
        """Run daily entry check for pending positions"""
        logger.info("Starting Daily Entry Check")
        try:
            from app.services.rotation_service import run_daily_entry_check
            signals = await run_daily_entry_check()
            logger.info(f"Daily entry check: {len(signals)} entry signals")

            for sig in signals:
                await notify_rotation_entry(sig)
        except Exception as e:
            logger.error(f"Error in daily entry check: {e}")

    async def _run_daily_exit_check(self):
        """Run daily exit check for active positions"""
        logger.info("Starting Daily Exit Check")
        try:
            from app.services.rotation_service import run_daily_exit_check
            signals = await run_daily_exit_check()
            logger.info(f"Daily exit check: {len(signals)} exit signals")

            for sig in signals:
                await notify_rotation_exit(sig)
        except Exception as e:
            logger.error(f"Error in daily exit check: {e}")

    async def _run_sync_tiger_orders(self):
        """Sync Tiger order status (filled/cancelled) for open orders"""
        logger.info("Starting Tiger order sync")
        try:
            from app.services.order_service import sync_tiger_orders
            result = await sync_tiger_orders()
            logger.info(f"Tiger order sync: {result}")
        except Exception as e:
            logger.error(f"Error syncing Tiger orders: {e}")

    # ===== Backtest Pre-compute Handler =====

    async def _run_backtest_precompute(self):
        """Pre-compute 25 backtest combos, store in cache for instant page load"""
        logger.info("=" * 50)
        logger.info("Starting Weekly Backtest Pre-compute (25 combos)")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_rotation_backtest
            import time as _time

            start_date = "2022-07-01"
            end_date = "2026-03-15"
            top_n_values = [2, 3, 4, 5, 6]
            bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

            from app.routers.web import _cache_set, _BACKTEST_TTL, _make_json_safe

            total = len(top_n_values) * len(bonus_values)
            count = 0
            t0 = _time.time()

            # Fetch data with extra lookback for custom date range slicing.
            # The 25 preset combos still use start_date (2022-07-01) for cache keys,
            # but _PREFETCHED_FULL needs data from earlier for momentum/MA lookback.
            from app.services.rotation_service import _fetch_backtest_data, set_prefetched_full
            prefetch_start = "2021-07-01"  # 1yr lookback before default start_date
            prefetched = await _fetch_backtest_data(prefetch_start, end_date)
            if "error" in prefetched:
                logger.error(f"Backtest pre-compute: data fetch failed: {prefetched['error']}")
                return

            # Cache full-range data for custom date range slicing
            set_prefetched_full(prefetched, prefetch_start, end_date)

            # Persist bt_fundamentals to Supabase so OHLCV-only startup can restore them
            if prefetched.get("bt_fundamentals"):
                from app.routers.web import _cache_set, _make_json_safe
                _cache_set("bt_fund:latest", _make_json_safe(prefetched["bt_fundamentals"]), 86400 * 30)
                logger.info(f"Cached bt_fundamentals to Supabase ({len(prefetched['bt_fundamentals'])} tickers)")

            for tn in top_n_values:
                for hb in bonus_values:
                    count += 1
                    try:
                        result = await run_rotation_backtest(
                            start_date=start_date,
                            end_date=end_date,
                            top_n=tn,
                            holding_bonus=hb,
                            _prefetched=prefetched,
                        )
                        if "error" not in result:
                            cache_key = f"bt_v2:{start_date}:{end_date}:{tn}:{hb}"
                            safe_result = _make_json_safe(result)
                            _cache_set(cache_key, safe_result, _BACKTEST_TTL)
                            logger.info(f"  [{count}/{total}] Top{tn}/HB{hb} → Sharpe={result.get('sharpe', 0):.2f}")
                        else:
                            logger.warning(f"  [{count}/{total}] Top{tn}/HB{hb} → error: {result['error']}")
                    except Exception as e:
                        logger.warning(f"  [{count}/{total}] Top{tn}/HB{hb} → exception: {e}")

            total_time = _time.time() - t0
            logger.info(f"Backtest pre-compute complete: {count} combos in {total_time:.0f}s")

        except Exception as e:
            logger.error(f"Error in backtest pre-compute: {e}")
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
