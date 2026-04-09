#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查平仓订单状态
"""

import asyncio
import sys
import os
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.services.order_service import TigerTradeClient
from app.config.intraday_config import IntradayConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_orders():
    """检查平仓订单状态"""

    print("\n" + "="*70)
    print("检查平仓订单状态")
    print("="*70)

    tiger = TigerTradeClient(account_label=IntradayConfig.ACCOUNT_LABEL)

    # 这些是刚才下的平仓订单 ID
    order_ids = [60, 61, 62, 63, 64, 65, 66, 67]

    print(f"\n[检查 {len(order_ids)} 个平仓订单]")

    for order_id in order_ids:
        try:
            status = await tiger.get_order_status(order_id)
            if status:
                print(f"\nOrder #{order_id}:")
                print(f"  状态: {status.get('status')}")
                print(f"  成交数: {status.get('filled_quantity')}")
                print(f"  平均价: ${status.get('avg_fill_price', 0):.2f}")
                print(f"  剩余: {status.get('remaining')}")
            else:
                print(f"\nOrder #{order_id}: 无法获取状态")
        except Exception as e:
            print(f"\nOrder #{order_id}: 错误 - {e}")

    # 检查当前持仓
    print(f"\n[当前持仓]")
    positions = await tiger.get_positions()

    if not positions:
        print("✅ 无持仓（平仓完成）")
    else:
        print(f"⚠️  还有 {len(positions)} 个持仓未平:")
        for pos in positions:
            ticker = pos.get('ticker')
            qty = pos.get('quantity')
            mkt_val = pos.get('market_value')
            print(f"  • {ticker}: {qty} 股 (${mkt_val:,.2f})")


if __name__ == '__main__':
    asyncio.run(check_orders())
