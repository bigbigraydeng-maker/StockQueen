import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from app.services.order_service import TigerTradeClient
    svc = TigerTradeClient(account_label="leverage")

    print("=== 持仓 (leverage) ===")
    positions = await svc.get_positions()
    has_pos = False
    for p in positions:
        if p["quantity"] > 0:
            has_pos = True
            avg = float(p.get("average_cost") or 0)
            pnl = float(p.get("unrealized_pnl") or 0)
            pnl_pct = (pnl / (avg * p["quantity"]) * 100) if avg > 0 else 0
            print(f"  {p['ticker']:6s}  qty={p['quantity']}  avg=${avg:.2f}  pnl=${pnl:.2f}  pnl%={pnl_pct:.2f}%")
    if not has_pos:
        print("  (无持仓)")

    print()
    print("=== 挂单 ===")
    orders = await svc.get_open_orders()
    for o in orders:
        print(f"  {o['ticker']:6s}  {o['action']} qty={o['quantity']} filled={o['filled']} limit=${o['limit_price']} status={o['status']}")
    if not orders:
        print("  (无挂单)")

    print()
    print("=== 账户权益 ===")
    assets = await svc.get_account_assets()
    equity = float(assets.get("net_liquidation") or assets.get("equity") or 0)
    cash   = float(assets.get("cash") or 0)
    print(f"  net_liquidation: ${equity:,.2f}")
    print(f"  cash:            ${cash:,.2f}")

asyncio.run(main())
