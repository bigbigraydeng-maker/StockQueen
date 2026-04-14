"""
测试 Scheduler 是否能成功注册 intraday_exit_passes
"""
import os
os.environ.setdefault("WORKER_ROLE", "all")

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

try:
    from app.scheduler import TaskScheduler
    ts = TaskScheduler()
    jobs = ts.scheduler.get_jobs()
    print(f"\n已注册 {len(jobs)} 个 jobs:")
    for j in jobs:
        print(f"  {j.id:40s} next={j.next_run_time}")
    
    target = [j for j in jobs if j.id == "intraday_exit_passes"]
    print()
    if target:
        print(">>> intraday_exit_passes 注册成功 ✅")
    else:
        print(">>> intraday_exit_passes 未注册 ❌")
        
    scoring = [j for j in jobs if j.id == "intraday_scoring"]
    if scoring:
        print(f">>> intraday_scoring trigger: {scoring[0].trigger}")
        
except Exception as e:
    import traceback
    print(f"Scheduler 初始化失败: {e}")
    traceback.print_exc()
