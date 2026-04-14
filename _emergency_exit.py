"""
紧急止损：手动跑一次完整 exit pass（Pass A/B/C）
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def main():
    print("=== 执行紧急 exit pass ===\n")

    from app.services.intraday_service import run_intraday_exits_only
    from app.config.intraday_config import IntradayConfig as cfg

    result = await run_intraday_exits_only(enable_auto_execute=True)
    status = result.get("status")
    print(f"exit_only 状态: {status}")

    if status == "skipped":
        print(f"跳过原因: {result.get('reason')}")
        # 市场已关闭时强制跑
        if result.get("reason") == "market_closed":
            print("\n市场已关闭，强制执行 execute_intraday_trades...")
            from app.services.intraday_trader import execute_intraday_trades
            dummy = {"status": "ok", "round": 0, "all_scores": [], "top": [], "total_scored": 0}
            trade_result = await execute_intraday_trades(dummy, auto_execute=True)
            result = {"status": "ok", "trading": trade_result}
            status = "ok"

    if status == "ok":
        t = result.get("trading") or {}
        exits = t.get("exits") or []
        entries = t.get("entries") or []
        print(f"\n  exits={len(exits)}  entries={len(entries)}")
        for e in exits:
            import json
            print(f"  [EXIT] {json.dumps(e, default=str)[:200]}")
        if not exits:
            print("  (无平仓动作)")

    # 最终持仓
    print("\n=== 当前持仓 ===")
    from app.services.order_service import TigerTradeClient
    svc = TigerTradeClient(account_label="leverage")
    for p in await svc.get_positions():
        if p["quantity"] <= 0:
            continue
        avg = float(p.get("average_cost") or 0)
        pnl = float(p.get("unrealized_pnl") or 0)
        pnl_pct = pnl / (avg * p["quantity"]) * 100 if avg > 0 else 0
        print(f"  {p['ticker']:6s}  qty={p['quantity']}  avg=${avg:.2f}  pnl=${pnl:.2f}  pnl%={pnl_pct:.2f}%")

asyncio.run(main())
