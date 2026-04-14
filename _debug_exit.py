"""
诊断铃铛 Pass A 为何没有触发止损
"""
import asyncio, json
from dotenv import load_dotenv
load_dotenv()

async def main():
    from app.services.order_service import TigerTradeClient
    from app.services.intraday_trader import _pnl_pct_for_stop, _pnl_components_from_position
    from app.config.intraday_config import IntradayConfig as cfg

    tiger = TigerTradeClient(account_label="leverage")
    positions = await tiger.get_positions()

    print("=== 原始持仓字段（MU / RDDT）===")
    for p in positions:
        if p.get("quantity", 0) <= 0:
            continue
        ticker = p.get("ticker") or p.get("symbol")
        if ticker not in ("MU", "RDDT"):
            continue
        print(f"\n[{ticker}] raw keys: {list(p.keys())}")
        for k, v in p.items():
            print(f"  {k}: {v}")

    print()
    print("=== Pass A 止损逻辑模拟 ===")
    universe = set(cfg.UNIVERSE)
    print(f"UNIVERSE 大小: {len(universe)}  包含 MU={('MU' in universe)}  RDDT={('RDDT' in universe)}")
    print(f"FULL_STOP_LOSS_PCT: {cfg.FULL_STOP_LOSS_PCT} ({cfg.FULL_STOP_LOSS_PCT*100:.1f}%)")
    print()

    for p in positions:
        if p.get("quantity", 0) <= 0:
            continue
        ticker = p.get("ticker") or p.get("symbol")
        qty = int(p.get("quantity", 0) or 0)
        avg = float(p.get("average_cost", 0) or 0)
        px, ur = _pnl_components_from_position(p)
        pnl_stop = _pnl_pct_for_stop(p)
        in_universe = ticker in universe

        flag = ""
        if not in_universe:
            flag = "[SKIP: not in universe]"
        elif qty <= 0 or avg <= 0:
            flag = "[SKIP: qty/avg=0]"
        elif pnl_stop <= cfg.FULL_STOP_LOSS_PCT:
            flag = "<<< SHOULD STOP LOSS >>>"
        else:
            flag = f"[pass: pnl={pnl_stop*100:.3f}% > threshold {cfg.FULL_STOP_LOSS_PCT*100:.1f}%]"

        print(f"  {ticker:6s}  in_universe={in_universe}  qty={qty}  avg=${avg:.2f}  "
              f"pct_px={px*100:.3f}%  pct_ur={ur*100:.3f}%  stop_pnl={pnl_stop*100:.3f}%  {flag}")

    print()
    print("=== 账户信息 ===")
    from app.services.intraday_trader import IntradayTrader
    trader = IntradayTrader(account_label="leverage")
    acct = await trader.get_account_info()
    print(json.dumps(acct, indent=2, default=str))

asyncio.run(main())
