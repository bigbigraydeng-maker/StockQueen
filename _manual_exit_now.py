"""Manually run intraday exits to trigger profit-taking NOW."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from app.services.intraday_service import run_intraday_exits_only
    print("Running intraday exits (auto_execute=True)...")
    result = await run_intraday_exits_only(enable_auto_execute=True)
    print(f"\nResult status: {result.get('status')}")
    if result.get('status') == 'skipped':
        print(f"  reason: {result.get('reason')}")
        return

    trading = result.get('trading', {})
    exits = trading.get('exits', [])
    print(f"  exits: {len(exits)}")
    for e in exits:
        print(f"    {e.get('ticker')} qty={e.get('qty')} reason={e.get('reason')} pnl={e.get('pnl_pct')}%")

    entries = trading.get('entries', [])
    print(f"  entries: {len(entries)}")
    for en in entries:
        print(f"    {en.get('ticker')} qty={en.get('qty')} reason={en.get('reason')}")

asyncio.run(main())
