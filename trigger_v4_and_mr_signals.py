#!/usr/bin/env python3
"""
Manual trigger for V4 daily_entry_check + MR/ED sub_strategy_scan
联合触发：
1. V4轮动进场检查 (daily_entry_check)
2. MR均值回归 + ED事件驱动扫描 (sub_strategy_scan)
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
    """Manually trigger V4 + MR signal generation"""

    logger.info("=" * 80)
    logger.info("MANUAL TRIGGER: V4 Daily Entry Check + MR/ED Sub-Strategy Scan")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 80)

    try:
        # ===== PART 1: V4 Daily Entry Check =====
        logger.info("\n" + "=" * 80)
        logger.info("[PART 1] V4 Rotation Daily Entry Check")
        logger.info("=" * 80)

        from app.services.rotation_service import run_daily_entry_check

        logger.info("Checking 18 pending_entry V4 candidates...")
        v4_signals = await run_daily_entry_check()

        logger.info(f"\n✓ V4 Daily Entry Check completed:")
        logger.info(f"  - Entry signals found: {len(v4_signals)}")

        if v4_signals:
            logger.info("\n  Entry Signals (ready to execute):")
            for i, sig in enumerate(v4_signals, 1):
                ticker = sig.get('ticker', 'N/A')
                price = sig.get('signal_price', 'N/A')
                logger.info(f"    {i}. {ticker} @ ${price}")

                # Send notifications
                try:
                    from app.services.notification_service import notify_rotation_entry
                    await notify_rotation_entry(sig)
                    logger.info(f"       -> Notification sent")
                except Exception as e:
                    logger.warning(f"       -> Notification failed: {e}")
        else:
            logger.info("  - No candidates met entry conditions yet")

        # ===== PART 2: MR + ED Sub-Strategy Scan =====
        logger.info("\n" + "=" * 80)
        logger.info("[PART 2] MR + ED Sub-Strategy Signal Scan")
        logger.info("=" * 80)

        from app.services.portfolio_manager import run_and_cache_daily_signals

        logger.info("Scanning MR (Mean Reversion) + ED (Event Driven) signals...")
        result = await run_and_cache_daily_signals()

        regime = result.get("regime", "UNKNOWN")
        mr_candidates = result.get("mr_candidates", [])
        ed_candidates = result.get("ed_candidates", [])

        logger.info(f"\n✓ Sub-Strategy Scan completed:")
        logger.info(f"  - Regime: {regime}")
        logger.info(f"  - MR candidates: {len(mr_candidates)}")
        logger.info(f"  - ED candidates: {len(ed_candidates)}")

        # ===== MR Signal Details =====
        if mr_candidates:
            logger.info("\n  MR Candidates (Mean Reversion):")
            for i, cand in enumerate(mr_candidates[:10], 1):
                ticker = cand.get('ticker', 'N/A')
                rsi = cand.get('rsi', 0)
                bb = cand.get('bb_position', 0)
                vol_ratio = cand.get('volume_ratio', 0)
                try:
                    logger.info(
                        f"    {i:2d}. {ticker:6s} | RSI={float(rsi):.1f} | "
                        f"BB={float(bb):.2f} | Vol={float(vol_ratio):.2f}x"
                    )
                except (ValueError, TypeError):
                    logger.info(f"    {i:2d}. {ticker:6s} (price data parsing)")

            if len(mr_candidates) > 10:
                logger.info(f"    ... 和其他 {len(mr_candidates) - 10} 个候选")

            # Write MR pending entries to DB
            mr_auto_pending = os.getenv("ENABLE_MR_AUTO_PENDING", "false").lower() == "true"
            if mr_auto_pending:
                logger.info("\n  Writing MR candidates to DB...")
                from app.services.mean_reversion_service import create_mr_pending_entries
                mr_created = await create_mr_pending_entries(mr_candidates)
                logger.info(f"    Created {mr_created} MR pending_entry positions")
            else:
                logger.info("\n  (ENABLE_MR_AUTO_PENDING=false, skipping DB write)")
        else:
            logger.info("  - No MR candidates found today")

        # ===== ED Signal Details =====
        if ed_candidates:
            logger.info(f"\n  ED Candidates (Event Driven):")
            for i, cand in enumerate(ed_candidates[:5], 1):
                ticker = cand.get('ticker', 'N/A')
                earnings_date = cand.get('earnings_date', 'N/A')
                logger.info(f"    {i}. {ticker:6s} | Earnings: {earnings_date}")

            if len(ed_candidates) > 5:
                logger.info(f"    ... 和其他 {len(ed_candidates) - 5} 个候选")
        else:
            logger.info("  - No ED candidates found (regime not suitable or already paused)")

        # ===== FINAL SUMMARY =====
        logger.info("\n" + "=" * 80)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 80)
        logger.info(f"V4 Entry Signals:  {len(v4_signals)} ready to execute")
        logger.info(f"MR Candidates:     {len(mr_candidates)} for review")
        logger.info(f"ED Candidates:     {len(ed_candidates)} (paused)")
        logger.info(f"Market Regime:     {regime}")
        logger.info("=" * 80)

        # ===== NEXT STEPS =====
        logger.info("\nNext Steps:")
        if v4_signals:
            logger.info(f"1. AUTO: {len(v4_signals)} V4 order(s) ready (AUTO_EXECUTE_ORDERS={os.getenv('AUTO_EXECUTE_ORDERS', 'false')})")
        else:
            logger.info("1. V4: Waiting for candidates to meet entry conditions")

        if mr_candidates:
            logger.info(f"2. MR: {len(mr_candidates)} candidates available for $102K deployment")
        else:
            logger.info("2. MR: No new candidates today")

        logger.info("3. ED: Currently paused (reserved budget for future use)")

    except Exception as e:
        logger.error(f"Error in manual trigger: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
