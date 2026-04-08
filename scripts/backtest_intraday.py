"""
StockQueen - 铃铛短线策略回测框架
盘中30分钟评分系统的历史验证脚本

用法：
  python scripts/backtest_intraday.py \
    --tickers AAPL,MSFT,NVDA \
    --days 10 \
    --top-n 5 \
    --output backtest_results.json
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import numpy as np
import sys
import os

# 设置路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.intraday_config import IntradayConfig
from app.services.intraday_scorer import compute_intraday_score
from app.services.massive_client import get_massive_client
import pytz

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

ET = pytz.timezone('US/Eastern')


class IntradayBacktester:
    """盘中短线策略回测引擎"""

    def __init__(self, top_n: int = 5, lookback_days: int = 10):
        self.top_n = top_n
        self.lookback_days = lookback_days
        self.client = get_massive_client()

        # 交易统计
        self.trades: List[Dict] = []
        self.scores_history: List[Dict] = []

    async def fetch_intraday_data(
        self,
        ticker: str,
        days: int = 10
    ) -> Optional[Dict[str, np.ndarray]]:
        """拉取 ticker 的历史 30min bars"""
        try:
            arrays = await self.client.get_intraday_arrays(
                ticker, "minute", 30, days
            )
            return arrays
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")
            return None

    async def run_backtest(
        self,
        tickers: List[str],
        days: int = 10
    ) -> Dict:
        """
        回测盘中评分系统

        Args:
            tickers: 股票列表
            days: 回看天数

        Returns:
            回测结果（收益、Sharpe、最大回撤等）
        """
        logger.info(f"Starting backtest: {len(tickers)} tickers, {days} days")

        # 拉取所有 ticker 的数据
        all_data = {}
        tasks = [self.fetch_intraday_data(t, days) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for ticker, data in zip(tickers, results):
            if isinstance(data, dict) and data.get('close') is not None:
                all_data[ticker] = data

        if not all_data:
            logger.error("No data fetched, aborting backtest")
            return {"status": "error", "reason": "no_data"}

        logger.info(f"Fetched data for {len(all_data)} tickers")

        # SPY 用于 relative_flow
        spy_data = await self.fetch_intraday_data("SPY", days)

        # 逐个 30min bar 运行评分（模拟实时）
        portfolio_returns = []
        bar_count = len(all_data[list(all_data.keys())[0]]['close'])

        for bar_idx in range(1, bar_count):  # 从第二个 bar 开始
            # 对所有 ticker 评分（使用到目前为止的数据）
            scores_this_round = []

            for ticker, data in all_data.items():
                # 截取到当前 bar 的数据
                bar_data = {
                    'open': data['open'][:bar_idx+1],
                    'close': data['close'][:bar_idx+1],
                    'high': data['high'][:bar_idx+1],
                    'low': data['low'][:bar_idx+1],
                    'volume': data['volume'][:bar_idx+1],
                }

                # 计算评分
                spy_bar_data = None
                if spy_data:
                    spy_bar_data = {
                        'close': spy_data['close'][:bar_idx+1],
                    }

                try:
                    score_result = compute_intraday_score(bar_data, spy_bar_data)
                    score = score_result.get('total_score', 0)
                    price = float(data['close'][bar_idx])

                    scores_this_round.append({
                        'ticker': ticker,
                        'score': score,
                        'price': price,
                        'factors': score_result.get('factors', {}),
                    })
                except Exception as e:
                    logger.debug(f"Score error {ticker}: {e}")

            # 排序取 TOP_N
            scores_this_round.sort(key=lambda x: x['score'], reverse=True)
            top_tickers = scores_this_round[:self.top_n]

            # 记录评分
            self.scores_history.append({
                'bar_idx': bar_idx,
                'top': top_tickers,
                'all_count': len(scores_this_round),
            })

            # 简单的交易逻辑：买入 TOP_N，下一个 bar 卖出
            # （真实交易会有持仓、止盈止损等复杂逻辑）
            for item in top_tickers:
                ticker = item['ticker']
                entry_price = item['price']

                # 下一个 bar 的价格（作为卖出价）
                if bar_idx + 1 < len(all_data[ticker]['close']):
                    exit_price = float(all_data[ticker]['close'][bar_idx + 1])
                    ret = (exit_price - entry_price) / entry_price

                    self.trades.append({
                        'ticker': ticker,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'return': ret,
                        'bar_entry': bar_idx,
                        'bar_exit': bar_idx + 1,
                    })

                    portfolio_returns.append(ret)

        # 计算统计指标
        if not portfolio_returns:
            logger.warning("No trades generated, backtest inconclusive")
            return {
                "status": "warning",
                "reason": "no_trades",
                "trades_count": 0,
            }

        returns = np.array(portfolio_returns)
        total_return = np.prod(1 + returns) - 1
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = mean_return / std_return * np.sqrt(252 * 6.5)  # 年化（6.5小时 x 252天）

        # 最大回撤
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = np.min(drawdown)

        win_count = np.sum(returns > 0)
        win_rate = win_count / len(returns)

        return {
            "status": "ok",
            "summary": {
                "total_return": round(total_return * 100, 2),
                "mean_return_bps": round(mean_return * 10000, 1),
                "sharpe": round(sharpe, 3),
                "max_drawdown": round(max_drawdown * 100, 2),
                "win_rate": round(win_rate * 100, 2),
                "trades_count": len(self.trades),
                "winning_trades": int(win_count),
            },
            "trades": self.trades[:100],  # 返回前100笔交易
            "config": {
                "top_n": self.top_n,
                "lookback_days": self.lookback_days,
                "universe_size": len(all_data),
                "total_bars": bar_count,
            }
        }


async def main():
    """主回测流程"""
    import argparse

    parser = argparse.ArgumentParser(description="铃铛短线策略回测")
    parser.add_argument('--tickers', default='AAPL,MSFT,NVDA,GOOGL,AMZN',
                       help='股票列表（逗号分隔）')
    parser.add_argument('--days', type=int, default=10,
                       help='回看天数')
    parser.add_argument('--top-n', type=int, default=5,
                       help='每轮取前N名')
    parser.add_argument('--output', default='scripts/backtest_intraday_results.json',
                       help='输出文件路径')

    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(',')]

    logger.info(f"Config: {len(tickers)} tickers, {args.days} days, TOP_{args.top_n}")
    logger.info(f"Tickers: {', '.join(tickers[:10])}")

    # 运行回测
    backtester = IntradayBacktester(top_n=args.top_n, lookback_days=args.days)
    result = await backtester.run_backtest(tickers, days=args.days)

    # 输出结果
    print("\n" + "=" * 70)
    print("BACKTEST RESULT")
    print("=" * 70)

    if result.get('status') == 'ok':
        summary = result['summary']
        print(f"\nSummary:")
        print(f"  Total Return:  {summary['total_return']:7.2f}%")
        print(f"  Mean Return:   {summary['mean_return_bps']:7.1f} bps")
        print(f"  Sharpe Ratio:  {summary['sharpe']:7.3f}")
        print(f"  Max Drawdown:  {summary['max_drawdown']:7.2f}%")
        print(f"  Win Rate:      {summary['win_rate']:7.2f}%")
        print(f"  Trades:        {summary['trades_count']:7d}")
        print(f"  Winners:       {summary['winning_trades']:7d}")
    else:
        print(f"\nStatus: {result.get('status')}")
        print(f"Reason: {result.get('reason')}")

    # 保存到文件
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    logger.info(f"Results saved to {args.output}")

    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
