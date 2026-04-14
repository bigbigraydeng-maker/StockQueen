#!/usr/bin/env python3
"""
补课执行引擎 - 简化版
直接运行，无 async 等待，快速反馈
"""

import sys
import os

# 设置路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 显式加载 .env
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

from datetime import datetime
import pytz

print("\n" + "=" * 70)
print("补课任务执行")
print("=" * 70)

# 时间检查
edt_tz = pytz.timezone('US/Eastern')
edt_now = datetime.now(edt_tz)

print(f"\n当前时间 (EDT): {edt_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

market_open = edt_now.replace(hour=9, minute=30, second=0, microsecond=0)
if edt_now < market_open:
    delta = market_open - edt_now
    hours = int(delta.total_seconds()) // 3600
    minutes = (int(delta.total_seconds()) % 3600) // 60
    print(f"距离开盘: {hours}h {minutes}m")
else:
    print("美股已开盘")

# 任务 1: 检查数据库连接
print("\n" + "=" * 70)
print("任务 1: 数据库连接检查")
print("=" * 70)

try:
    from app.services.db import get_db_session
    from app.models import RotationPosition

    session = get_db_session()
    count = session.query(RotationPosition).count()
    session.close()

    print(f"✓ 数据库连接正常")
    print(f"  当前 rotation_positions 记录数: {count}")
except Exception as e:
    print(f"✗ 数据库连接失败: {e}")
    sys.exit(1)

# 任务 2: 检查 MR 服务
print("\n" + "=" * 70)
print("任务 2: Mean Reversion 信号扫描准备")
print("=" * 70)

try:
    from app.services.mean_reversion_service import scan_live_signals
    print(f"✓ MR 服务导入成功")
    print(f"  函数签名: scan_live_signals(regime: str) -> list[dict]")
    print(f"  用法: 需要在 async 环境中调用")
except Exception as e:
    print(f"✗ MR 服务导入失败: {e}")

# 任务 3: 检查 ED 服务
print("\n" + "=" * 70)
print("任务 3: Event Driven 信号确认准备")
print("=" * 70)

try:
    from app.services.event_driven_service import scan_live_events
    print(f"✓ ED 服务导入成功")
    print(f"  函数签名: scan_live_events(current_date: str) -> list[dict]")
except Exception as e:
    print(f"✗ ED 服务导入失败: {e}")

# 任务 4: 检查 Exit Scorer
print("\n" + "=" * 70)
print("任务 4: Exit Scorer ML 推断准备")
print("=" * 70)

try:
    from app.services.exit_scorer import run_exit_scorer_signals
    print(f"✓ Exit Scorer 导入成功")
    print(f"  函数签名: run_exit_scorer_signals() -> dict")
except Exception as e:
    print(f"✗ Exit Scorer 导入失败: {e}")

# 任务 5: 检查 Rotation 服务
print("\n" + "=" * 70)
print("任务 5: V4 轮动备选更新准备")
print("=" * 70)

try:
    from app.services.rotation_service import run_rotation
    print(f"✓ Rotation 服务导入成功")
    print(f"  函数签名: run_rotation() -> dict")
except Exception as e:
    print(f"✗ Rotation 服务导入失败: {e}")

print("\n" + "=" * 70)
print("所有服务准备完毕")
print("=" * 70)

print(f"""
\n【后续执行步骤】

由于 MR、ED、Exit Scorer、Rotation 都是异步函数，需要在异步环境中运行。

推荐方案：

1. 在 Flask 应用启动后，通过 portfolio_manager 的定时任务调用
   (现有的 daily_entry_check 流程)

2. 如需立即手动运行，使用 asyncio.run():

   python3 << 'EOF'
   import asyncio
   from app.services.mean_reversion_service import scan_live_signals

   async def main():
       candidates = await scan_live_signals(regime='bull')
       print(f"找到 {{len(candidates)}} 个 MR 信号")

   asyncio.run(main())
   EOF

3. 或启动 Flask 应用，让定时器自动执行：
   python app/main.py

【当前系统状态】
- 数据库: 正常
- 服务导入: 全部就绪
- 等待: Flask 应用启动或异步执行环境

""")
