#!/usr/bin/env python3
"""
StockQueen - 大规模回测数据集自动构建（反向查找策略）
从 watchlist 股票出发，找出历史上成交量暴涨/暴跌的日期，作为回测数据点
"""

import yfinance as yf
import pandas as pd
import csv
import time
import logging
from datetime import datetime
from typing import Dict, List
from tqdm import tqdm

from app.config.pharma_watchlist import PHARMA_WATCHLIST
from app.config.settings import RiskConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

VOLUME_MULTIPLIER = RiskConfig.VOLUME_MULTIPLIER
MIN_GAIN_ABS = 0.08
REQUEST_DELAY = 0.4

FINANCING_EVENT_DATES = {
    "HALO": ["2021-02-24"],
}


def get_volume_spikes_for_ticker(ticker: str, company_name: str) -> List[Dict]:
    """
    获取单只股票的历史成交量暴涨事件
    返回符合条件的日期列表
    """
    start = "2019-01-01"
    end = "2024-12-31"
    
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        
        if df.empty or len(df) < 30:
            return []
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['Avg_Volume_30d'] = df['Volume'].rolling(window=30).mean()
        
        df = df.iloc[30:].copy()
        
        df['Volume_Multiplier'] = df['Volume'] / df['Avg_Volume_30d']
        df['Day_Change_Pct'] = (df['Close'] - df['Close'].shift(1)) / df['Close'].shift(1)
        
        condition = (
            (df['Volume_Multiplier'] >= VOLUME_MULTIPLIER) &
            (abs(df['Day_Change_Pct']) >= MIN_GAIN_ABS)
        )
        
        spike_rows = df[condition]
        
        results = []
        for idx, row in spike_rows.iterrows():
            date_str = idx.strftime('%Y-%m-%d')
            
            is_financing = False
            if ticker in FINANCING_EVENT_DATES:
                if date_str in FINANCING_EVENT_DATES[ticker]:
                    is_financing = True
            
            price_above_ma20 = float(row['Close']) > float(row['MA20']) if not pd.isna(row['MA20']) else False
            
            post_5d_return = None
            post_1d_return = None
            try:
                current_idx = df.index.get_loc(idx)
                entry_price = float(row['Close'])
                
                if current_idx + 1 < len(df):
                    next_day_price = float(df.iloc[current_idx + 1]['Close'])
                    post_1d_return = round((next_day_price - entry_price) / entry_price, 4)
                
                if current_idx + 5 < len(df):
                    exit_price = float(df.iloc[current_idx + 5]['Close'])
                    post_5d_return = round((exit_price - entry_price) / entry_price, 4)
            except:
                pass
            
            signal_triggered = False
            signal_rating = 'NONE'
            if row['Day_Change_Pct'] >= MIN_GAIN_ABS and row['Volume_Multiplier'] >= VOLUME_MULTIPLIER:
                signal_triggered = True
                signal_rating = 'HIGH' if price_above_ma20 else 'MEDIUM'
            
            results.append({
                'ticker': ticker,
                'company': company_name,
                'event_date': idx.strftime('%Y%m%d'),
                'actual_date': date_str,
                'event_type': 'volume_spike',
                'day_gain_pct': round(float(row['Day_Change_Pct']) * 100, 2),
                'volume_multiplier': round(float(row['Volume_Multiplier']), 2),
                'price_above_ma20': price_above_ma20,
                'ma20': round(float(row['MA20']), 2) if not pd.isna(row['MA20']) else 0.0,
                'signal_triggered': signal_triggered,
                'signal_rating': signal_rating,
                'is_financing_event': is_financing,
                'post_1d_return': post_1d_return,
                'post_5d_return': post_5d_return,
                'notes': 'financing_event' if is_financing else ''
            })
        
        return results
        
    except Exception as e:
        logger.warning(f"获取 {ticker} 数据失败: {e}")
        return []


def build_dataset(target_count: int = 100):
    """构建回测数据集"""
    logger.info(f"开始构建回测数据集（反向查找策略），目标: {target_count}个有效事件")
    
    all_results = []
    
    small_cap_tickers = [
        "SAVA", "ACAD", "HALO", "KRTX", "ARQT", "IMVT", "KRYS", 
        "RXRX", "BEAM", "EDIT", "NTLA", "CRSP", "PTCT", "BLUE", 
        "NBIX", "SRPT", "EXEL", "INCY", "JAZZ", "SGEN",
        "VKTX", "ARWR", "IONS", "ALNY", "BMRN", "RARE", "PCVX",
        "MRNA", "NVAX", "BNTX", "ADPT", "FATE", "CARV", "TWST",
        "GCT", "ZYME", "ABSI", "SDGR", "PRCT", "CERE", "XFOR",
        "AUTL", "TCRR", "ALLO", "RGNX", "KOD", "VIR", "ADAG", "MOR"
    ]
    
    logger.info(f"优先处理小盘股: {len(small_cap_tickers)} 只")
    
    for ticker in tqdm(small_cap_tickers, desc="处理小盘股"):
        if len(all_results) >= target_count * 2:
            break
        
        company_name = PHARMA_WATCHLIST.get(ticker, ticker)
        results = get_volume_spikes_for_ticker(ticker, company_name)
        
        all_results.extend(results)
        logger.info(f"{ticker} 找到 {len(results)} 个异动事件")
        
        time.sleep(REQUEST_DELAY)
    
    if len(all_results) < target_count:
        logger.info(f"小盘股只找到 {len(all_results)} 个事件，继续处理其他股票")
        for ticker in tqdm(PHARMA_WATCHLIST.keys(), desc="处理剩余股票"):
            if ticker in small_cap_tickers:
                continue
            if len(all_results) >= target_count * 2:
                break
            
            company_name = PHARMA_WATCHLIST.get(ticker, ticker)
            results = get_volume_spikes_for_ticker(ticker, company_name)
            
            all_results.extend(results)
            time.sleep(REQUEST_DELAY)
    
    all_results = all_results[:target_count * 2]
    
    if all_results:
        filename = f"backtest_results_{datetime.now().strftime('%Y%m%d')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'ticker', 'company', 'event_date', 'actual_date', 'event_type',
                'day_gain_pct', 'volume_multiplier',
                'price_above_ma20', 'ma20', 'signal_triggered', 'signal_rating',
                'is_financing_event', 'post_1d_return', 'post_5d_return', 'notes'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_results)
        
        logger.info(f"结果已保存到: {filename}")
    
    print_statistics(all_results)
    
    return all_results


def print_statistics(results: List[Dict]):
    """打印统计报告"""
    if not results:
        logger.warning("没有数据生成统计报告")
        return
    
    print("\n" + "=" * 60)
    print("StockQueen 回测统计报告（反向查找策略）")
    print("=" * 60)
    
    total = len(results)
    print(f"\n总事件数: {total}")
    
    tickers_used = list(set(r['ticker'] for r in results))
    print(f"涉及股票: {len(tickers_used)} 只")
    
    financing_events = [r for r in results if r.get('is_financing_event', False)]
    print(f"融资事件（已标记）: {len(financing_events)} 个")
    
    valid_results = [r for r in results if not r.get('is_financing_event', False)]
    print(f"有效事件（排除融资）: {len(valid_results)} 个")
    
    long_signals = [r for r in valid_results if r['day_gain_pct'] >= 0]
    short_signals = [r for r in valid_results if r['day_gain_pct'] < 0]
    
    print(f"做多事件（上涨）: {len(long_signals)} 个")
    print(f"做空事件（下跌）: {len(short_signals)} 个")
    
    triggered = [r for r in valid_results if r['signal_triggered']]
    print(f"\n触发信号: {len(triggered)} 个 (触发率 {len(triggered)/len(valid_results)*100:.1f}%)")
    
    if triggered:
        high_count = sum(1 for r in triggered if r['signal_rating'] == 'HIGH')
        medium_count = sum(1 for r in triggered if r['signal_rating'] == 'MEDIUM')
        avg_gain = sum(r['day_gain_pct'] for r in triggered) / len(triggered)
        avg_vol = sum(r['volume_multiplier'] for r in triggered) / len(triggered)
        
        print(f"├── HIGH rating: {high_count} 个")
        print(f"└── MEDIUM rating: {medium_count} 个")
        print(f"平均涨跌幅（触发日）: {avg_gain:.2f}%")
        print(f"平均成交量倍数: {avg_vol:.2f}x")
        
        returns = [r['post_5d_return'] for r in triggered if r['post_5d_return'] is not None]
        if returns:
            avg_return = sum(returns) / len(returns) * 100
            print(f"触发后5日平均收益: {avg_return:.2f}%")
        
        returns_1d = [r['post_1d_return'] for r in triggered if r['post_1d_return'] is not None]
        if returns_1d:
            avg_return_1d = sum(returns_1d) / len(returns_1d) * 100
            print(f"触发后次日平均收益: {avg_return_1d:.2f}%")
    
    print(f"\n--- 股票分布 ---")
    ticker_counts = {}
    for r in valid_results:
        ticker_counts[r['ticker']] = ticker_counts.get(r['ticker'], 0) + 1
    
    for ticker, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"{ticker}: {count} 个事件")
    
    print("\n" + "=" * 60)


def main():
    """主函数"""
    build_dataset(target_count=100)


if __name__ == "__main__":
    main()
