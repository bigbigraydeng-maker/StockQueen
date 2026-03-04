"""Parse backtest JSON output from stdin and display formatted results."""
import sys
import json
from collections import Counter

data = json.load(sys.stdin)
gi = data['global_info']
print(f'=== Backtest {data["target_date"]} ===')
print(f'SPY: {gi["spy_change"]:+.2f}%  Crisis: {gi["crisis_score"]}/4  Decay: {gi["decay_multiplier"]}x  Day: {gi["event_days_ago"]}')
print(f'Signals: {data["signals_generated"]}  Scanned: {data["total_scanned"]}')
print()

if data['signals']:
    print('=== SIGNALS ===')
    for s in data['signals']:
        alpha = s.get('alpha_vs_spy')
        a = f'{alpha:+.2f}' if alpha is not None else 'N/A'
        print(f'  {s["ticker"]:8s} {s["direction"]:5s}  entry=${s["entry_price"]}  chg={s["day_change_pct"]:+.2f}%  alpha={a}%  vol={s["volume_multiplier"]}x  conf={s["confidence"]}')
    print()

passed = [d for d in data['diagnostics'] if d['result'] not in ('SKIP_VOLUME', 'SKIP_NO_DATA', 'SKIP_SNAPSHOT_FAIL')]
print(f'=== Passed volume gate ({len(passed)} tickers): ===')
for d in passed:
    alpha = d.get('alpha_vs_spy')
    a = f'{alpha:+.2f}' if alpha is not None else 'N/A'
    print(f'  {d["ticker"]:8s} chg={d.get("day_change_pct",0):+6.2f}%  alpha={a:>7s}  vol={d.get("volume_multiplier",0):.1f}x  thresh=[{d.get("short_threshold","?")},{d.get("long_threshold","?")}]  {d["result"]}')

c = Counter(d['result'] for d in data['diagnostics'])
print(f'\nBreakdown: {dict(c)}')
