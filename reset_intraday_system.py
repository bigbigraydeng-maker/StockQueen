#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
紧急重置脚本：清空所有头寸，重置铃铛系统
"""

import asyncio
import sys
import os
import io

# Windows 编码支持
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.services.order_service import TigerTradeClient
from app.config.intraday_config import IntradayConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def reset_intraday_system():
    """紧急重置：平仓所有头寸"""

    print("\n" + "="*70)
    print("🔴 铃铛系统紧急重置")
    print("="*70)

    try:
        # 初始化 Tiger 客户端
        tiger = TigerTradeClient(account_label=IntradayConfig.ACCOUNT_LABEL)

        # 获取账户信息
        acct = await tiger.get_account_assets()
        if not acct:
            print("❌ 无法获取账户信息")
            return False

        equity = acct.get('net_liquidation', 0)
        print(f"\n[账户状态]")
        print(f"  ├─ 净值: ${equity:,.2f}")
        print(f"  ├─ 可用: ${acct.get('buying_power', 0):,.2f}")
        print(f"  └─ 现金: ${acct.get('cash', 0):,.2f}")

        # 获取所有持仓
        positions = await tiger.get_positions()

        if not positions:
            print(f"\n✅ 账户已无持仓（干净状态）")
            return True

        print(f"\n[发现 {len(positions)} 个持仓，开始清仓]")

        # 逐个平仓
        closed = 0
        failed = 0

        for pos in positions:
            ticker = pos.get('ticker')
            qty = pos.get('quantity', 0)
            mkt_val = pos.get('market_value', 0)

            if qty <= 0:
                continue

            try:
                print(f"\n  平仓: {ticker} x{qty} (市值 ${mkt_val:,.2f})")

                # 市价卖单
                order_result = await tiger.place_sell_order(
                    ticker=ticker,
                    quantity=int(qty),
                    limit_price=None  # 市价
                )

                if order_result and order_result.get('order_id'):
                    order_id = order_result.get('order_id')
                    print(f"    ✅ 订单已下: #{order_id}")
                    closed += 1
                else:
                    print(f"    ❌ 下单失败: {order_result}")
                    failed += 1

            except Exception as e:
                print(f"    ❌ 异常: {e}")
                failed += 1

        # 汇总
        print(f"\n[清仓结果]")
        print(f"  ├─ 成功: {closed} 个")
        print(f"  ├─ 失败: {failed} 个")

        if failed == 0:
            print(f"  └─ 状态: ✅ 完全清仓")
        else:
            print(f"  └─ 状态: ⚠️  部分清仓（请检查）")

        return failed == 0

    except Exception as e:
        print(f"\n❌ 重置失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = asyncio.run(reset_intraday_system())

    if success:
        print(f"\n" + "="*70)
        print("✅ 系统重置完成，已清空所有头寸")
        print("="*70)
        print("\n下一步: 等待 NZT 3:00 (EDT 10:00) 自动建仓")
        print("或手动执行: python test_manual_lingdang.py")

    sys.exit(0 if success else 1)
