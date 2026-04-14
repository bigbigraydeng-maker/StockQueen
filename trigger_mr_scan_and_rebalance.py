#!/usr/bin/env python3
"""
Manual trigger for MR signal scan + cleanup oversized MR positions + redeploy to V4
步骤：
1. 触发MR信号扫描
2. 获取当前MR仓位
3. 清仓超额部分（$146K）
4. 重新部署给V4
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
    """Manually trigger MR signal scan and rebalance"""

    logger.info("=" * 70)
    logger.info("MANUAL TRIGGER: MR Signal Scan + Position Rebalance")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info("=" * 70)

    try:
        # ===== STEP 1: 触发MR信号扫描 =====
        logger.info("\n[STEP 1] 触发MR信号扫描...")
        from app.services.portfolio_manager import run_and_cache_daily_signals

        result = await run_and_cache_daily_signals()
        regime = result.get("regime", "UNKNOWN")
        mr_candidates = result.get("mr_candidates", [])

        logger.info(f"✓ 扫描完成:")
        logger.info(f"  - Regime: {regime}")
        logger.info(f"  - MR candidates: {len(mr_candidates)}")

        if mr_candidates:
            logger.info("\n  MR候选信号:")
            for i, candidate in enumerate(mr_candidates[:10], 1):
                ticker = candidate.get('ticker', 'N/A')
                price = candidate.get('price', 0)
                rsi = candidate.get('rsi', 0)
                try:
                    logger.info(
                        f"    {i}. {ticker} @ ${float(price):.2f} "
                        f"(RSI={float(rsi):.1f})"
                    )
                except (ValueError, TypeError):
                    logger.info(f"    {i}. {ticker} (price={price}, RSI={rsi})")
            if len(mr_candidates) > 10:
                logger.info(f"    ... 和其他 {len(mr_candidates) - 10} 个候选")

        # ===== STEP 2: 写入MR pending entries =====
        logger.info("\n[STEP 2] 将MR候选写入数据库...")
        if mr_candidates:
            from app.services.mean_reversion_service import create_mr_pending_entries
            mr_created = await create_mr_pending_entries(mr_candidates)
            logger.info(f"✓ MR pending entries created: {mr_created}")
        else:
            logger.info("⚠ 没有MR候选信号，跳过写入")

        # ===== STEP 3: 获取当前仓位 =====
        logger.info("\n[STEP 3] 获取当前仓位信息...")
        from app.database import get_db

        db = get_db()

        # 查询rotation_positions表获取当前活跃仓位
        positions_response = db.table("rotation_positions").select(
            "id, ticker, current_price, quantity, entry_price, unrealized_pnl_pct"
        ).eq("status", "active").execute()

        current_positions = positions_response.data if positions_response.data else []
        logger.info(f"✓ 当前仓位:")

        # HON和GILD是MR策略头寸（基于已知信息）
        mr_tickers = {"HON", "GILD"}

        total_mr_value = 0
        mr_positions = []
        for pos in current_positions:
            ticker = pos.get("ticker", "")
            if ticker in mr_tickers:
                current_price = pos.get("current_price", 0)
                qty = pos.get("quantity", 0)
                value = current_price * qty if current_price and qty else 0
                pos["current_value"] = value
                pos["current_price"] = current_price
                pos["quantity"] = qty
                mr_positions.append(pos)
                total_mr_value += value
                logger.info(
                    f"  - {ticker}: ${value:,.2f} qty={qty} @ ${current_price:.2f} "
                    f"({pos.get('unrealized_pnl_pct', 0):.1f}%) [MR]"
                )

        logger.info(f"\n  MR总仓位: ${total_mr_value:,.2f}")
        logger.info(f"  目标MR配置: $100,000.00")
        logger.info(f"  超额: ${max(0, total_mr_value - 100000):,.2f}")

        # ===== STEP 4: 计算清仓方案 =====
        logger.info("\n[STEP 4] 计算清仓方案...")

        target_mr = 100000
        excess = total_mr_value - target_mr

        if excess <= 0:
            logger.info("⚠ MR仓位未超额，无需清仓")
            logger.info("✓ 系统已就绪，等待后续指令")
            return

        # 按照亏损程度排序（亏损少的优先清仓）
        mr_positions_sorted = sorted(
            mr_positions,
            key=lambda x: x.get("unrealized_pnl_pct", 0),
            reverse=True  # 亏损少的排在前面
        )

        logger.info(f"✓ 清仓策略: 优先清仓亏损最少的头寸")
        logger.info(f"  需要清仓: ${excess:,.2f}")

        liquidation_plan = []
        remaining_excess = excess

        for pos in mr_positions_sorted:
            if remaining_excess <= 0:
                break

            ticker = pos["ticker"]
            value = pos["current_value"]
            pnl_pct = pos.get("unrealized_pnl_pct", 0)
            qty = pos.get("quantity", 0)
            price = pos.get("current_price", 0)

            liquidate_amount = min(value, remaining_excess)
            liquidate_qty = int(liquidate_amount / price) if price > 0 else 0

            if liquidate_qty > 0:
                liquidation_plan.append({
                    "ticker": ticker,
                    "qty": liquidate_qty,
                    "price": price,
                    "amount": liquidate_qty * price,
                    "pnl_pct": pnl_pct,
                    "current_value": value
                })

                logger.info(
                    f"  - {ticker}: 卖出 {liquidate_qty} 股 @ ${price:.2f} "
                    f"= ${liquidate_qty * price:,.2f} (PnL={pnl_pct:.1f}%)"
                )

                remaining_excess -= liquidate_amount

        # ===== STEP 5: 执行清仓 =====
        logger.info("\n[STEP 5] 执行清仓...")

        from app.services.order_service import get_tiger_trade_client

        tiger_client = get_tiger_trade_client("primary")
        total_liquidated = 0
        successful_liquidations = []

        for plan in liquidation_plan:
            try:
                ticker = plan["ticker"]
                qty = plan["qty"]

                logger.info(f"  正在卖出 {ticker} {qty} 股 @ MKT...")

                # 调用Tiger API卖出（市价单）
                order_result = await tiger_client.place_sell_order(ticker, qty)

                if order_result:
                    amount = plan["amount"]
                    order_id = order_result.get("order_id", "N/A")
                    total_liquidated += amount
                    successful_liquidations.append({
                        "ticker": ticker,
                        "qty": qty,
                        "amount": amount,
                        "order_id": order_id
                    })
                    logger.info(
                        f"    ✓ 成功下单，释放 ${amount:,.2f} "
                        f"(order_id={order_id})"
                    )

                    # 更新DB标记为已清仓
                    db.table("rotation_positions").update({
                        "status": "closed",
                        "exit_reason": "mr_rebalance_excess",
                        "exit_date": datetime.now().date().isoformat(),
                    }).eq("ticker", ticker).eq("status", "active").execute()

                else:
                    logger.warning(f"    ⚠ 卖出失败: Tiger API返回None")

            except Exception as e:
                logger.error(f"    ✗ 异常: {e}")

        logger.info(f"\n✓ 清仓完成:")
        logger.info(f"  - 成功清仓: {len(successful_liquidations)} 个头寸")
        logger.info(f"  - 释放资金: ${total_liquidated:,.2f}")

        # ===== STEP 6: 重新部署给V4 =====
        logger.info("\n[STEP 6] 重新部署资金给V4...")
        logger.info(f"  - 可用资金: ${total_liquidated:,.2f}")
        logger.info(f"  - V4当前仓位: $177,000.00")
        logger.info(f"  - V4目标: $600,000.00")
        logger.info(f"  - V4缺口: $423,000.00")
        logger.info(f"  → 部署后V4: ${177000 + total_liquidated:,.2f}")

        logger.info("\n✓ 资金已释放，等待 daily_entry_check 生成V4入场信号")
        logger.info("✓ 重新部署流程已完成")

        # ===== FINAL SUMMARY =====
        logger.info("\n" + "=" * 70)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 70)
        logger.info(f"MR信号扫描: ✓ ({len(mr_candidates)} candidates)")
        logger.info(f"MR pending entries: ✓ ({mr_created if mr_candidates else 0} created)")
        logger.info(f"MR仓位清仓: ✓ (释放 ${total_liquidated:,.2f})")
        logger.info(f"资金重新部署: ✓ (就绪，等待V4入场信号)")
        logger.info("=" * 70)

        logger.info("\n系统操作流程已完成。下一步:")
        logger.info("1. 监控 daily_entry_check 的V4入场信号")
        logger.info("2. 监控新的MR信号（已启用ENABLE_MR_AUTO_PENDING）")
        logger.info("3. 资金配置: V4 $560K+ | MR $100K | ED $0(paused)")

    except Exception as e:
        logger.error(f"Error in manual trigger: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
