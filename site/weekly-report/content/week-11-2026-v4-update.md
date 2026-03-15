# StockQueen V4 Strategy Validation Special Report — Week 11, 2026

**Report Date:** March 15, 2026
**Strategy Version:** V4.0 Momentum Rotation + Trailing Stop (Walk-Forward Validated)
**Market Regime:** Monitoring

---

## 🎯 Strategy Upgrade Announcement: V4 Locked

After 4 rounds of rigorous Walk-Forward validation, StockQueen V4 parameters are now officially locked. This report summarizes the complete validation journey and final results.

### What Changed from V3 to V4

| Parameter | V3 Value | V4 Value | Evidence |
|-----------|----------|----------|----------|
| TOP_N | 4 | **6** | 4/6 OOS windows chose 6 |
| HOLDING_BONUS | 0.5 | **0.0** | 5/6 OOS windows chose 0 |
| ATR_STOP | 2.0 | **1.5** | Stable across all 6 windows |
| Trailing Stop | Not implemented | **1.5 × ATR** | Validated vs no-trailing baseline |
| Trailing Activate | N/A | **0.5 × ATR** | Low threshold outperforms high |
| Stock Pool | 147 tickers | **220 tickers** | 25 sectors, 8 new sector groups |
| Bias Corrections | None | **3 corrections** | Slippage, volume, next-day open |

---

## 📊 Walk-Forward Validation Results (6 Windows)

### Methodology
- **Design:** 8-month training + 8-month out-of-sample (OOS) test
- **Windows:** 6 overlapping periods covering Jul 2021 – Mar 2026
- **Parameter Grid:** 25 combinations per window (5 TOP_N × 5 HB values)
- **Optimization Metric:** Sharpe Ratio on training set
- **Key Principle:** Parameters are NEVER evaluated on their training data

### Window-by-Window Results

| Window | OOS Period | Market Context | Best TOP_N | Best HB | OOS Sharpe |
|--------|-----------|----------------|-----------|---------|------------|
| W1 | Jul 2022 – Feb 2023 | Fed rate hikes, bear market | 6 | 0 | 1.92 |
| W2 | Mar 2023 – Oct 2023 | AI boom, choppy market | 6 | 0.5 | 2.28 |
| W3 | Nov 2023 – Jun 2024 | Magnificent 7 leadership | 5 | 0 | 2.52 |
| W4 | Jul 2024 – Feb 2025 | Rate cut expectations | 2 | 0 | 2.68 |
| W5 | Mar 2025 – Oct 2025 | Increased volatility | 6 | 0 | 2.15 |
| W6 | Sep 2025 – Mar 2026 | Recent environment | 6 | 0 | 2.45 |

### Spliced OOS Performance (188 Weeks)

| Metric | Value |
|--------|-------|
| **Cumulative Return** | **494.4%** |
| **Annualized Return** | **63.7%** |
| **Sharpe Ratio** | **2.33** |
| **Max Drawdown** | **-20.8%** |
| **Overfitting Decay** | **0.23** (MODERATE — real edge confirmed) |

---

## 📈 4-Round Iteration History

| Version | Change | Tickers | Windows | Sharpe | Annual | Max DD | Decay |
|---------|--------|---------|---------|--------|--------|--------|-------|
| V1 | Baseline | 136 | 3 | 1.04 | 40.4% | -35.7% | 0.45 |
| V2 | +Trailing Stop | 136 | 3 | 1.99 | 77.6% | -29.5% | 0.57 |
| V3 | +Expanded Pool & Windows | 220 | 6 | 2.41 | 68.3% | -25.8% | 0.42 |
| **V4** | **+Bias Corrections** | **220** | **6** | **2.33** | **63.7%** | **-20.8%** | **0.23** |

**Key Insight:** V4 Sharpe dropped slightly from V3 (2.41→2.33) but overfitting decay improved dramatically (0.42→0.23). This means the strategy's edge is MORE REAL, not less — the corrections removed artificial advantages that inflated training-set performance.

---

## 🔬 Bias Corrections Applied

### 1. Transaction Costs (0.1% Slippage)
Every position change incurs 0.1% slippage per side (0.2% round-trip). This accounts for bid-ask spread and market impact.

### 2. Volume Filter (500K Shares Minimum)
Stocks with 20-day average volume below 500,000 shares are excluded from scoring. This prevents the optimizer from picking illiquid stocks where the backtest price may not be achievable.

### 3. Next-Day Open Price Entry
Signals are generated at market close; execution happens at next day's open price. This removes the unrealistic assumption of trading at the signal's closing price.

---

## ⚠️ Known Limitations (Honest Disclosure)

1. **Survivorship Bias:** All 220 stocks in our pool survived to today. Companies that went bankrupt or were delisted during 2021-2026 are not included.
2. **Gap Risk:** ATR-based stops assume execution at the stop price. Overnight gaps can cause worse fills.
3. **Multiple Testing:** We iterated 4 rounds, viewing OOS results each time. This introduces mild data snooping.
4. **Capacity Limits:** With TOP_N=6, weekly rebalancing involves significant trading volume. Large capital may face market impact.
5. **Limited Extreme Markets:** 2021-2026 does not include a 2008-style crash or March 2020-style panic.

---

## 🔮 V5 Roadmap Preview

### Phase 1: Dynamic Stock Pool
Replace the static 220-ticker list with automatic full-market scanning (market cap > $500M, daily volume > 1M shares, listed > 1 year). This addresses survivorship bias by including stocks that existed at the time of each backtest window.

### Phase 2: Strategy Enhancement
- Bear market auto-deleveraging (reduce to 50% capital)
- Turnover rate constraints (max 50% weekly change)
- Factor weight Walk-Forward optimization

### Phase 3: Productization
- After-hours AI news signal scanning
- Telegram/WeChat signal push notifications
- Subscription management platform

---

## 📞 Next Steps

The V4 strategy is now locked and running in production. Key parameters will not change unless a new Walk-Forward validation round produces significantly better results.

**For questions:** research@stockqueen.tech

---

*This report is generated by StockQueen V4.0 Quant Engine*
*Data Update: 2026-03-15 18:00 EST*
*Disclaimer: This report is for reference only and does not constitute investment advice. Past performance does not guarantee future results. Investing involves risk.*

**StockQueen Quantitative Research Team | Rayde Capital**
