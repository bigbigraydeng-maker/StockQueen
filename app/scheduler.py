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
        """Setup scheduled jobs"""
        
        # Job 1: News Fetch + AI Classification
        # Runs at 06:30 NZ time daily
        self.scheduler.add_job(
            self._run_news_pipeline,
            trigger=CronTrigger(hour=6, minute=30),
            id="news_pipeline",
            name="News Fetch and AI Classification",
            replace_existing=True
        )
        
        # Job 2: Market Data Fetch
        # Runs at 07:00 NZ time daily (after news processing)
        self.scheduler.add_job(
            self._run_market_data_pipeline,
            trigger=CronTrigger(hour=7, minute=0),
            id="market_data_pipeline",
            name="Market Data Fetch and Signal Generation",
            replace_existing=True
        )
        
        # Job 3: D+1 Confirmation Engine
        # Runs at 06:30 NZ time daily
        self.scheduler.add_job(
            self._run_confirmation_engine,
            trigger=CronTrigger(hour=6, minute=30),
            id="confirmation_engine",
            name="D+1 Confirmation Check",
            replace_existing=True
        )

        # Job 4: Geopolitical Crisis Scan (Hormuz)
        # Runs at 07:30 NZ time daily (after market data pipeline)
        # Also runs at 23:00 NZ (US market open ~9:30 ET)
        self.scheduler.add_job(
            self._run_geopolitical_scan,
            trigger=CronTrigger(hour=7, minute=30),
            id="geopolitical_scan_morning",
            name="Geopolitical Crisis Scan (Morning)",
            replace_existing=True
        )
        self.scheduler.add_job(
            self._run_geopolitical_scan,
            trigger=CronTrigger(hour=23, minute=0),
            id="geopolitical_scan_usopen",
            name="Geopolitical Crisis Scan (US Open)",
            replace_existing=True
        )

        # ===== RAG Knowledge Collectors =====

        # Job 5: Signal Outcome Tracker (Daily 09:00)
        self.scheduler.add_job(
            self._run_signal_outcome_collector,
            trigger=CronTrigger(hour=9, minute=0),
            id="signal_outcome_collector",
            name="Signal Outcome Tracker",
            replace_existing=True
        )

        # Job 6: News Outcome Correlator (Daily 09:15)
        self.scheduler.add_job(
            self._run_news_outcome_collector,
            trigger=CronTrigger(hour=9, minute=15),
            id="news_outcome_collector",
            name="News Outcome Correlator",
            replace_existing=True
        )

        # Job 7: Pattern Statistics (Weekly Monday 09:30)
        self.scheduler.add_job(
            self._run_pattern_stat_collector,
            trigger=CronTrigger(day_of_week='mon', hour=9, minute=30),
            id="pattern_stat_collector",
            name="Technical Pattern Statistics",
            replace_existing=True
        )

        # Job 8: Sector Rotation Recorder (Weekly Monday 09:30)
        self.scheduler.add_job(
            self._run_sector_rotation_collector,
            trigger=CronTrigger(day_of_week='mon', hour=9, minute=30),
            id="sector_rotation_collector",
            name="Sector Rotation Recorder",
            replace_existing=True
        )

        # Job 9: Knowledge Cleanup (Daily 03:00)
        self.scheduler.add_job(
            self._run_knowledge_cleanup,
            trigger=CronTrigger(hour=3, minute=0),
            id="knowledge_cleanup",
            name="Knowledge Base Cleanup",
            replace_existing=True
        )

        # ===== Momentum Rotation =====

        # Job 10: Weekly Rotation (Monday 08:00)
        self.scheduler.add_job(
            self._run_weekly_rotation,
            trigger=CronTrigger(day_of_week='mon', hour=8, minute=0),
            id="weekly_rotation",
            name="Weekly Momentum Rotation",
            replace_existing=True
        )

        # Job 11: Daily Entry Check (Mon-Fri 08:30)
        self.scheduler.add_job(
            self._run_daily_entry_check,
            trigger=CronTrigger(day_of_week='mon-fri', hour=8, minute=30),
            id="daily_entry_check",
            name="Daily Entry Check",
            replace_existing=True
        )

        # Job 12: Daily Exit Check (Mon-Fri 08:30)
        self.scheduler.add_job(
            self._run_daily_exit_check,
            trigger=CronTrigger(day_of_week='mon-fri', hour=8, minute=35),
            id="daily_exit_check",
            name="Daily Exit Check",
            replace_existing=True
        )

        logger.info("Scheduled jobs configured (V1 + RAG + Rotation)")

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

    # ===== Rotation Handlers =====

    async def _run_weekly_rotation(self):
        """Run weekly momentum rotation"""
        logger.info("=" * 50)
        logger.info("Starting Weekly Rotation")
        logger.info("=" * 50)
        try:
            from app.services.rotation_service import run_rotation
            result = await run_rotation()
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
