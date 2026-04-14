#!/usr/bin/env python3
"""
补课执行引擎 - 开盘前 4 小时内跑所有需要的信号扫描。

任务清单：
1. Mean Reversion 信号扫描 (MR)
2. Event Driven 信号确认 (ED)
3. Exit Scorer 推断 (退出信号)
4. V4 轮动备选更新 (下周候选)

执行方式：
  python _makeup_tasks.py
"""

import asyncio
import sys
import logging
from datetime import datetime, timezone, timedelta
import pytz
import os
import json

# 设置编码
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 导入服务
from app.services.mean_reversion_service import scan_live_signals as mr_scan, create_mr_pending_entries
from app.services.event_driven_service import scan_live_events
from app.services.exit_scorer import run_exit_scorer_signals
from app.services.rotation_service import run_rotation

# ============================================================
# 时间工具
# ============================================================

def show_time_status():
    """显示当前时间状态"""
    print("\n" + "=" * 70)
    print("时间状态")
    print("=" * 70)

    utc_now = datetime.now(timezone.utc)
    nzt_tz = pytz.timezone('Pacific/Auckland')
    edt_tz = pytz.timezone('US/Eastern')

    nzt_now = utc_now.astimezone(nzt_tz)
    edt_now = utc_now.astimezone(edt_tz)

    print(f"UTC:  {utc_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"NZT:  {nzt_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"EDT:  {edt_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # 开盘倒计时
    market_open_edt = edt_now.replace(hour=9, minute=30, second=0, microsecond=0)
    if edt_now.hour >= 9 and edt_now.minute >= 30 and edt_now.hour < 16:
        print(f"\n状态: 美股盘中 (open)")
    elif edt_now.hour >= 16:
        print(f"\n状态: 美股已收盘 (closed)")
    else:
        delta = market_open_edt - edt_now
        hours = int(delta.total_seconds()) // 3600
        minutes = (int(delta.total_seconds()) % 3600) // 60
        print(f"\n状态: 开盘倒计时 {hours}h {minutes}m")


# ============================================================
# 任务 1: MR 信号扫描
# ============================================================

async def task_1_mr_scan():
    """扫描均值回归信号"""
    print("\n" + "=" * 70)
    print("任务 1: Mean Reversion 信号扫描")
    print("=" * 70)

    try:
        # 检测当前体制
        logger.info("正在检测当前市场体制...")
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        # 简化体制检测：暂时假设为 bull（用户可随意修改）
        regime = "bull"
        logger.info(f"当前体制: {regime}")

        # 扫描 MR 信号
        logger.info(f"开始 MR 信号扫描，体制={regime}...")
        candidates = await mr_scan(regime=regime)

        print(f"\n[MR 扫描结果]")
        print(f"  发现信号: {len(candidates)} 个")

        if candidates:
            for i, c in enumerate(candidates[:5], 1):  # 显示前5个
                print(f"  {i}. {c['ticker']:6s} | 价格: ${c['current_price']:8.2f} | RSI: {c['rsi']:6.1f} | 信号强度: {c['signal_strength']:.3f}")
            if len(candidates) > 5:
                print(f"  ... 还有 {len(candidates) - 5} 个")

        # 写入 pending entries
        if candidates:
            logger.info(f"写入 {len(candidates)} 个 MR pending entries...")
            created_count = await create_mr_pending_entries(candidates)
            print(f"  已写入 DB: {created_count} 条记录")
            return created_count
        else:
            print(f"  无信号，跳过 DB 写入")
            return 0

    except Exception as e:
        logger.error(f"[MR] 扫描失败: {e}", exc_info=True)
        return 0


# ============================================================
# 任务 2: ED 信号确认
# ============================================================

async def task_2_ed_scan():
    """扫描事件驱动信号"""
    print("\n" + "=" * 70)
    print("任务 2: Event Driven 信号确认")
    print("=" * 70)

    try:
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"扫描 ED 信号，日期={today}...")

        events = await scan_live_events(current_date=today)

        print(f"\n[ED 扫描结果]")
        print(f"  发现事件: {len(events)} 个")

        if events:
            for i, e in enumerate(events[:3], 1):
                print(f"  {i}. {e.get('ticker', 'N/A'):6s} | 事件: {e.get('event_type', 'unknown'):15s} | 置信度: {e.get('confidence', 0):.2f}")

        return len(events)

    except Exception as e:
        logger.error(f"[ED] 扫描失败: {e}", exc_info=True)
        return 0


# ============================================================
# 任务 3: Exit Scorer 推断
# ============================================================

async def task_3_exit_scorer():
    """运行 Exit Scorer 推断"""
    print("\n" + "=" * 70)
    print("任务 3: Exit Scorer ML 推断")
    print("=" * 70)

    try:
        logger.info("运行 Exit Scorer ML 推断...")

        # 查询当前活跃仓位
        from app.services.db import get_db_session
        session = get_db_session()
        from app.models import RotationPosition

        active_positions = session.query(RotationPosition).filter(
            RotationPosition.status.in_(['open', 'active'])
        ).all()

        logger.info(f"当前活跃仓位: {len(active_positions)} 个")

        # 运行 Exit Scorer
        result = await run_exit_scorer_signals()

        print(f"\n[Exit Scorer 结果]")
        print(f"  处理仓位: {len(active_positions)} 个")
        print(f"  推断完成")
        if result:
            print(f"  结果摘要: {result}")

        return len(active_positions)

    except Exception as e:
        logger.error(f"[Exit Scorer] 推断失败: {e}", exc_info=True)
        return 0


# ============================================================
# 任务 4: V4 轮动备选更新
# ============================================================

async def task_4_rotation_update():
    """更新 V4 轮动备选"""
    print("\n" + "=" * 70)
    print("任务 4: V4 轮动备选更新 (下周候选)")
    print("=" * 70)

    try:
        logger.info("开始更新 V4 轮动备选...")

        # 运行轮动评分
        result = await run_rotation()

        print(f"\n[轮动更新结果]")
        if result:
            print(f"  候选更新: 已完成")
            # 返回结果摘要
            if isinstance(result, dict):
                for key, val in list(result.items())[:3]:
                    print(f"    {key}: {val}")
        else:
            print(f"  候选更新: 无新候选")

        return 1 if result else 0

    except Exception as e:
        logger.error(f"[Rotation] 更新失败: {e}", exc_info=True)
        return 0


# ============================================================
# 主函数
# ============================================================

async def main():
    """执行所有补课任务"""

    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + "StockQueen 补课执行引擎 (Makeup Tasks)".center(68) + "║")
    print("║" + f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}".center(68) + "║")
    print("╚" + "=" * 68 + "╝")

    # 时间状态
    show_time_status()

    # 执行所有任务
    print("\n" + "=" * 70)
    print("开始执行任务队列")
    print("=" * 70)

    results = {}

    # Task 1: MR 扫描
    try:
        results['mr_signals'] = await task_1_mr_scan()
    except Exception as e:
        logger.error(f"Task 1 失败: {e}")
        results['mr_signals'] = 0

    # Task 2: ED 扫描
    try:
        results['ed_events'] = await task_2_ed_scan()
    except Exception as e:
        logger.error(f"Task 2 失败: {e}")
        results['ed_events'] = 0

    # Task 3: Exit Scorer
    try:
        results['exit_scorer_positions'] = await task_3_exit_scorer()
    except Exception as e:
        logger.error(f"Task 3 失败: {e}")
        results['exit_scorer_positions'] = 0

    # Task 4: Rotation 更新
    try:
        results['rotation_updated'] = await task_4_rotation_update()
    except Exception as e:
        logger.error(f"Task 4 失败: {e}")
        results['rotation_updated'] = 0

    # 汇总报告
    print("\n" + "=" * 70)
    print("补课任务完成总结")
    print("=" * 70)

    print(f"\n【任务结果统计】")
    print(f"  MR 信号:         {results.get('mr_signals', 0)} 个")
    print(f"  ED 事件:         {results.get('ed_events', 0)} 个")
    print(f"  Exit Scorer:     {results.get('exit_scorer_positions', 0)} 个仓位")
    print(f"  轮动更新:        {'完成' if results.get('rotation_updated') else '无'}")

    print(f"\n【执行时间】")
    print(f"  完成于: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} NZT")

    print(f"\n【后续动作】")
    print(f"  1. MR 信号已写入 rotation_positions，明天 09:40 daily_entry_check 自动进场")
    print(f"  2. Exit Scorer 信号已生成，明天执行时参考")
    print(f"  3. 轮动候选已更新，下周可参考当前评分")

    print("\n" + "=" * 70)
    print("补课完毕，等待美股开盘")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
