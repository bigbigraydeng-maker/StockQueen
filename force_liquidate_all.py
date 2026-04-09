#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强制平仓脚本：市价单全部平仓，确保成交
"""

import asyncio
import sys
import os
import io
from datetime import datetime, timedelta
import time

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.services.order_service import TigerTradeClient
from app.config.intraday_config import IntradayConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def force_liquidate_all():
    """强制平仓所有头寸 - 市价单，确保成交"""

    print("\n" + "="*70)
    print("🔴 强制清仓 - 市价单全部平仓")
    print("="*70)

    tiger = TigerTradeClient(account_label=IntradayConfig.ACCOUNT_LABEL)

    # ===== 第一步：获取当前持仓 =====
    print("\n[第 1/3 步] 获取当前持仓...")
    try:
        positions = await tiger.get_positions()
        if not positions:
            print("✅ 账户已无持仓")
            return True

        print(f"发现 {len(positions)} 个持仓")
        for pos in positions:
            ticker = pos.get('ticker')
            qty = pos.get('quantity')
            mkt_val = pos.get('market_value')
            print(f"  • {ticker}: {qty} 股 (${mkt_val:,.2f})")

    except Exception as e:
        print(f"❌ 获取持仓失败: {e}")
        return False

    # ===== 第二步：逐个市价平仓 =====
    print("\n[第 2/3 步] 下达市价卖单...")

    sell_orders = []
    for pos in positions:
        ticker = pos.get('ticker')
        qty = int(pos.get('quantity', 0))

        if qty <= 0:
            continue

        try:
            print(f"\n  平仓 {ticker}: {qty} 股")

            # 市价卖单 - 无限价，确保立即成交
            order_result = await tiger.place_sell_order(
                ticker=ticker,
                quantity=qty,
                limit_price=None  # 市价！
            )

            if order_result and order_result.get('order_id'):
                order_id = order_result.get('order_id')
                print(f"    ✅ 卖单已下: Order #{order_id}")
                sell_orders.append({
                    'ticker': ticker,
                    'qty': qty,
                    'order_id': order_id
                })
            else:
                print(f"    ❌ 下单失败: {order_result}")

        except Exception as e:
            print(f"    ❌ 异常: {e}")

    print(f"\n共下达 {len(sell_orders)} 个卖单")

    if not sell_orders:
        print("❌ 没有成功下单，清仓失败")
        return False

    # ===== 第三步：等待成交并验证 =====
    print("\n[第 3/3 步] 等待成交（30秒）...")

    # 等待市场处理订单
    for i in range(30, 0, -5):
        print(f"  等待中... {i}秒")
        await asyncio.sleep(5)

    # 验证成交
    print("\n[验证成交结果]")
    try:
        final_positions = await tiger.get_positions()

        if not final_positions:
            print("✅ 成功！账户已完全平仓")
            return True
        else:
            print(f"⚠️  还有 {len(final_positions)} 个持仓未平:")
            for pos in final_positions:
                ticker = pos.get('ticker')
                qty = pos.get('quantity')
                mkt_val = pos.get('market_value')
                print(f"  • {ticker}: {qty} 股 (${mkt_val:,.2f})")
            return False

    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False


async def main():
    success = await force_liquidate_all()

    print("\n" + "="*70)
    if success:
        print("✅ 清仓完成！账户已清空，可以在 NZT 3:00 重新建仓")
    else:
        print("⚠️  清仓可能未完全成功，请检查 Tiger 后台")
        print("    建议：登录 Tiger 后台手动取消未成交订单")
    print("="*70)

    return success


if __name__ == '__main__':
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
