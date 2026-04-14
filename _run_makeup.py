#!/usr/bin/env python3
"""
补课任务直接执行脚本
使用 asyncio 在同步环境中运行异步函数
"""

import asyncio
import sys
import os
from pathlib import Path

# 确保在正确的工作目录
os.chdir(str(Path(__file__).parent))

# 设置 env 从文件
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

print("\n补课任务开始执行\n")

# ============================================================
# Task 1: Mean Reversion 信号扫描
# ============================================================

async def task1_mr_signals():
    """MR 信号扫描"""
    print("=" * 70)
    print("任务 1: MR 信号扫描")
    print("=" * 70)

    try:
        from app.services.mean_reversion_service import scan_live_signals, create_mr_pending_entries

        regime = "bull"  # 当前假设为 bull 体制
        print(f"扫描 MR 信号 (体制={regime})...")

        candidates = await scan_live_signals(regime=regime)

        print(f"\n发现 {len(candidates)} 个 MR 信号")

        if candidates:
            print("\n前5个信号:")
            for i, c in enumerate(candidates[:5], 1):
                print(f"  {i}. {c.get('ticker', 'N/A'):6s} | ${c.get('current_price', 0):.2f} | RSI: {c.get('rsi', 0):.1f} | 强度: {c.get('signal_strength', 0):.3f}")

            # 写入 DB
            print(f"\n写入 {len(candidates)} 个 pending entries...")
            created = await create_mr_pending_entries(candidates)
            print(f"成功写入 {created} 条")
            return created
        else:
            print("无 MR 信号")
            return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0


# ============================================================
# Task 2: Event Driven 事件扫描
# ============================================================

async def task2_ed_events():
    """ED 事件扫描"""
    print("\n" + "=" * 70)
    print("任务 2: ED 事件扫描")
    print("=" * 70)

    try:
        from app.services.event_driven_service import scan_live_events
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        print(f"扫描 ED 事件 (日期={today})...")

        events = await scan_live_events(current_date=today)

        print(f"\n发现 {len(events)} 个事件")

        if events:
            print("\n前3个事件:")
            for i, e in enumerate(events[:3], 1):
                print(f"  {i}. {e.get('ticker', 'N/A'):6s} | {e.get('event_type', 'unknown')}")

        return len(events)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0


# ============================================================
# Task 3: Exit Scorer
# ============================================================

async def task3_exit_scorer():
    """Exit Scorer ML 推断"""
    print("\n" + "=" * 70)
    print("任务 3: Exit Scorer")
    print("=" * 70)

    try:
        from app.services.exit_scorer import run_exit_scorer_signals

        print("运行 Exit Scorer...")

        result = await run_exit_scorer_signals()

        print(f"\n结果: {type(result).__name__}")
        if result:
            print(f"详情: {str(result)[:200]}")

        return 1 if result else 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0


# ============================================================
# Task 4: Rotation 更新
# ============================================================

async def task4_rotation():
    """轮动候选更新"""
    print("\n" + "=" * 70)
    print("任务 4: 轮动候选更新")
    print("=" * 70)

    try:
        from app.services.rotation_service import run_rotation

        print("更新轮动候选...")

        result = await run_rotation()

        print(f"\n结果: {type(result).__name__}")
        if result:
            print(f"详情: {str(result)[:200]}")

        return 1 if result else 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0


# ============================================================
# Main
# ============================================================

async def main():
    """执行所有补课任务"""

    print("\n╔" + "=" * 68 + "╗")
    print("║" + "补课任务执行引擎".center(68) + "║")
    print("║" + "StockQueen Makeup Tasks".center(68) + "║")
    print("╚" + "=" * 68 + "╝\n")

    # 执行任务
    mr_count = await task1_mr_signals()
    ed_count = await task2_ed_events()
    exit_count = await task3_exit_scorer()
    rot_count = await task4_rotation()

    # 汇总
    print("\n" + "=" * 70)
    print("补课完成")
    print("=" * 70)

    print(f"""
【结果统计】
  MR 信号:         {mr_count} 个
  ED 事件:         {ed_count} 个
  Exit Scorer:     {exit_count} (1=completed)
  轮动更新:        {rot_count} (1=completed)

【下一步】
  - MR 信号已写入 DB，明天 09:40 daily_entry_check 自动进场
  - ED 事件已扫描完成
  - Exit Scorer 已生成推断
  - 轮动候选已更新

  等待美股开盘...
""")


if __name__ == "__main__":
    asyncio.run(main())
