#!/usr/bin/env python3
"""
铃铛策略 - 每日利润监控脚本
实时追踪日内交易进度，目标 $20,000 日利润
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

async def get_account_status():
    """获取当前账户状态"""
    from app.services.order_service import get_tiger_trade_client

    try:
        trader = get_tiger_trade_client("leverage")
        assets = await trader.get_account_assets()
        positions = await trader.get_positions()

        return {
            "timestamp": datetime.now().isoformat(),
            "equity": assets.get("net_liquidation", 0),
            "cash": assets.get("cash", 0),
            "buying_power": assets.get("buying_power", 0),
            "positions": positions,
            "position_count": len(positions),
            "unrealized_pnl": sum(p.get("unrealized_pnl", 0) for p in positions),
        }
    except Exception as e:
        logger.error(f"获取账户状态失败: {e}")
        return None

async def calculate_daily_metrics(initial_equity=999987.65):
    """计算日P&L和进度"""
    status = await get_account_status()
    if not status:
        return None

    current_equity = status["equity"]
    daily_pnl = current_equity - initial_equity
    daily_pnl_pct = (daily_pnl / initial_equity * 100) if initial_equity > 0 else 0

    profit_target = 20000.00
    progress_pct = (daily_pnl / profit_target * 100) if profit_target > 0 else 0

    return {
        "current_equity": current_equity,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
        "profit_target": profit_target,
        "progress_pct": min(100, progress_pct),  # Cap at 100%
        "positions": status["position_count"],
        "unrealized_pnl": status["unrealized_pnl"],
        "buying_power": status["buying_power"],
        "cash": status["cash"],
    }

def format_metrics(metrics):
    """格式化输出"""
    if not metrics:
        return "📊 暂无数据"

    pnl = metrics["daily_pnl"]
    pnl_color = "🟢" if pnl >= 0 else "🔴"
    progress = metrics["progress_pct"]

    output = f"""
╔══════════════════════════════════════════════════════════════════╗
║           铃铛策略 - 日内交易实时监控                           ║
╚══════════════════════════════════════════════════════════════════╝

📈 账户状态
  · 当前净值: ${metrics['current_equity']:,.2f}
  · 日P&L: {pnl_color} ${pnl:+,.2f} ({metrics['daily_pnl_pct']:+.2f}%)
  · 利润目标: $20,000.00
  · 完成进度: {progress:.1f}% [{int(progress)//10 * '█'}{' ' * (10-int(progress)//10)}]

💰 头寸管理
  · 活跃头寸: {metrics['positions']} 个
  · 未实现盈亏: ${metrics['unrealized_pnl']:+,.2f}
  · 现金: ${metrics['cash']:,.2f}
  · 购买力: ${metrics['buying_power']:,.2f}

⏰ 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} NZT
"""
    return output

async def monitor_loop(interval_seconds=300):
    """持续监控循环 (每5分钟输出一次)"""
    print("🚀 开启日内交易监控（每5分钟更新）...")

    while True:
        try:
            metrics = await calculate_daily_metrics()
            output = format_metrics(metrics)
            print(output)

            # 追加到日志文件
            log_file = Path("logs/intraday_trading_20260408.log")
            if log_file.exists():
                with open(log_file, "a") as f:
                    f.write(f"\n{output}\n")

        except Exception as e:
            logger.error(f"监控循环错误: {e}")

        await asyncio.sleep(interval_seconds)

async def main():
    """主函数"""
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        handlers=[
            logging.FileHandler("logs/monitor_daily_profit.log"),
            logging.StreamHandler(),
        ]
    )

    # 启动监控
    await monitor_loop(interval_seconds=300)  # 5分钟更新

if __name__ == "__main__":
    asyncio.run(main())
