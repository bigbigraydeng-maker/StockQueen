"""
冷却期回测对比测试
"""
import yfinance as yf
import pandas as pd
from datetime import datetime
from app.config.pharma_watchlist import PHARMA_WATCHLIST

print('='*100)
print('Pharma板块冷却期对比测试')
print('='*100)
print('回测区间: 2020-01-01 至今')
print(f'标的数量: {len(PHARMA_WATCHLIST)} 只')
print('阈值: 涨幅>=8%, 成交量>=5倍')
print()

long_threshold = 0.08
volume_multiplier = 5.0
cooldown_days = 30

results_no_cooldown = []
results_with_cooldown = []
filtered_signals = []
last_signal_dates = {}

tickers = list(PHARMA_WATCHLIST.keys())

for ticker in tickers:
    try:
        df = yf.download(ticker, start='2020-01-01', progress=False, auto_adjust=False)
        if df.empty or len(df) < 30:
            continue
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df['volume_ma30'] = df['Volume'].rolling(30).mean()
        df['vol_ratio'] = df['Volume'] / df['volume_ma30']
        df['day_change'] = df['Close'].pct_change()
        
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
                signal_date_str = signal_date.strftime('%Y-%m-%d')
                
                signal_data = {
                    'ticker': ticker,
                    'date': signal_date_str,
                    'day_change': day_change,
                    'vol_ratio': vol_ratio,
                    'd1_return': d1_return
                }
                
                results_no_cooldown.append(signal_data.copy())
                
                if ticker in last_signal_dates:
                    last_date = datetime.strptime(last_signal_dates[ticker], '%Y-%m-%d')
                    days_diff = (signal_date - last_date).days
                    
                    if days_diff >= cooldown_days:
                        results_with_cooldown.append(signal_data.copy())
                        last_signal_dates[ticker] = signal_date_str
                    else:
                        signal_data['days_since_last'] = days_diff
                        filtered_signals.append(signal_data.copy())
                else:
                    results_with_cooldown.append(signal_data.copy())
                    last_signal_dates[ticker] = signal_date_str
    except:
        continue

def calc_stats(signals):
    count = len(signals)
    valid_d1 = [s['d1_return'] for s in signals if s['d1_return'] is not None]
    avg_d1 = sum(valid_d1) / len(valid_d1) if valid_d1 else 0
    positive_count = sum(1 for r in valid_d1 if r > 0)
    win_rate = positive_count / len(valid_d1) * 100 if valid_d1 else 0
    return count, avg_d1, win_rate

count_no, avg_no, win_no = calc_stats(results_no_cooldown)
count_with, avg_with, win_with = calc_stats(results_with_cooldown)

print('='*100)
print('冷却期对比结果汇总')
print('='*100)
print(f'指标                           无冷却期                 30天冷却期')
print('-' * 80)
print(f'触发信号总数                   {count_no:<25} {count_with}')
print(f'D+1平均收益率                  {avg_no*100:>+.2f}%                  {avg_with*100:>+.2f}%')
print(f'D+1胜率                        {win_no:>.1f}%                   {win_with:>.1f}%')
print(f'过滤信号数量                   -                      {count_no - count_with}')

print()
print('='*100)
print('冷却期效果分析')
print('='*100)
print(f'D+1平均收益率提升: {(avg_with - avg_no)*100:+.2f}%')
print(f'D+1胜率提升: {win_with - win_no:+.1f}%')
print(f'过滤比例: {(count_no - count_with) / count_no * 100:.1f}%')

sava_no = [s for s in results_no_cooldown if s['ticker'] == 'SAVA']
sava_with = [s for s in results_with_cooldown if s['ticker'] == 'SAVA']
sava_filtered = [s for s in filtered_signals if s['ticker'] == 'SAVA']

print()
print('='*100)
print('SAVA信号数量对比（典型案例）')
print('='*100)
print(f'无冷却期: {len(sava_no)}个信号')
print(f'30天冷却期: {len(sava_with)}个信号')
print(f'被过滤: {len(sava_filtered)}个信号')
if sava_no:
    print(f'过滤比例: {len(sava_filtered) / len(sava_no) * 100:.1f}%')

print()
print('='*100)
print(f'被冷却期过滤掉的信号列表（共{len(filtered_signals)}条）')
print('='*100)
print(f'序号   股票      日期          日涨幅      距上次      D+1收益')
print('-' * 70)
for i, s in enumerate(filtered_signals[:20], 1):
    d1_str = f"{s['d1_return']*100:>+.2f}%" if s['d1_return'] is not None else 'N/A'
    print(f"{i:<6} {s['ticker']:<8} {s['date']:<12} {s['day_change']*100:>8.2f}% {s['days_since_last']:>6}天    {d1_str:>8}")
if len(filtered_signals) > 20:
    print(f'... 还有 {len(filtered_signals) - 20} 条被过滤的信号')
