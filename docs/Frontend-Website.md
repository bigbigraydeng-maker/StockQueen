---
name: ǰ����վ�嵥
description: �Ǳ���ҳ�桢HTMX�����Ӫ��վ�㡢����ϵͳ��CMS
type: reference
created: 2026-03-19
tags: [frontend, website, HTMX, Jinja2, blog, CMS, active]
---

# ǰ����վ�嵥

## ����ջ

| �� | ���� | ˵�� |
|---|------|------|
| ģ������ | Jinja2 | FastAPI HTMLResponse |
| �첽ˢ�� | HTMX | 20�� partial endpoint |
| ��ʽ | Tailwind CSS + DaisyUI | ��Ӧʽ��� |
| ͼ�� | Chart.js | ��ֵ����/�ز��� |
| ʵʱ���� | WebSocket | Tiger������ |
| Ӫ��վ�� | ��HTML | site/ ��̬�ļ� |
| CMS | Next.js (����) | ���ͱ༭�� |

---

## 1. �Ǳ���ҳ�棨11ҳ��

| ·�� | ģ�� | ���� | ״̬ |
|------|------|------|------|
| `/dashboard` | `dashboard.html` | �ֲ�/��ֵ/�������� | ?? |
| `/rotation` | `rotation.html` | �ֶ�����/Regime��ͼ/��ʷʱ����/�������ͼ | ?? |
| `/quotes` | `quotes.html` | ʵʱ���飨WebSocket�� | ?? |
| `/knowledge` | `knowledge.html` | ֪ʶ��/���žۺ�/���� | ?? |
| `/strategy` | `strategy.html` | ����˵���ĵ� | ?? |
| `/strategy-matrix` | `strategy_matrix.html` | ��������ֶԱȾ��� | ?? |
| `/backtest` | `backtest.html` | �ز⹤�ߣ�3 Tab: V4������/���Ծ���/Walk-Forward��֤�� | ?? |
| `/trades` | `trades.html` | ���׼�¼ | ?? |
| `/social` | `social.html` | AI�罻ý���������� | ?? |
| `/scheduler` | `scheduler.html` | ��ʱ������־/�ֶ����� | ?? |
| `/changelog` | `changelog.html` | �汾������־ | ?? |

### ����·��
| ·�� | ģ�� | ���� |
|------|------|------|
| `/rotation/sector/{name}` | `sector_detail.html` | ���������ȡ |

### �������ͼ�鲢��2026-03-22��

ԭ 33 ����Ƭ sector �鲢Ϊ 21 ����16 ��Ʊ��� + 5 ETF��𣩣�

| �鲢�� | �����ľɱ�ǩ | ���� |
|--------|-------------|------|
| technology | tech, saas, ai | 93 |
| mega_tech | mega_tech (FAANG+TSLA) | 9 |
| semiconductors | semi | 28 |
| financial_services | financials, fintech | 57 |
| healthcare | healthcare, bio, med_device | 68 |
| industrials | industrials, industrial, transport | 55 |
| consumer | consumer, consumer_lc, travel | 43 |
| energy | energy, clean_energy | 33 |
| communication | media, telecom | 24 |
| real_estate | reit | 22 |
| defense | defense, space | 15 |
| china | china | 15 |
| staples | staples | 13 |
| materials | materials | 9 |
| utilities | utilities | 4 |

�ؼ��ļ���`rotation_watchlist.py` (`normalize_sector()`)  
�������ҳ������ 20 ֻʱ�Զ���ҳ��ǰ�� JS��  
DB��`sector_snapshots` ��ʷ������Ǩ�Ƶ��±�ǩ

---

## 2. HTMX Partial �����20����

| �˵� | ģ�� | ˢ�³��� |
|------|------|---------|
| `/htmx/rotation-full` | `_rotation_full.html` | �����ֶ���������+�ֲ�+Regime�� |
| `/htmx/rotation-table` | `_rotation_table.html` | �ֶ����ֱ� |
| `/htmx/rotation-intraday` | `_rotation_intraday.html` | ����ɨ���� |
| `/htmx/rotation-exec-result` | `_rotation_exec_result.html` | ִ�н������ |
| `/htmx/daily-check-result` | `_daily_check_result.html` | ÿ�ռ���� |
| `/htmx/quotes-table` | `_quotes_table.html` | �����б� |
| `/htmx/ticker-quote` | `_ticker_quote.html` | ��ֻ��Ʊ���ۿ� |
| `/htmx/positions` | `_positions.html` | ��ǰ�ֱֲ� |
| `/htmx/pending-entries` | `_pending_entries.html` | ���볡�ź� |
| `/htmx/regime-map` | `_regime_map.html` | Regime ״̬��ͼ |
| `/htmx/regime-history` | `_regime_history.html` | Regime �仯ʱ���� |
| `/htmx/backtest-results` | `_backtest_results.html` | �ز��� |
| `/htmx/optimize-results` | `_optimize_results.html` | �Ż���� |
| `/htmx/signals` | `_signals.html` | �ź���� |
| `/htmx/risk-badge` | `_risk_badge.html` | ����ָ����� |
| `/htmx/knowledge-list` | `_knowledge_list.html` | ֪ʶ���б� |
| `/htmx/knowledge-stats` | `_knowledge_stats.html` | ֪ʶ��ͳ�� |
| `/htmx/search-results` | `_search_results.html` | ������� |
| `/htmx/scheduler-logs` | `_scheduler_logs.html` | ��������־ |
| `/htmx/trade-history` | `_trade_history.html` | ������ʷ |

---

## 3. Ӫ��վ�� (site/)

### ����ҳ��
| ҳ�� | ���� | Ӣ�� | ˵�� |
|------|------|------|------|
| ��ҳ | `index-zh.html` | `index.html` | ��Ʒ���� |
| ���� | `subscribe-zh.html` | `subscribe.html` | ע����� |
| ���� | �� | `pricing.html` | �۸񷽰� |
| ���� | `terms-zh.html` | `terms.html` | ʹ������ |
| ��˽ | `privacy-zh.html` | `privacy.html` | ��˽���� |
| ֧���ɹ� | `payment-success-zh.html` | `payment-success.html` | Stripe�ص� |
| ��Ա���� | �� | `member-dashboard.html` | ���ѻ�Ա�Ǳ��� |

### ���� (site/blog/) �� 23ƪ
| ���� | ˫�� |
|------|------|
| AI ��������ָ�� | ? |
| �������Խ��� | ? |
| Bear Market ���ز��� | ? |
| ɢ����������ָ�� | ? |
| ���⻪��Ͷ��ָ�� | ? |
| Sharpe ����ָ�� | ? |
| ������Ʊ˰��ָ�� | ? |
| V5 500 �������� | ? |
| Walk-Forward ��֤��� | ? |
| AI vs �˹�ѡ�� | ? |
| 2025 ���г�չ�� | ? |

### �ܱ� (site/weekly-report/)
- 6���ѷ�������Ӣ˫�� = 12 HTML��
- ����Դ: `content/*.md`
- �Զ�����: `scripts/newsletter/`

---

## 4. CMS ϵͳ (cms/)

| ��� | �ļ� | ˵�� |
|------|------|------|
| ��ҳ�� | `src/app/page.tsx` | �����б�/�༭�� |
| �༭�� | `src/components/Editor.tsx` | TipTap ���ı� |
| ���ݿ�Ƭ | `src/components/DataCard.tsx` | Ƕ��ʽ����չʾ |
| API - Blog | `src/app/api/blog/route.ts` | ����CRUD |
| API - Git | `src/app/api/git/route.ts` | Git push/pull |
| API - Perf | `src/app/api/performance/route.ts` | ��������ע�� |

**״̬**: ?? ���ã������ؿ�����δ����������

---

## 5. ���� JSON (site/data/)

| �ļ� | ��; | ����Ƶ�� |
|------|------|---------|
| `live-metrics.json` | ��ҳʵʱָ�� | ÿ�� |
| `backtest-summary.json` | �ز�ժҪ | ÿ�� |
| `equity-curve.json` | ��ֵ���� | ÿ�� |
| `latest-signals.json` | �����ź� | ÿ�� |
| `signal-history.json` | �ź���ʷ | ÿ�� |
| `signal-track-record.json` | �źųɼ��� | ÿ�� |
| `walk-forward-validation.json` | WF��֤ | �ֶ� |
| `yearly-performance.json` | ��ȱ��� | ÿ�� |
| `changelog.json` | ������־ | ÿ�η��� |

---

## 6. ��ҳ�������ݹ淶��2026-03-20 ���£�

> **����Դ����**: �����������ݱ����� Obsidian/PPT һ�£�ͳһʹ�� **Walk-Forward Adaptive (����Ӧ WF)** ���֣���ֹչʾ����ѡ�Σ�Fixed Best�����֡�

### ��ǰչʾָ�꣨Walk-Forward Adaptive OOS��

| ָ�� | ֵ | ��Դ�ֶ� |
|------|----|---------|
| �ۼ����� | **+379.7%** | `walk-forward-validation.json �� adaptive.cumulative_return` |
| �껯���� | 64.9% | `adaptive.annualized_return` |
| ���ձ��� | **1.76** | `adaptive.sharpe` |
| ���س� | -25.3% | `adaptive.max_drawdown` |
| ʤ�� | 56.4% | `adaptive.win_rate` |
| Alpha vs SPY | **+309.9%** | `adaptive.alpha_vs_spy` |

> �������Ų����������ڲ��ο�����ֹ����ҳչʾ����536.8% / Sharpe 2.68

### ���Ժ������㣨�Ѹ��£�
1. **ML Walk-Forward �����Ż�** �� ÿ�´�25��������Զ�ѡSharpe���ţ�40���������ڣ���ǰհƫ��
2. **��̬500ֻ��Ʊ��** �� ���� + ��С�̳ɳ� + ��ҵETF + ���� + ���򣬺������Թ��ˣ��վ��ɽ�>50��ɣ�
3. **Regime ����Ӧ** �� �Զ�ʶ��ţ/��/�𵴣���̬��������/������λ
4. **���տ���** �� ATRֹ�� + ��鼯�ж����� + 0.1%˫�򻬵�

### ƫ�����˵������������
- ? 0.1% ˫�򻬵��ѽ�ģ����"�޻���"��
- ? �վ��ɽ��� 50 ��ɹ���������
- ? ���տ��̼�ִ�У������̼�ǰհ��
- ? 40���� Walk-Forward����"6����"�ɰ�˵����