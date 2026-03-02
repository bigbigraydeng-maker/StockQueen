import pandas as pd

df = pd.read_csv('backtest_results_20260228.csv')

print('=' * 60)
print('不含 SAVA 的统计')
print('=' * 60)

df_no_sava = df[df['ticker'] != 'SAVA']

print(f'总事件数: {len(df_no_sava)}')
print(f'涉及股票: {df_no_sava["ticker"].nunique()} 只')
print(f'股票列表: {df_no_sava["ticker"].unique().tolist()}')

triggered = df_no_sava[df_no_sava['signal_triggered'] == True]
print(f'\n触发信号: {len(triggered)} 个 (触发率 {len(triggered)/len(df_no_sava)*100:.1f}%)')

high_rating = df_no_sava[df_no_sava['signal_rating'] == 'HIGH']
medium_rating = df_no_sava[df_no_sava['signal_rating'] == 'MEDIUM']
print(f'├── HIGH rating: {len(high_rating)} 个')
print(f'└── MEDIUM rating: {len(medium_rating)} 个')

print(f'\n平均涨跌幅（触发日）: {triggered["day_gain_pct"].mean():.2f}%')
print(f'平均成交量倍数: {triggered["volume_multiplier"].mean():.2f}x')

returns_5d = triggered['post_5d_return'].dropna()
returns_1d = triggered['post_1d_return'].dropna()
print(f'触发后5日平均收益: {returns_5d.mean()*100:.2f}%')
print(f'触发后次日平均收益: {returns_1d.mean()*100:.2f}%')

print(f'\n--- 次日胜率分析 ---')
wins = triggered[triggered['post_1d_return'] > 0]
losses = triggered[triggered['post_1d_return'] <= 0]
print(f"次日胜率: {len(wins)}/{len(triggered)} = {len(wins)/len(triggered)*100:.1f}%")
print(f"次日平均盈利: {wins['post_1d_return'].mean()*100:.2f}%")
print(f"次日平均亏损: {losses['post_1d_return'].mean()*100:.2f}%")
if len(wins) > 0 and len(losses) > 0:
    print(f"盈亏比: {abs(wins['post_1d_return'].mean()/losses['post_1d_return'].mean()):.2f}")

print(f'\n--- 各股票分布 ---')
for ticker in df_no_sava['ticker'].unique():
    count = len(df_no_sava[df_no_sava['ticker'] == ticker])
    print(f'{ticker}: {count} 个事件')

print(f'\n--- 触发信号详情 ---')
print(triggered[['ticker', 'event_date', 'day_gain_pct', 'volume_multiplier', 'signal_rating', 'post_1d_return', 'post_5d_return']].to_string())

print(f'\n--- 逐个次日结果 ---')
print(triggered[['ticker', 'event_date', 'day_gain_pct', 'post_1d_return']].to_string())

print('\n' + '=' * 60)
print('对比：含 SAVA vs 不含 SAVA')
print('=' * 60)

triggered_all = df[df['signal_triggered'] == True]
print(f'含 SAVA: 次日收益 {triggered_all["post_1d_return"].mean()*100:.2f}%, 5日收益 {triggered_all["post_5d_return"].mean()*100:.2f}%')
print(f'不含 SAVA: 次日收益 {returns_1d.mean()*100:.2f}%, 5日收益 {returns_5d.mean()*100:.2f}%')
