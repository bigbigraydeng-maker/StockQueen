#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动测试脚本：验证铃铛系统（数据→评分→下单）
"""

import asyncio
import sys
import os
import io

# Windows 编码支持
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.services.intraday_service import run_intraday_trading_round
from app.config.intraday_config import IntradayConfig
from app.config.intraday_runtime import get_max_total_exposure
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_manual_lingdang():
    """手动运行一次完整的铃铛循环"""

    print("\n" + "="*70)
    print("🔔 铃铛系统 (Lingdang) 手动测试")
    print("="*70)

    print(f"\n[配置]")
    print(f"  ├─ 账户: {IntradayConfig.ACCOUNT_LABEL}")
    print(f"  ├─ TOP_N: {IntradayConfig.TOP_N}")
    print(f"  ├─ 自动下单: {IntradayConfig.AUTO_EXECUTE}")
    print(f"  ├─ 敞口上限(运行时): {get_max_total_exposure()}x")
    print(f"  └─ 单票上限: {IntradayConfig.MAX_POSITION_SIZE}%")

    try:
        # 运行完整的交易循环
        print(f"\n[执行] 启动盘中评分 + 自动交易...")
        result = await run_intraday_trading_round(enable_auto_execute=True)

        status = result.get('status')
        print(f"\n[结果] Status: {status}")

        if status == 'skipped':
            reason = result.get('reason')
            print(f"⏭️  系统跳过: {reason}")
            return

        if status != 'ok':
            print(f"❌ 执行失败: {result.get('error')}")
            return

        # ===== 数据获取 =====
        print(f"\n[1️⃣  数据获取]")
        top = result.get('top', [])
        if top:
            print(f"✅ 获取 TOP {len(top)} 评分股票:")
            for rank, item in enumerate(top, 1):
                ticker = item.get('ticker')
                score = item.get('total_score', 0)
                price = item.get('latest_price', 0)
                print(f"   {rank}. {ticker:6s} - 评分 {score:6.3f} @ ${price:.2f}")
        else:
            print(f"❌ 没有获取到 TOP 评分")
            return

        # ===== 交易执行 =====
        print(f"\n[2️⃣  交易执行]")
        trading = result.get('trading', {})

        entries = trading.get('entries', []) if trading else []
        exits = trading.get('exits', []) if trading else []

        if entries:
            print(f"✅ 建仓订单 ({len(entries)} 个):")
            for entry in entries:
                status_e = entry.get('status')
                ticker_e = entry.get('ticker', 'N/A')
                if status_e == 'ok':
                    order_id = entry.get('order_id')
                    qty = entry.get('qty')
                    price = entry.get('price')
                    print(f"   ✅ {ticker_e}: {qty} 股 @ ${price} (Order: {order_id})")
                else:
                    reason_e = entry.get('reason')
                    print(f"   ⏭️  {ticker_e}: {reason_e}")
        else:
            print(f"ℹ️  无新建仓 (可能已有持仓或风控阻止)")

        if exits:
            print(f"✅ 平仓订单 ({len(exits)} 个):")
            for exit_order in exits:
                ticker_x = exit_order.get('ticker')
                qty_x = exit_order.get('qty')
                price_x = exit_order.get('exit_price')
                reason_x = exit_order.get('exit_reason')
                pnl_x = exit_order.get('pnl', 0)
                print(f"   {ticker_x}: {qty_x} 股 @ ${price_x} (reason: {reason_x}, pnl: ${pnl_x:.0f})")
        else:
            print(f"ℹ️  无平仓订单")

        # ===== 风控摘要 =====
        print(f"\n[3️⃣  风控摘要]")
        trading_result = result.get('trading', {})
        risk = trading_result.get('risk_summary', {}) if trading_result else {}

        if risk:
            daily_pnl = risk.get('daily_pnl', 0)
            daily_pnl_pct = risk.get('daily_pnl_pct', 0)
            maint_ratio = risk.get('maintenance_ratio', 0)
            day_trades = risk.get('day_trades', 0)
            trading_allowed = risk.get('trading_allowed', False)

            print(f"  ├─ 日内 P&L: ${daily_pnl:.2f} ({daily_pnl_pct:.2f}%)")
            print(f"  ├─ 维持率: {maint_ratio:.1%}")
            print(f"  ├─ 日冲计数: {day_trades} / {risk.get('day_trade_limit', 3)}")
            print(f"  └─ 交易许可: {'✅ YES' if trading_allowed else '❌ NO'}")
        else:
            print(f"⚠️  无风控数据（交易结果: {trading_result}）")

        # ===== 持仓状态 =====
        print(f"\n[4️⃣  当前持仓]")
        positions = result.get('active_positions', {})
        if positions:
            print(f"✅ 活跃头寸 ({len(positions)} 个):")
            for ticker_p, pos in positions.items():
                qty_p = pos.get('qty')
                entry_price = pos.get('entry_price')
                current_price = pos.get('current_price', entry_price)
                hold_bars = pos.get('hold_bars', 0)
                unrealized = (current_price - entry_price) * qty_p

                print(f"   {ticker_p}: {qty_p} @ ${entry_price} (now ${current_price}) +${unrealized:.0f}, {hold_bars} bars")
        else:
            print(f"ℹ️  当前无持仓")

        # ===== 总结 =====
        print(f"\n" + "="*70)
        print(f"✅ 测试完成 - 系统正常运行")
        print(f"="*70)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(test_manual_lingdang())
