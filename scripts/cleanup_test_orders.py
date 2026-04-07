#!/usr/bin/env python3
"""Cancel all test orders from leverage account."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.order_service import TigerTradeClient


async def cleanup():
    """Cancel all open orders."""
    client = TigerTradeClient(account_label="leverage")

    print("Fetching open orders...")
    open_orders = await client.get_open_orders()

    if not open_orders:
        print("No open orders to cancel.")
        return

    print(f"Found {len(open_orders)} open orders. Cancelling...")
    for order in open_orders:
        order_id = order.get('id')
        ticker = order.get('ticker')
        action = order.get('action')
        quantity = order.get('quantity')

        print(f"  Cancelling {ticker} {action} {quantity}x (ID={order_id})...")
        success = await client.cancel_order(order_id)
        if success:
            print(f"    [OK] Cancelled")
        else:
            print(f"    [FAIL] Could not cancel")

    print("\nFinal state:")
    final_orders = await client.get_open_orders()
    if final_orders:
        print(f"Still have {len(final_orders)} open orders")
    else:
        print("All test orders cancelled successfully!")


if __name__ == "__main__":
    asyncio.run(cleanup())
