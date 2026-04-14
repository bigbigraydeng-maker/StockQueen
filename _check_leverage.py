"""Check current leverage state."""
import os, json, asyncio
from dotenv import load_dotenv
load_dotenv()

# 1. Check intraday_runtime config
from app.config.intraday_runtime import get_max_total_exposure, load_intraday_runtime

rt = load_intraday_runtime()
print(f"=== intraday_runtime.json ===")
print(f"  max_total_exposure: {rt.get('max_total_exposure')}")
print(f"  day_start_equity:   {rt.get('day_start_equity')}")
print(f"  day_start_date:     {rt.get('day_start_date')}")
print(f"  effective max_total_exposure (via get_max_total_exposure): {get_max_total_exposure()}")

async def main():
    from app.services.order_service import TigerTradeClient
    svc = TigerTradeClient(account_label="leverage")

    # 2. Account assets
    assets = await svc.get_account_assets()
    equity = float(assets.get('net_liquidation') or assets.get('equity') or 0)
    cash = float(assets.get('cash') or 0)
    gross_position_value = float(assets.get('gross_position_value') or 0)
    print(f"\n=== Tiger Account (leverage) ===")
    print(f"  net_liquidation:       ${equity:,.2f}")
    print(f"  cash:                  ${cash:,.2f}")
    print(f"  gross_position_value:  ${gross_position_value:,.2f}")

    # 3. Calculate actual leverage
    positions = await svc.get_positions() or []
    total_market_value = sum(
        abs(float(p.get('market_value') or 0) or
            float(p.get('quantity', 0)) * float(p.get('latest_price') or p.get('average_cost', 0)))
        for p in positions if int(p.get('quantity', 0) or 0) > 0
    )
    actual_leverage = total_market_value / equity if equity > 0 else 0
    print(f"  total_market_value:    ${total_market_value:,.2f}")
    print(f"  actual leverage:       {actual_leverage:.2f}x  (positions / equity)")

    # 4. Target leverage
    from app.config.intraday_config import IntradayConfig
    from app.config.intraday_runtime import get_max_total_exposure
    target = get_max_total_exposure()
    print(f"\n=== Target vs Actual ===")
    print(f"  target max_total_exposure: {target}x")
    print(f"  actual leverage:           {actual_leverage:.2f}x")
    print(f"  target $ exposure:         ${equity * target:,.0f}")
    print(f"  actual $ exposure:         ${total_market_value:,.0f}")
    print(f"  gap:                       ${(equity * target - total_market_value):,.0f}")

asyncio.run(main())
