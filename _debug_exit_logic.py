"""Simulate exit_passes logic locally to find why no exits fire."""
import os, asyncio, json
from dotenv import load_dotenv
load_dotenv()

async def main():
    from supabase import create_client
    sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

    # 1. Check partial_tickers state
    r = sb.table('cache_store').select('value').eq('key', 'intraday_strategy_state').limit(1).execute()
    state = r.data[0]['value'] if r.data else {}
    partial = state.get('partial_tickers', {})
    print(f"[STATE] et_date={state.get('et_date')}, partial_tickers={json.dumps(partial)}")

    # 2. Get positions from Tiger
    from app.services.order_service import TigerTradeClient
    svc = TigerTradeClient(account_label="leverage")
    positions = await svc.get_positions() or []
    print(f"\n[POSITIONS] {len(positions)} positions")

    # 3. Check universe
    from app.config.intraday_config import IntradayConfig
    universe = set(IntradayConfig.UNIVERSE)
    print(f"[CONFIG] PARTIAL_PROFIT_TRIGGER_PCT={IntradayConfig.PARTIAL_PROFIT_TRIGGER_PCT}")
    print(f"[CONFIG] PARTIAL_EXIT_FRACTION={IntradayConfig.PARTIAL_EXIT_FRACTION}")
    print(f"[CONFIG] FULL_STOP_LOSS_PCT={IntradayConfig.FULL_STOP_LOSS_PCT}")
    print(f"[CONFIG] AUTO_EXECUTE={IntradayConfig.AUTO_EXECUTE}")

    # 4. Check each position
    from app.services.intraday_trader import _pnl_pct_for_partial_profit, _pnl_pct_for_stop
    for pos in positions:
        ticker = pos.get('ticker') or pos.get('symbol', '')
        qty = int(pos.get('quantity', 0) or 0)
        if qty <= 0:
            continue
        in_universe = ticker in universe
        pnl_profit = _pnl_pct_for_partial_profit(pos)
        pnl_stop = _pnl_pct_for_stop(pos)
        trigger_profit = pnl_profit >= IntradayConfig.PARTIAL_PROFIT_TRIGGER_PCT
        trigger_stop = pnl_stop <= IntradayConfig.FULL_STOP_LOSS_PCT
        partial_blocked = partial.get(ticker, False)

        status_flags = []
        if not in_universe:
            status_flags.append("NOT_IN_UNIVERSE")
        if trigger_profit:
            status_flags.append("PROFIT_TRIGGER")
        if trigger_stop:
            status_flags.append("STOP_TRIGGER")
        if partial_blocked:
            status_flags.append("PARTIAL_BLOCKED")

        print(f"  {ticker:<6} qty={qty:<6} pnl_profit={pnl_profit*100:+.3f}% pnl_stop={pnl_stop*100:+.3f}% "
              f"in_univ={in_universe} flags={status_flags or 'none'}")

    # 5. Check market open
    from app.services.intraday_service import _is_market_open
    print(f"\n[MARKET] is_market_open={_is_market_open()}")

asyncio.run(main())
