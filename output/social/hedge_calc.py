import asyncio
import numpy as np
from app.services.massive_client import get_massive_client

async def main():
    client = get_massive_client()
    index_map = {
        "SH":  "SPY",
        "PSQ": "QQQ",
        "RWM": "IWM",
        "DOG": "DIA",
    }

    best_inv = None
    best_w = -999

    for inv_tk, idx_tk in index_map.items():
        try:
            data = await asyncio.wait_for(client.get_daily_history(idx_tk, days=30), timeout=20)
            if data is None or len(data) < 22:
                print(f"{idx_tk}: insufficient data")
                continue
            c = data["Close"].values
            r1w = (c[-1] / c[-5]) - 1
            r1m = (c[-1] / c[-22]) - 1
            w = -(0.4 * r1w + 0.6 * r1m)
            print(f"{inv_tk} -> {idx_tk}: close={c[-1]:.2f}  1W={r1w*100:+.1f}%  1M={r1m*100:+.1f}%  weakness={w:.4f}")
            if w > best_w:
                best_w = w
                best_inv = inv_tk
        except Exception as e:
            print(f"{inv_tk} -> {idx_tk}: error {e}")

    print(f"\n>>> Hedge Overlay = {best_inv} (weakness={best_w:.4f})")

    if best_inv:
        try:
            inv_data = await asyncio.wait_for(client.get_daily_history(best_inv, days=5), timeout=20)
            if inv_data is not None and len(inv_data) > 0:
                last = float(inv_data["Close"].values[-1])
                shares = int(154174 / last)
                print(f">>> {best_inv} price = ${last:.2f}")
                print(f">>> Hedge allocation $154,174 = {shares} shares")
        except Exception as e:
            print(f"Price fetch error: {e}")

asyncio.run(main())
