"""
铃铛策略启动验证脚本
检查所有必要的配置和连接
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def verify_all() -> bool:
    """验证所有启动条件"""

    print("=" * 70)
    print("铃铛策略启动验证")
    print("=" * 70)

    all_pass = True

    # 1. 配置检查
    print("\n[1] 配置检查")
    print("-" * 70)
    try:
        from app.config.intraday_config import IntradayConfig as cfg

        print(f"  Auto Execute: {cfg.AUTO_EXECUTE}")
        print(f"  Account Label: {cfg.ACCOUNT_LABEL}")
        print(f"  Scan Interval: {cfg.SCAN_INTERVAL_MIN} min")
        print(f"  Universe Size: {len(cfg.UNIVERSE)} tickers")
        print(f"  TOP_N: {cfg.TOP_N}")
        print(f"  Max Position: {cfg.MAX_POSITION_SIZE*100}%")
        print(f"  Max Exposure: {cfg.MAX_TOTAL_EXPOSURE*100}%")

        if not cfg.AUTO_EXECUTE:
            print("  WARNING: AUTO_EXECUTE is False (信号模式)")
            print("  -> 需要改为 AUTO_EXECUTE=True 才能自动下单")
            all_pass = False
        else:
            print("  OK: AUTO_EXECUTE=True (自动交易模式)")

    except Exception as e:
        print(f"  ERROR: {e}")
        all_pass = False

    # 2. Tiger API 连接
    print("\n[2] Tiger API 连接检查")
    print("-" * 70)
    try:
        from app.services.order_service import get_tiger_trade_client

        trader = get_tiger_trade_client("leverage")
        assets = await trader.get_account_assets()

        equity = assets.get("net_liquidation", 0)
        print(f"  Account: {trader.account}")
        print(f"  Equity: ${equity:,.2f}")
        print(f"  OK: Tiger API connected")

    except Exception as e:
        print(f"  ERROR: Tiger API connection failed")
        print(f"  -> {str(e)[:100]}")
        print(f"  -> Check: .env contains TIGER_ACCOUNT_2, TIGER_ID_2, TIGER_PRIVATE_KEY_2")
        all_pass = False

    # 3. 数据库连接
    print("\n[3] 数据库连接检查")
    print("-" * 70)
    try:
        from app.database import get_db

        db = get_db()
        result = db.table("intraday_scores").select("count").execute()

        print(f"  Table: intraday_scores")
        print(f"  Rows: {len(result.data) if result.data else 0}")
        print(f"  OK: Database connected")

    except Exception as e:
        print(f"  ERROR: Database connection failed")
        print(f"  -> {str(e)[:100]}")
        all_pass = False

    # 4. 评分引擎
    print("\n[4] 评分引擎检查")
    print("-" * 70)
    try:
        import numpy as np
        from app.services.intraday_scorer import compute_intraday_score

        # 模拟数据
        test_bars = {
            'open': np.array([100, 101, 102, 103, 104] * 6),
            'close': np.array([101, 102, 103, 104, 105] * 6),
            'high': np.array([102, 103, 104, 105, 106] * 6),
            'low': np.array([99, 100, 101, 102, 103] * 6),
            'volume': np.array([1000000] * 30),
        }

        result = compute_intraday_score(test_bars)
        score = result.get('total_score', 0)

        print(f"  Test Score: {score:.2f}")
        print(f"  Factors: {len(result.get('factors', {}))}")
        print(f"  OK: Scoring engine works")

    except Exception as e:
        print(f"  ERROR: Scoring engine failed")
        print(f"  -> {str(e)[:100]}")
        all_pass = False

    # 5. 交易执行器
    print("\n[5] 交易执行器检查")
    print("-" * 70)
    try:
        from app.services.intraday_trader import IntradayTrader

        trader = IntradayTrader(account_label="leverage")

        print(f"  Trader initialized")
        print(f"  Has check_maintenance_ratio: {hasattr(trader, 'check_maintenance_ratio')}")
        print(f"  Has check_daily_loss_limit: {hasattr(trader, 'check_daily_loss_limit')}")
        print(f"  Has check_day_trade_limit: {hasattr(trader, 'check_day_trade_limit')}")
        print(f"  OK: Trader ready")

    except Exception as e:
        print(f"  ERROR: Trader initialization failed")
        print(f"  -> {str(e)[:100]}")
        all_pass = False

    # 总结
    print("\n" + "=" * 70)
    if all_pass:
        print("STATUS: ALL CHECKS PASSED - Ready to launch")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Make sure Tiger API is set to PAPER TRADING mode")
        print("  2. Open Dashboard at http://localhost:8000/dashboard")
        print("  3. Wait for next 30-min mark (10:00, 10:30, 11:00, etc)")
        print("  4. First trade will execute automatically")
        print("  5. Monitor dashboard for entries, exits, and risk metrics")
        return True
    else:
        print("STATUS: SOME CHECKS FAILED - Review errors above")
        print("=" * 70)
        return False


if __name__ == "__main__":
    result = asyncio.run(verify_all())
    sys.exit(0 if result else 1)
