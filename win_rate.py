import pandas as pd

df = pd.read_csv('backtest_results_20260228.csv')
triggered = df[(df['ticker'] != 'SAVA') & (df['signal_triggered'] == True)]

wins = triggered[triggered['post_1d_return'] > 0]
losses = triggered[triggered['post_1d_return'] <= 0]

print('=' * 60)
print('次日胜率分析')
print('=' * 60)
print(f'次日胜率: {len(wins)}/{len(triggered)} = {len(wins)/len(triggered)*100:.1f}%')
print(f'次日平均盈利: {wins["post_1d_return"].mean()*100:.2f}%')
print(f'次日平均亏损: {losses["post_1d_return"].mean()*100:.2f}%')
if len(wins) > 0 and len(losses) > 0:
    print(f'盈亏比: {abs(wins["post_1d_return"].mean()/losses["post_1d_return"].mean()):.2f}')

print('\n--- 逐个次日结果 ---')
result_list = []
for idx, row in triggered.iterrows():
    ret = row['post_1d_return'] * 100
    result_emoji = "✅" if row['post_1d_return'] > 0 else "❌"
    result_list.append({
        'ticker': row['ticker'],
        'date': row['event_date'],
        'day_gain': f"{row['day_gain_pct']:.1f}%",
        'next_day_ret': f"{ret:.2f}%",
        'result': result_emoji
    })

df_result = pd.DataFrame(result_list)
print(df_result.to_string(index=False))
