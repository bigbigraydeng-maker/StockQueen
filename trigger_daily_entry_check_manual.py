#!/usr/bin/env python3
"""
Manual trigger for daily_entry_check
直接调用entry check逻辑，无需等待scheduler
"""

import asyncio
import os
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    """Manually trigger daily_entry_check"""

    logger.info("=" * 60)
    logger.info(f"MANUAL TRIGGER: daily_entry_check")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    try:
        # Import rotation service
        from app.services.rotation_service import run_daily_entry_check
        from app.services.notification_service import notify_rotation_entry

        logger.info("Starting daily entry check...")

        # Run the check
        signals = await run_daily_entry_check()

        logger.info(f"✓ Daily entry check completed: {len(signals)} entry signal(s)")

        if signals:
            logger.info("\nEntry Signals Found:")
            for i, sig in enumerate(signals, 1):
                logger.info(f"  {i}. {sig.get('ticker', 'N/A')} @ ${sig.get('signal_price', 'N/A'):.2f}")

                # Send notifications
                try:
                    await notify_rotation_entry(sig)
                    logger.info(f"     ✓ Notification sent")
                except Exception as e:
                    logger.warning(f"     ⚠ Notification failed: {e}")
        else:
            logger.info("No entry signals found")

        logger.info("\n" + "=" * 60)
        logger.info("MANUAL TRIGGER COMPLETE")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error in manual trigger: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
