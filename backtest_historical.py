#!/usr/bin/env python3
"""
StockQueen 回测验证系统
使用历史重大事件验证信号逻辑
"""

import yfinance as yf
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import Counter

# 导入配置
from app.config import RiskConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST


# 信号触发条件 - 使用RiskConfig配置
PHARMA_LONG_MIN_GAIN = RiskConfig.LONG_MIN_GAIN
PHARMA_SHORT_MIN_DROP = RiskConfig.SHORT_MIN_DROP
PHARMA_VOLUME_MULTIPLIER = RiskConfig.VOLUME_MULTIPLIER
PHARMA_MIN_MARKET_CAP = RiskConfig.MIN_MARKET_CAP
PHARMA_MAX_MARKET_CAP = RiskConfig.MAX_MARKET_CAP


# ========== Pharma历史事件数据 ==========
PHARMA_HISTORICAL_EVENTS = [
    # === 做多案例 ===
    {
        "ticker": "MRNA",
        "date": "2020-11-16",
        "event": "Phase 3 COVID Vaccine Positive Results (94.5% efficacy)",
        "event_type": "Phase3_Positive",
        "expected_signal": "long"
    },
    {
        "ticker": "PFE",
        "date": "2020-11-09",
        "event": "Pfizer COVID Vaccine Positive Phase 3 Results",
        "event_type": "Phase3_Positive", 
        "expected_signal": "long"
    },
    {
        "ticker": "SRPT",
        "date": "2023-06-22",
        "event": "FDA Approved Elevidys for Duchenne Muscular Dystrophy",
        "event_type": "FDA_Approval",
        "expected_signal": "long"
    },
    {
        "ticker": "MRNA",
        "date": "2022-06-08",
        "event": "Moderna COVID Vaccine Authorized for Kids 6-17",
        "event_type": "FDA_Approval",
        "expected_signal": "long"
    },
    {
        "ticker": "GILD",
        "date": "2020-05-01",
        "event": "Remdesivir Emergency Use Authorization",
        "event_type": "FDA_Approval",
        "expected_signal": "long"
    },
    {
        "ticker": "BNTX",
        "date": "2020-11-09",
        "event": "BioNTech/Pfizer COVID Vaccine Phase 3 Success",
        "event_type": "Phase3_Positive",
        "expected_signal": "long"
    },
    {
        "ticker": "NVAX",
        "date": "2021-06-14",
        "event": "Novavax COVID Vaccine Phase 3 Results",
        "event_type": "Phase3_Positive",
        "expected_signal": "long"
    },
    {
        "ticker": "BIIB",
        "date": "2021-06-07",
        "event": "FDA Approved Aduhelm for Alzheimer's (controversial)",
        "event_type": "FDA_Approval",
        "expected_signal": "long"
    },
    # === 预期内事件（不应触发） ===
    {
        "ticker": "LLY",
        "date": "2023-11-08",
        "event": "Eli Lilly Q3 Earnings Beat (Expected)",
        "event_type": "Other",
        "expected_signal": "none"
    },
]


def get_thresholds() -> Dict:
    """获取阈值配置"""
    return {
        "long_threshold": PHARMA_LONG_MIN_GAIN,
        "short_threshold": PHARMA_SHORT_MIN_DROP,
        "volume_multiplier": PHARMA_VOLUME_MULTIPLIER,
        "market_cap_min": PHARMA_MIN_MARKET_CAP,
        "market_cap_max": PHARMA_MAX_MARKET_CAP,
    }


def fetch_historical_data(ticker: str, event_date: str, days_before: int = 30) -> Optional[Dict]:
    """获取事件前后的历史数据"""
    event_dt = datetime.strptime(event_date, "%Y-%m-%d")
    start_dt = event_dt - timedelta(days=days_before + 10)
    end_dt = event_dt + timedelta(days=5)
    
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start_dt.strftime("%Y-%m-%d"), 
                            end=end_dt.strftime("%Y-%m-%d"))
        
        if hist.empty:
            return None
        
        # 找到事件日期的数据
        event_date_str = event_date
        if event_date_str not in hist.index.strftime("%Y-%m-%d").tolist():
            # 找最近的交易日
            for idx in hist.index:
                if idx.strftime("%Y-%m-%d") >= event_date_str:
                    event_date_str = idx.strftime("%Y-%m-%d")
                    break
        
        event_row = hist[hist.index.strftime("%Y-%m-%d") == event_date_str]
        
        if event_row.empty:
            return None
        
        event_data = event_row.iloc[0]
        
        # 计算前30天平均成交量
        hist_before = hist[hist.index < event_row.index[0]]
        if len(hist_before) >= 5:
            avg_volume_30d = hist_before['Volume'].tail(30).mean()
        else:
            avg_volume_30d = event_data['Volume']
        
        # 计算日涨跌幅
        if len(hist_before) > 0:
            prev_close = hist_before.iloc[-1]['Close']
            day_change_pct = (event_data['Close'] - prev_close) / prev_close
        else:
            day_change_pct = 0
        
        # 计算MA20
        if len(hist_before) >= 20:
            ma20 = hist_before['Close'].tail(20).mean()
        else:
            ma20 = event_data['Close']
        
        price_above_ma20 = event_data['Close'] > ma20
        
        return {
            "ticker": ticker,
            "date": event_date_str,
            "open": event_data['Open'],
            "high": event_data['High'],
            "low": event_data['Low'],
            "close": event_data['Close'],
            "volume": int(event_data['Volume']),
            "avg_volume_30d": int(avg_volume_30d),
            "day_change_pct": day_change_pct,
            "volume_ratio": event_data['Volume'] / avg_volume_30d if avg_volume_30d > 0 else 0,
            "ma20": round(ma20, 2),
            "price_above_ma20": price_above_ma20
        }
        
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def check_signal_conditions(data: Dict, thresholds: Dict) -> Dict:
    """检查是否满足信号条件"""
    result = {
        "ticker": data["ticker"],
        "date": data["date"],
        "close": data["close"],
        "day_change_pct": data["day_change_pct"],
        "volume_ratio": data["volume_ratio"],
        "ma20": data["ma20"],
        "price_above_ma20": data["price_above_ma20"],
        "signal_triggered": None,
        "rating": None,
        "conditions_met": {}
    }
    
    # 检查做多条件
    long_gain = data["day_change_pct"] >= thresholds["long_threshold"]
    long_volume = data["volume_ratio"] >= thresholds["volume_multiplier"]
    
    result["conditions_met"]["long_gain"] = long_gain
    result["conditions_met"]["long_volume"] = long_volume
    
    if long_gain and long_volume:
        result["signal_triggered"] = "long"
        # Determine rating based on MA20 trend
        if data["price_above_ma20"]:
            result["rating"] = "HIGH"
        else:
            result["rating"] = "MEDIUM"
        return result
    
    # 检查做空条件
    short_drop = data["day_change_pct"] <= thresholds["short_threshold"]
    short_volume = data["volume_ratio"] >= thresholds["volume_multiplier"]
    
    result["conditions_met"]["short_drop"] = short_drop
    result["conditions_met"]["short_volume"] = short_volume
    
    if short_drop and short_volume:
        result["signal_triggered"] = "short"
        result["rating"] = "MEDIUM"  # Short signals always MEDIUM for now
    
    return result


def run_backtest(events: List[Dict]) -> List[Dict]:
    """运行回测"""
    thresholds = get_thresholds()
    results = []
    
    print(f"\n{'='*80}")
    print(f"StockQueen Pharma回测")
    print(f"{'='*80}")
    print(f"\n信号触发条件:")
    print(f"  做多: 日涨幅 >= {thresholds['long_threshold']*100}% + 成交量 >= {thresholds['volume_multiplier']}倍均值")
    print(f"  做空: 日跌幅 <= {thresholds['short_threshold']*100}% + 成交量 >= {thresholds['volume_multiplier']}倍均值")
    print()
    
    for event in events:
        print(f"📅 {event['ticker']} - {event['date']}")
        print(f"   事件: {event['event']}")
        
        # 获取历史数据
        data = fetch_historical_data(event['ticker'], event['date'])
        
        if data is None:
            print(f"   ❌ 无法获取历史数据")
            print()
            continue
        
        # 检查信号条件
        signal_result = check_signal_conditions(data, thresholds)
        signal_result["event"] = event["event"]
        signal_result["event_type"] = event["event_type"]
        signal_result["expected_signal"] = event["expected_signal"]
        
        results.append(signal_result)
        
        # 打印结果
        print(f"   收盘价: ${data['close']:.2f}")
        print(f"   日涨跌: {data['day_change_pct']*100:.2f}%")
        print(f"   成交量: {data['volume']:,}")
        print(f"   成交量倍数: {data['volume_ratio']:.2f}x")
        
        # MA20趋势分析
        ma20_status = "✅" if data["price_above_ma20"] else "❌"
        print(f"   MA20: ${data['ma20']:.2f} {ma20_status}")
        
        # 条件检查
        conditions = signal_result["conditions_met"]
        gain_status = "✅" if conditions.get("long_gain") else "❌"
        drop_status = "✅" if conditions.get("short_drop") else "❌"
        volume_status = "✅" if conditions.get("long_volume") or conditions.get("short_volume") else "❌"
        
        print(f"   条件检查:")
        print(f"     涨幅>={thresholds['long_threshold']*100}%: {gain_status}")
        print(f"     跌幅<={thresholds['short_threshold']*100}%: {drop_status}")
        print(f"     成交量>={thresholds['volume_multiplier']}x: {volume_status}")
        
        # 信号结果
        if signal_result["signal_triggered"]:
            signal_emoji = "📈" if signal_result["signal_triggered"] == "long" else "📉"
            rating_emoji = "🟢" if signal_result["rating"] == "HIGH" else "🟡"
            print(f"   {signal_emoji} 触发信号: {signal_result['signal_triggered'].upper()} ({rating_emoji} {signal_result['rating']})")
        else:
            print(f"   ⚠️ 未触发信号")
        
        # 验证结果
        actual_signal = signal_result["signal_triggered"] or "none"
        expected = event["expected_signal"]
        
        if actual_signal == expected:
            print(f"   ✅ 验证通过: 预期={expected}, 实际={actual_signal}")
        else:
            print(f"   ❌ 验证失败: 预期={expected}, 实际={actual_signal}")
        
        print()
    
    return results


def print_summary(results: List[Dict]):
    """打印回测汇总结果"""
    if not results:
        print("无回测数据")
        return
    
    print(f"\n{'='*80}")
    print(f"Pharma市场回测汇总")
    print(f"{'='*80}")
    
    correct = sum(1 for r in results if (r["signal_triggered"] or "none") == r["expected_signal"])
    total = len(results)
    
    print(f"总事件数: {total}")
    print(f"验证通过: {correct}")
    print(f"验证失败: {total - correct}")
    print(f"准确率: {correct/total*100:.1f}%" if total > 0 else "N/A")
    
    # 详细结果表
    print()
    print("详细结果:")
    print("-" * 110)
    print(f"{'股票':<8} {'日期':<12} {'涨跌幅':>10} {'成交量倍数':>10} {'MA20':>8} {'Rating':>8} {'预期':>8} {'实际':>8} {'结果':>6}")
    print("-" * 110)
    
    for r in results:
        actual = r["signal_triggered"] or "none"
        result_str = "✅" if actual == r["expected_signal"] else "❌"
        ma20_str = f"${r['ma20']:.0f}" if r.get('ma20') else "N/A"
        rating_str = r.get('rating', '-') or '-'
        print(f"{r['ticker']:<8} {r['date']:<12} {r['day_change_pct']*100:>9.2f}% {r['volume_ratio']:>9.2f}x {ma20_str:>8} {rating_str:>8} {r['expected_signal']:>8} {actual:>8} {result_str:>6}")
    
    # Rating统计
    print()
    print("信号评级统计:")
    high_signals = sum(1 for r in results if r.get("rating") == "HIGH")
    medium_signals = sum(1 for r in results if r.get("rating") == "MEDIUM")
    total_signals = sum(1 for r in results if r.get("signal_triggered"))
    
    print(f"  🟢 HIGH (趋势配合): {high_signals}")
    print(f"  🟡 MEDIUM (逆势信号): {medium_signals}")
    print(f"  总触发信号: {total_signals}")


# ========== 阈值对比测试 ==========

def run_threshold_comparison():
    """
    对Pharma全部watchlist进行两套阈值方案的对比测试
    方案A（当前）：涨幅>=8%，成交量>=5倍
    方案B（测试）：涨幅>=5%，成交量>=5倍
    """
    import pandas as pd
    
    print(f"\n{'='*100}")
    print("Pharma板块阈值对比测试")
    print(f"{'='*100}")
    print(f"回测区间: 2020-01-01 至今")
    print(f"标的数量: {len(PHARMA_WATCHLIST)} 只")
    print()
    
    # 两套阈值方案
    schemes = {
        "方案A（当前）": {"long_threshold": 0.08, "volume_multiplier": 5.0},
        "方案B（测试）": {"long_threshold": 0.05, "volume_multiplier": 5.0},
    }
    
    results = {name: [] for name in schemes.keys()}
    
    # 获取所有Pharma标的
    tickers = list(PHARMA_WATCHLIST.keys())
    
    for ticker in tickers:
        try:
            # 下载数据
            df = yf.download(ticker, start="2020-01-01", progress=False, auto_adjust=False)
            
            if df.empty or len(df) < 30:
                continue
            
            # 处理多层列索引
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 计算指标
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df["volume_ma30"] = df["Volume"].rolling(30).mean()
            df["vol_ratio"] = df["Volume"] / df["volume_ma30"]
            df["day_change"] = df["Close"].pct_change()
            
            # 对每套方案检测信号
            for scheme_name, params in schemes.items():
                long_threshold = params["long_threshold"]
                volume_multiplier = params["volume_multiplier"]
                
                for idx in range(len(df)):
                    row = df.iloc[idx]
                    
                    if pd.isna(row['day_change']) or pd.isna(row['vol_ratio']):
                        continue
                    
                    day_change = float(row['day_change'])
                    vol_ratio = float(row['vol_ratio'])
                    
                    # 做多信号
                    if day_change >= long_threshold and vol_ratio >= volume_multiplier:
                        # 计算D+1收益
                        d1_return = None
                        if idx + 1 < len(df):
                            d0_close = float(row['Close'])
                            d1_close = float(df.iloc[idx + 1]['Close'])
                            d1_return = (d1_close - d0_close) / d0_close
                        
                        results[scheme_name].append({
                            "ticker": ticker,
                            "date": df.index[idx].strftime("%Y-%m-%d"),
                            "close": float(row['Close']),
                            "day_change": day_change,
                            "vol_ratio": vol_ratio,
                            "d1_return": d1_return
                        })
                        
        except Exception as e:
            continue
    
    # 输出对比结果
    print_comparison_results(results, schemes)


def print_comparison_results(results: Dict, schemes: Dict):
    """并排输出两套方案的对比结果"""
    
    print(f"\n{'='*100}")
    print("对比结果汇总")
    print(f"{'='*100}\n")
    
    # 并排显示统计信息
    print(f"{'指标':<30} {'方案A (>=8%)':<25} {'方案B (>=5%)':<25}")
    print("-" * 100)
    
    for scheme_name in schemes.keys():
        signals = results[scheme_name]
        count = len(signals)
        
        valid_d1 = [s['d1_return'] for s in signals if s['d1_return'] is not None]
        avg_d1 = sum(valid_d1) / len(valid_d1) if valid_d1 else 0
        positive_count = sum(1 for r in valid_d1 if r > 0)
        win_rate = positive_count / len(valid_d1) * 100 if valid_d1 else 0
        
        if scheme_name == "方案A（当前）":
            print(f"{'触发信号总数':<30} {count:<25}", end="")
        else:
            print(f"{count:<25}")
            
    for scheme_name in schemes.keys():
        signals = results[scheme_name]
        valid_d1 = [s['d1_return'] for s in signals if s['d1_return'] is not None]
        avg_d1 = sum(valid_d1) / len(valid_d1) if valid_d1 else 0
        
        if scheme_name == "方案A（当前）":
            print(f"{'D+1平均收益率':<30} {avg_d1*100:>+.2f}%{'':<18}", end="")
        else:
            print(f"{avg_d1*100:>+.2f}%")
            
    for scheme_name in schemes.keys():
        signals = results[scheme_name]
        valid_d1 = [s['d1_return'] for s in signals if s['d1_return'] is not None]
        positive_count = sum(1 for r in valid_d1 if r > 0)
        win_rate = positive_count / len(valid_d1) * 100 if valid_d1 else 0
        
        if scheme_name == "方案A（当前）":
            print(f"{'D+1胜率（正收益占比）':<30} {win_rate:>.1f}%{'':<19}", end="")
        else:
            print(f"{win_rate:>.1f}%")
    
    print()
    
    # 输出每条信号的D+1收益率明细
    print(f"\n{'='*100}")
    print("每条信号D+1收益率明细")
    print(f"{'='*100}\n")
    
    for scheme_name in schemes.keys():
        signals = results[scheme_name]
        print(f"\n{scheme_name} - 共{len(signals)}条信号:")
        print("-" * 80)
        print(f"{'序号':<6} {'股票':<8} {'日期':<12} {'日涨幅':>10} {'成交量倍数':>10} {'D+1收益':>10}")
        print("-" * 80)
        
        for i, s in enumerate(signals, 1):
            d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else "N/A"
            print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>9.2f}% {s['vol_ratio']:>9.2f}x {d1_str:>10}")


# ========== 冷却期对比测试 ==========

def run_cooldown_comparison():
    """
    对比有/无30天冷却期的回测结果
    """
    import pandas as pd
    from datetime import datetime
    
    print(f"\n{'='*100}")
    print("Pharma板块冷却期对比测试")
    print(f"{'='*100}")
    print(f"回测区间: 2020-01-01 至今")
    print(f"标的数量: {len(PHARMA_WATCHLIST)} 只")
    print(f"阈值: 涨幅>=8%, 成交量>=5倍")
    print()
    
    # 阈值参数
    long_threshold = 0.08
    volume_multiplier = 5.0
    cooldown_days = 30
    
    # 三套结果：无冷却期、30天冷却期、被过滤的信号
    results_no_cooldown = []
    results_with_cooldown = []
    filtered_signals = []  # 被冷却期过滤掉的信号
    
    # 用于冷却期的记录器
    last_signal_dates = {}  # ticker -> date string
    
    # 获取所有Pharma标的
    tickers = list(PHARMA_WATCHLIST.keys())
    
    for ticker in tickers:
        try:
            # 下载数据
            df = yf.download(ticker, start="2020-01-01", progress=False, auto_adjust=False)
            
            if df.empty or len(df) < 30:
                continue
            
            # 处理多层列索引
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 计算指标
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df["volume_ma30"] = df["Volume"].rolling(30).mean()
            df["vol_ratio"] = df["Volume"] / df["volume_ma30"]
            df["day_change"] = df["Close"].pct_change()
            
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['day_change']) or pd.isna(row['vol_ratio']):
                    continue
                
                day_change = float(row['day_change'])
                vol_ratio = float(row['vol_ratio'])
                
                # 做多信号
                if day_change >= long_threshold and vol_ratio >= volume_multiplier:
                    # 计算D+1收益
                    d1_return = None
                    if idx + 1 < len(df):
                        d0_close = float(row['Close'])
                        d1_close = float(df.iloc[idx + 1]['Close'])
                        d1_return = (d1_close - d0_close) / d0_close
                    
                    signal_date = df.index[idx]
                    signal_date_str = signal_date.strftime("%Y-%m-%d")
                    
                    signal_data = {
                        "ticker": ticker,
                        "date": signal_date_str,
                        "close": float(row['Close']),
                        "day_change": day_change,
                        "vol_ratio": vol_ratio,
                        "d1_return": d1_return
                    }
                    
                    # 无冷却期：所有信号都计入
                    results_no_cooldown.append(signal_data.copy())
                    
                    # 有冷却期：检查是否在冷却期内
                    if ticker in last_signal_dates:
                        last_date = datetime.strptime(last_signal_dates[ticker], "%Y-%m-%d")
                        current_date = signal_date
                        days_diff = (current_date - last_date).days
                        
                        if days_diff >= cooldown_days:
                            # 冷却期已过，可以触发
                            results_with_cooldown.append(signal_data.copy())
                            last_signal_dates[ticker] = signal_date_str
                        else:
                            # 在冷却期内，记录被过滤的信号
                            signal_data["days_since_last"] = days_diff
                            filtered_signals.append(signal_data.copy())
                    else:
                        # 首次触发
                        results_with_cooldown.append(signal_data.copy())
                        last_signal_dates[ticker] = signal_date_str
                        
        except Exception as e:
            continue
    
    # 输出对比结果
    print_cooldown_comparison(results_no_cooldown, results_with_cooldown, filtered_signals)


def print_cooldown_comparison(results_no_cooldown, results_with_cooldown, filtered_signals):
    """输出冷却期对比结果"""
    
    print(f"\n{'='*100}")
    print("冷却期对比结果汇总")
    print(f"{'='*100}\n")
    
    # 计算统计数据
    def calc_stats(signals):
        count = len(signals)
        valid_d1 = [s['d1_return'] for s in signals if s['d1_return'] is not None]
        avg_d1 = sum(valid_d1) / len(valid_d1) if valid_d1 else 0
        positive_count = sum(1 for r in valid_d1 if r > 0)
        win_rate = positive_count / len(valid_d1) * 100 if valid_d1 else 0
        return count, avg_d1, win_rate
    
    count_no, avg_no, win_no = calc_stats(results_no_cooldown)
    count_with, avg_with, win_with = calc_stats(results_with_cooldown)
    
    # 并排显示统计信息
    print(f"{'指标':<30} {'无冷却期':<25} {'30天冷却期':<25}")
    print("-" * 100)
    print(f"{'触发信号总数':<30} {count_no:<25} {count_with:<25}")
    print(f"{'D+1平均收益率':<30} {avg_no*100:>+.2f}%{'':<19} {avg_with*100:>+.2f}%")
    print(f"{'D+1胜率（正收益占比）':<30} {win_no:>.1f}%{'':<20} {win_with:>.1f}%")
    print(f"{'过滤信号数量':<30} {'-':<25} {count_no - count_with:<25}")
    
    # 计算收益和胜率提升
    avg_improvement = (avg_with - avg_no) * 100
    win_rate_improvement = win_with - win_no
    print(f"\n{'='*100}")
    print("冷却期效果分析")
    print(f"{'='*100}")
    print(f"D+1平均收益率提升: {avg_improvement:+.2f}%")
    print(f"D+1胜率提升: {win_rate_improvement:+.1f}%")
    print(f"过滤比例: {(count_no - count_with) / count_no * 100:.1f}%")
    
    # SAVA信号数量对比
    sava_no_cooldown = [s for s in results_no_cooldown if s['ticker'] == 'SAVA']
    sava_with_cooldown = [s for s in results_with_cooldown if s['ticker'] == 'SAVA']
    sava_filtered = [s for s in filtered_signals if s['ticker'] == 'SAVA']
    
    print(f"\n{'='*100}")
    print("SAVA信号数量对比（典型案例）")
    print(f"{'='*100}")
    print(f"无冷却期: {len(sava_no_cooldown)}个信号")
    print(f"30天冷却期: {len(sava_with_cooldown)}个信号")
    print(f"被过滤: {len(sava_filtered)}个信号")
    print(f"过滤比例: {len(sava_filtered) / len(sava_no_cooldown) * 100:.1f}%" if sava_no_cooldown else "N/A")
    
    # 输出被冷却期过滤掉的信号列表
    print(f"\n{'='*100}")
    print(f"被冷却期过滤掉的信号列表（共{len(filtered_signals)}条）")
    print(f"{'='*100}")
    print("-" * 90)
    print(f"{'序号':<6} {'股票':<8} {'日期':<12} {'日涨幅':>10} {'距上次':>10} {'D+1收益':>10}")
    print("-" * 90)
    
    for i, s in enumerate(filtered_signals, 1):
        d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else "N/A"
        days_str = f"{s['days_since_last']}天"
        print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>9.2f}% {days_str:>10} {d1_str:>10}")
    
    print()
    
    # 输出每条信号的D+1收益率明细
    print(f"\n{'='*100}")
    print("每条信号D+1收益率明细")
    print(f"{'='*100}\n")
    
    print(f"\n无冷却期 - 共{count_no}条信号:")
    print("-" * 80)
    print(f"{'序号':<6} {'股票':<8} {'日期':<12} {'日涨幅':>10} {'成交量倍数':>10} {'D+1收益':>10}")
    print("-" * 80)
    
    for i, s in enumerate(results_no_cooldown, 1):
        d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else "N/A"
        print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>9.2f}% {s['vol_ratio']:>9.2f}x {d1_str:>10}")
    
    print(f"\n\n30天冷却期 - 共{count_with}条信号:")
    print("-" * 80)
    print(f"{'序号':<6} {'股票':<8} {'日期':<12} {'日涨幅':>10} {'成交量倍数':>10} {'D+1收益':>10}")
    print("-" * 80)
    
    for i, s in enumerate(results_with_cooldown, 1):
        d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else "N/A"
        print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>9.2f}% {s['vol_ratio']:>9.2f}x {d1_str:>10}")


def run_short_signal_backtest():
    """
    Pharma板块做空信号回测
    做空条件：日跌幅 <= -10%，成交量 >= 30日均量5倍
    应用30天冷却期
    """
    import pandas as pd
    from datetime import datetime
    
    print(f"\n{'='*100}")
    print("Pharma板块做空信号回测")
    print(f"{'='*100}")
    print(f"回测区间: 2020-01-01 至今")
    print(f"标的数量: {len(PHARMA_WATCHLIST)} 只")
    print(f"做空条件: 跌幅 <= -10%, 成交量 >= 5倍均值")
    print(f"冷却期: 30天")
    print()
    
    # 做空信号参数
    short_threshold = -0.10  # -10%跌幅
    volume_multiplier = 5.0
    cooldown_days = 30
    
    # 存储结果
    short_signals = []
    last_signal_dates = {}
    
    tickers = list(PHARMA_WATCHLIST.keys())
    
    for ticker in tickers:
        try:
            # 下载数据
            df = yf.download(ticker, start="2020-01-01", progress=False, auto_adjust=False)
            
            if df.empty or len(df) < 30:
                continue
            
            # 处理多层列索引
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 计算指标
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df["volume_ma30"] = df["Volume"].rolling(30).mean()
            df["vol_ratio"] = df["Volume"] / df["volume_ma30"]
            df["day_change"] = df["Close"].pct_change()
            
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['day_change']) or pd.isna(row['vol_ratio']):
                    continue
                
                day_change = float(row['day_change'])
                vol_ratio = float(row['vol_ratio'])
                
                # 做空信号条件：跌幅 <= -10% 且 成交量 >= 5倍
                if day_change <= short_threshold and vol_ratio >= volume_multiplier:
                    # 计算D+1收益（做空方向）
                    # 做空D+1收益 = (信号日收盘价 - 次日收盘价) / 信号日收盘价
                    d1_return = None
                    if idx + 1 < len(df):
                        d0_close = float(row['Close'])
                        d1_close = float(df.iloc[idx + 1]['Close'])
                        d1_return = (d0_close - d1_close) / d0_close  # 做空收益
                    
                    signal_date = df.index[idx]
                    signal_date_str = signal_date.strftime("%Y-%m-%d")
                    
                    # 检查冷却期
                    if ticker in last_signal_dates:
                        last_date = datetime.strptime(last_signal_dates[ticker], "%Y-%m-%d")
                        days_diff = (signal_date - last_date).days
                        
                        if days_diff < cooldown_days:
                            continue  # 在冷却期内，跳过
                    
                    # 记录信号
                    signal_data = {
                        "ticker": ticker,
                        "date": signal_date_str,
                        "close": float(row['Close']),
                        "day_change": day_change,
                        "vol_ratio": vol_ratio,
                        "d1_return": d1_return
                    }
                    short_signals.append(signal_data)
                    last_signal_dates[ticker] = signal_date_str
                    
        except Exception as e:
            continue
    
    # 输出结果
    print_short_backtest_results(short_signals)


def print_short_backtest_results(short_signals):
    """输出做空信号回测结果"""
    
    # 1. 所有触发的做空信号明细
    print(f"\n{'='*100}")
    print("1. 做空信号明细")
    print(f"{'='*100}")
    print(f"{'序号':<6} {'股票':<8} {'日期':<12} {'跌幅':>10} {'成交量倍数':>12} {'D+1收益':>10}")
    print("-" * 100)
    
    for i, s in enumerate(short_signals, 1):
        d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else "N/A"
        print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>9.2f}% {s['vol_ratio']:>11.2f}x {d1_str:>10}")
    
    # 2. 做空信号汇总统计
    print(f"\n{'='*100}")
    print("2. 做空信号汇总统计")
    print(f"{'='*100}")
    
    total_count = len(short_signals)
    valid_d1 = [s['d1_return'] for s in short_signals if s['d1_return'] is not None]
    avg_d1 = sum(valid_d1) / len(valid_d1) if valid_d1 else 0
    positive_count = sum(1 for r in valid_d1 if r > 0)  # D+1正收益 = 做空盈利
    win_rate = positive_count / len(valid_d1) * 100 if valid_d1 else 0
    
    print(f"做空信号总数: {total_count}")
    print(f"D+1平均收益: {avg_d1*100:>+.2f}%")
    print(f"D+1胜率（次日继续下跌）: {win_rate:.1f}%")
    print(f"有D+1数据信号数: {len(valid_d1)}")
    
    # 3. 做多 vs 做空对比
    print(f"\n{'='*100}")
    print("3. 做多 vs 做空信号对比")
    print(f"{'='*100}")
    
    # 重新运行做多信号统计（使用相同的冷却期逻辑）
    long_signals = get_long_signals_with_cooldown()
    
    long_valid_d1 = [s['d1_return'] for s in long_signals if s['d1_return'] is not None]
    long_avg = sum(long_valid_d1) / len(long_valid_d1) if long_valid_d1 else 0
    long_positive = sum(1 for r in long_valid_d1 if r > 0)
    long_win_rate = long_positive / len(long_valid_d1) * 100 if long_valid_d1 else 0
    
    print(f"{'指标':<25} {'做多信号':<20} {'做空信号':<20}")
    print("-" * 80)
    print(f"{'信号总数':<25} {len(long_signals):<20} {total_count:<20}")
    print(f"{'D+1平均收益':<25} {long_avg*100:>+.2f}%{'':<14} {avg_d1*100:>+.2f}%")
    print(f"{'D+1胜率':<25} {long_win_rate:.1f}%{'':<15} {win_rate:.1f}%")
    
    # 4. 触发做空信号最多的前5只股票
    print(f"\n{'='*100}")
    print("4. 做空信号最多的前5只股票")
    print(f"{'='*100}")
    
    ticker_counts = Counter(s['ticker'] for s in short_signals)
    top5 = ticker_counts.most_common(5)
    
    print(f"{'排名':<6} {'股票':<8} {'信号数量':<10}")
    print("-" * 40)
    for rank, (ticker, count) in enumerate(top5, 1):
        print(f"{rank:<6} {ticker:<8} {count:<10}")
    
    print(f"\n{'='*100}")
    print("回测完成")
    print(f"{'='*100}")


def get_long_signals_with_cooldown():
    """获取做多信号（带30天冷却期）用于对比"""
    import pandas as pd
    
    long_threshold = 0.08
    volume_multiplier = 5.0
    cooldown_days = 30
    
    long_signals = []
    last_signal_dates = {}
    
    tickers = list(PHARMA_WATCHLIST.keys())
    
    for ticker in tickers:
        try:
            df = yf.download(ticker, start="2020-01-01", progress=False, auto_adjust=False)
            
            if df.empty or len(df) < 30:
                continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df["volume_ma30"] = df["Volume"].rolling(30).mean()
            df["vol_ratio"] = df["Volume"] / df["volume_ma30"]
            df["day_change"] = df["Close"].pct_change()
            
            for idx in range(len(df)):
                row = df.iloc[idx]
                
                if pd.isna(row['day_change']) or pd.isna(row['vol_ratio']):
                    continue
                
                day_change = float(row['day_change'])
                vol_ratio = float(row['vol_ratio'])
                
                if day_change >= long_threshold and vol_ratio >= volume_multiplier:
                    d1_return = None
                    if idx + 1 < len(df):
                        d0_close = float(row['Close'])
                        d1_close = float(df.iloc[idx + 1]['Close'])
                        d1_return = (d1_close - d0_close) / d0_close
                    
                    signal_date = df.index[idx]
                    signal_date_str = signal_date.strftime("%Y-%m-%d")
                    
                    if ticker in last_signal_dates:
                        last_date = datetime.strptime(last_signal_dates[ticker], "%Y-%m-%d")
                        days_diff = (signal_date - last_date).days
                        
                        if days_diff < cooldown_days:
                            continue
                    
                    signal_data = {
                        "ticker": ticker,
                        "date": signal_date_str,
                        "day_change": day_change,
                        "vol_ratio": vol_ratio,
                        "d1_return": d1_return
                    }
                    long_signals.append(signal_data)
                    last_signal_dates[ticker] = signal_date_str
                    
        except Exception:
            continue
    
    return long_signals


if __name__ == "__main__":
    import sys
    
    # 检查命令行参数
    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        # 运行阈值对比测试
        run_threshold_comparison()
    elif len(sys.argv) > 1 and sys.argv[1] == "--cooldown":
        # 运行冷却期对比测试
        run_cooldown_comparison()
    elif len(sys.argv) > 1 and sys.argv[1] == "--short":
        # 运行做空信号回测
        run_short_signal_backtest()
    else:
        # 运行原有回测
        results = run_backtest(PHARMA_HISTORICAL_EVENTS)
        print_summary(results)
