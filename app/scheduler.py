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
from app.services.signal_service import run_signal_generation
from app.services.signal_service import run_confirmation_engine
from app.services.notification_service import notify_signals_ready

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
        
        logger.info("Scheduled jobs configured")
    
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
