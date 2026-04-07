#!/usr/bin/env python3
"""Close all test positions in leverage account."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.order_service import TigerTradeClient


async def close_all():
    """Close all positions by selling."""
    client = TigerTradeClient(account_label="leverage")

    print("Fetching current positions...")
    positions = await client.get_positions()

    if not positions:
        print("No positions to close.")
        return

    print(f"Found {len(positions)} position(s). Closing...")
    for pos in positions:
        ticker = pos.get('ticker')
        quantity = pos.get('quantity')

        if quantity <= 0:
            continue

        print(f"  Selling {ticker} {quantity}x (MKT)...")
        result = await client.place_sell_order(ticker=ticker, quantity=quantity)
        if result and result.get('order_id'):
            print(f"    [OK] Sell order placed: ID={result.get('order_id')}")
        else:
            print(f"    [FAIL] Could not place sell order")

    print("\nFinal state:")
    final_positions = await client.get_positions()
    if final_positions:
        print(f"Still have {len(final_positions)} position(s):")
        for pos in final_positions:
            print(f"   {pos.get('ticker')}: {pos.get('quantity')}x")
    else:
        print("All positions closed successfully!")


if __name__ == "__main__":
    asyncio.run(close_all())
