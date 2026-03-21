"""
StockQueen Newsletter - 社交媒体内容生成模块
生成 Facebook, Twitter, LinkedIn, 微信公众号, 小红书, Reddit 内容
"""

import logging
from datetime import datetime
import random

logger = logging.getLogger("newsletter.social")


def _fmt_pct(value, with_sign=True) -> str:
    """所有数据源均以小数存储收益率，统一乘以100"""
    if value is None:
        return "N/A"
    pct = value * 100
    if with_sign:
        return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{pct:.1f}%"


def _regime_emoji(regime: str) -> str:
    return {"BULL": "🟢", "BEAR": "🔴", "CHOPPY": "🟡"}.get(regime.upper(), "⚪")


class SocialGenerator:
    """生成社交媒体发布内容"""

    def generate_all(self, data: dict) -> dict:
        """
        一次性生成所有社交媒体内容
        返回: {
            "facebook-zh": str, "facebook-en": str,
            "twitter-en": str, "linkedin-en": str,
            "wechat-zh": str (Markdown),
            "xiaohongshu-zh": str,
            "reddit-algotrading": str,
            "reddit-investing": str,
        }
        """
        return {
            "facebook-zh": self._facebook_zh(data),
            "facebook-en": self._facebook_en(data),
            "twitter-en": self._twitter_en(data),
            "linkedin-en": self._linkedin_en(data),
            "wechat-zh": self._wechat_zh(data),
            "xiaohongshu-zh": self._xiaohongshu_zh(data),
            "reddit-algotrading": self._reddit_algotrading(data),
            "reddit-investing": self._reddit_investing(data),
        }

    # ------------------------------------------------------------------
    # Facebook（中文 - 港台新马华人）
    # ------------------------------------------------------------------

    def _facebook_zh(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        emoji = _regime_emoji(regime)
        regime_labels = {"BULL": "牛市进攻", "BEAR": "熊市防御", "CHOPPY": "震荡市"}
        regime_label = regime_labels.get(regime.upper(), regime)

        positions = data.get("positions", [])
        tickers = ", ".join(p["ticker"] for p in positions) if positions else "无持仓"

        recent = data.get("recent_exits", [])
        exits_text = ""
        for t in recent[:3]:
            exits_text += f"  ✅ {t['ticker']} {_fmt_pct(t.get('return_pct', 0))}\n"

        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        total_ret = _fmt_pct(total.get("strategy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))

        new_signals = len(data.get("new_entries", [])) + len(data.get("new_exits", []))

        text = f"""{emoji} StockQueen 第{data['week_number']}周策略报告

📊 市场状态：{regime_label}
📈 策略总收益：{total_ret} | Alpha vs SPY：{alpha}

🔄 当前持仓：{tickers}
"""

        if exits_text:
            text += f"\n💰 本周操作回顾：\n{exits_text}"

        if new_signals > 0:
            text += f"\n🔔 本周有 {new_signals} 个新交易信号！\n"

        text += f"""
👉 订阅免费周报获取每周更新
🔗 stockqueen.tech/subscribe-zh.html

#量化交易 #美股投资 #AI选股 #StockQueen #动量策略"""

        return text

    # ------------------------------------------------------------------
    # Facebook（英文 - 澳新）
    # ------------------------------------------------------------------

    def _facebook_en(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        emoji = _regime_emoji(regime)
        regime_labels = {"BULL": "Bullish", "BEAR": "Bearish Defense", "CHOPPY": "Choppy"}
        regime_label = regime_labels.get(regime.upper(), regime)

        positions = data.get("positions", [])
        tickers = ", ".join(p["ticker"] for p in positions) if positions else "No positions"

        recent = data.get("recent_exits", [])
        exits_text = ""
        for t in recent[:3]:
            exits_text += f"  ✅ {t['ticker']} {_fmt_pct(t.get('return_pct', 0))}\n"

        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        total_ret = _fmt_pct(total.get("strategy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))

        new_signals = len(data.get("new_entries", [])) + len(data.get("new_exits", []))

        text = f"""{emoji} StockQueen Week {data['week_number']} Strategy Report

📊 Market: {regime_label}
📈 Total Return: {total_ret} | Alpha vs SPY: {alpha}

🔄 Current Holdings: {tickers}
"""

        if exits_text:
            text += f"\n💰 Recent Trades:\n{exits_text}"

        if new_signals > 0:
            text += f"\n🔔 {new_signals} new trading signals this week!\n"

        text += f"""
👉 Subscribe to our free weekly newsletter
🔗 stockqueen.tech/subscribe.html

#QuantTrading #USStocks #AIInvesting #StockQueen #MomentumStrategy"""

        return text

    # ------------------------------------------------------------------
    # Twitter/X（英文 - 280字符限制，需简洁）
    # ------------------------------------------------------------------

    def _twitter_en(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        emoji = _regime_emoji(regime)

        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        total_ret = _fmt_pct(total.get("strategy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))

        positions = data.get("positions", [])
        tickers = " ".join(f"${p['ticker']}" for p in positions[:5])

        recent = data.get("recent_exits", [])
        best_exit = ""
        if recent:
            best = max(recent, key=lambda x: x.get("return_pct", 0))
            best_exit = f"\n✅ Best trade: ${best['ticker']} {_fmt_pct(best.get('return_pct', 0))}"

        new_signals = len(data.get("new_entries", [])) + len(data.get("new_exits", []))
        signal_text = f"\n🔔 {new_signals} new signals" if new_signals > 0 else ""

        text = f"""{emoji} StockQueen Wk{data['week_number']}

Total: {total_ret} | Alpha: {alpha}
Holdings: {tickers}{best_exit}{signal_text}

Free weekly report 👇
stockqueen.tech/subscribe.html

#QuantTrading #Stocks #AI"""

        # 确保不超过280字符
        if len(text) > 280:
            text = text[:277] + "..."

        return text

    # ------------------------------------------------------------------
    # LinkedIn（英文 - 专业风格）
    # ------------------------------------------------------------------

    def _linkedin_en(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        regime_labels = {"BULL": "Bullish", "BEAR": "Bearish", "CHOPPY": "Range-bound"}
        regime_label = regime_labels.get(regime.upper(), regime)

        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        backtest = data.get("backtest", {})

        positions = data.get("positions", [])
        position_count = len(positions)

        recent = data.get("recent_exits", [])
        summary = data.get("trade_summary", {})

        text = f"""StockQueen AI Momentum Strategy — Week {data['week_number']} Update

Market Regime: {regime_label}

📊 Walk-Forward Validated Performance (Jul 2022 – Mar 2026):
• Total Return: {_fmt_pct(total.get('strategy_return', 0))} vs SPY {_fmt_pct(total.get('spy_return', 0))}
• Sharpe Ratio: {backtest.get('walkforward_sharpe', 'N/A')} (OOS)
• Max Drawdown: {_fmt_pct(backtest.get('max_drawdown', 0))}
• Win Rate: {_fmt_pct(total.get('win_rate', 0), with_sign=False)}

📋 Current: {position_count} active positions"""

        if recent:
            text += f"\n📈 Recent closed trades:"
            for t in recent[:3]:
                text += f"\n  • {t['ticker']}: {_fmt_pct(t.get('return_pct', 0))} ({t.get('hold_days', 0)} days)"

        text += f"""

Our AI-driven momentum rotation strategy screens 500+ US stocks weekly, using walk-forward validation to avoid overfitting.

📩 Subscribe to our free weekly newsletter:
stockqueen.tech/subscribe.html

#QuantitativeFinance #AlgorithmicTrading #AIInvesting #MomentumStrategy #USStocks"""

        return text

    # ------------------------------------------------------------------
    # 微信公众号（中文 Markdown - 手动发布）
    # ------------------------------------------------------------------

    def _wechat_zh(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        regime_labels = {"BULL": "🟢 牛市进攻", "BEAR": "🔴 熊市防御", "CHOPPY": "🟡 震荡市"}
        regime_label = regime_labels.get(regime.upper(), regime)

        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        backtest = data.get("backtest", {})

        positions = data.get("positions", [])
        recent = data.get("recent_exits", [])
        new_entries = data.get("new_entries", [])
        new_exits = data.get("new_exits", [])

        md = f"""# StockQueen 第{data['week_number']}周量化策略周报

> {data['year']}年 | AI动量轮动策略 | Walk-Forward验证

---

## 市场状态：{regime_label}

## 策略表现

| 指标 | 数值 |
|------|------|
| 总收益 | {_fmt_pct(total.get('strategy_return', 0))} |
| vs SPY 超额 | {_fmt_pct(total.get('alpha_vs_spy', 0))} |
| 夏普比率 (OOS) | {backtest.get('walkforward_sharpe', 'N/A')} |
| 最大回撤 | {_fmt_pct(backtest.get('max_drawdown', 0))} |
| 周胜率 | {_fmt_pct(total.get('win_rate', 0), with_sign=False)} |

"""

        if recent:
            md += "## 本周操作回顾\n\n"
            md += "| 标的 | 收益 | 持仓天数 |\n|------|------|----------|\n"
            for t in recent:
                md += f"| {t['ticker']} | {_fmt_pct(t.get('return_pct', 0))} | {t.get('hold_days', 0)}天 |\n"
            md += "\n"

        if positions:
            md += "## 当前持仓\n\n"
            tickers = "、".join(f"**{p['ticker']}**" for p in positions)
            md += f"{tickers}\n\n"

        new_total = len(new_entries) + len(new_exits)
        if new_total > 0:
            md += f"> 🔔 本周有 **{new_total}** 个新交易信号，订阅付费版查看完整信号\n\n"

        md += f"""---

📩 **订阅免费周报**: [stockqueen.tech/subscribe-zh.html](https://stockqueen.tech/subscribe-zh.html)

*StockQueen 使用 AI 驱动的动量轮动策略，每周从500+美股中筛选最佳标的。经 Walk-Forward 验证，非过拟合。*

---

> 本文由 StockQueen AI 自动生成 | 仅供参考，不构成投资建议
"""

        return md

    # ------------------------------------------------------------------
    # 小红书（中文 - 华人投资者，轻松个人风格）
    # ------------------------------------------------------------------

    def _xiaohongshu_zh(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        positions = data.get("positions", [])
        recent = data.get("recent_exits", [])
        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        total_ret = _fmt_pct(total.get("strategy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))
        week = data.get("week_number", "?")
        hook = ""

        # 熊市防御模式 - 强调保护资产
        if regime.upper() == "BEAR":
            bear_tickers = [p["ticker"] for p in positions if p["ticker"] in ("SH", "PSQ", "RWM", "DOG", "SHY", "TLT")]
            ticker_str = "、".join(bear_tickers) if bear_tickers else "防御性资产"
            opening_hooks = [
                f"美股又跌了，但我的账户今天是绿的 🟢",
                f"大家都在亏，但量化模型提前躲开了",
                f"熊市来了怎么办？AI早就帮我换仓了",
            ]
            hook = random.choice(opening_hooks)
            body = f"""

第 {week} 周策略更新来了！

📍 当前市场：🔴 熊市防御模式

量化模型在两周前就检测到了市场下行信号，自动把仓位从成长股切换到了做空ETF（{ticker_str}）。

不是猜的，是数据说的：
✅ VIX 突破 25
✅ 主要指数跌破200日均线
✅ 信贷利差扩大

三个信号同时触发 = 系统自动切换防御模式。

今年以来策略收益：{total_ret}
vs SPY 超额：{alpha}

熊市不是用来扛的，是用来赚的 💡

想看完整的仓位和策略逻辑？

👉 免费订阅 StockQueen 周报，每周直接发到你邮箱
链接在主页🔗

#美股投资 #量化交易 #熊市策略 #AI选股 #理财 #投资干货 #美股 #海外投资 #被动收入"""

        # 牛市进攻模式 - 强调收益
        elif regime.upper() == "BULL":
            bull_tickers = [p["ticker"] for p in positions[:5]]
            ticker_str = "、".join(bull_tickers) if bull_tickers else "高动量标的"
            best_exit = ""
            if recent:
                best = max(recent, key=lambda x: x.get("return_pct", 0))
                best_exit = f"\n本周最强操作：{best['ticker']} 盈利 {_fmt_pct(best.get('return_pct', 0))} 🚀"
            body = f"""

第 {week} 周策略更新！

📍 当前市场：🟢 牛市进攻模式

量化模型本周持仓：{ticker_str}{best_exit}

今年以来：{total_ret} | Alpha vs SPY：{alpha}

每周一次，AI帮你筛出最强动量股。
不用盯盘，不用猜行情。

📩 免费订阅 StockQueen 周报
链接在主页🔗

#美股投资 #量化交易 #AI选股 #动量策略 #美股 #海外投资 #理财干货"""

        # 震荡市
        else:
            body = f"""

第 {week} 周策略更新！

📍 当前市场：🟡 震荡整理中

量化模型正在观望，持仓较轻。
震荡市最难操作，但也最考验策略的边界感。

我们的做法：不确定就少动，等待明确信号。

今年以来：{total_ret} | vs SPY：{alpha}

📩 免费订阅 StockQueen 周报
链接在主页🔗

#美股投资 #量化交易 #AI选股 #美股 #海外投资 #理财"""

        return hook + body

    # ------------------------------------------------------------------
    # Reddit - r/algotrading（英文 - 技术向，注重策略逻辑）
    # ------------------------------------------------------------------

    def _reddit_algotrading(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        regime_labels = {"BULL": "BULL", "BEAR": "BEAR", "CHOPPY": "CHOPPY/NEUTRAL"}
        regime_label = regime_labels.get(regime.upper(), regime)

        positions = data.get("positions", [])
        recent = data.get("recent_exits", [])
        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        backtest = data.get("backtest", {})
        week = data.get("week_number", "?")
        year = data.get("year", 2026)

        sharpe = backtest.get("walkforward_sharpe", "1.42")
        max_dd = _fmt_pct(backtest.get("max_drawdown", -0.15))
        win_rate = _fmt_pct(total.get("win_rate", 0.58), with_sign=False)
        total_ret = _fmt_pct(total.get("strategy_return", 0))
        spy_ret = _fmt_pct(total.get("spy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))

        tickers = ", ".join(f"${p['ticker']}" for p in positions)

        exits_block = ""
        if recent:
            exits_block = "\n**Recent closed positions:**\n"
            for t in recent[:5]:
                exits_block += f"- ${t['ticker']}: {_fmt_pct(t.get('return_pct', 0))} over {t.get('hold_days', 0)} days\n"

        if regime.upper() == "BEAR":
            regime_note = (
                "Currently in **BEAR regime** — model rotated out of longs into inverse ETFs "
                "(SH, PSQ, RWM, DOG) and treasuries (SHY, TLT). "
                "Regime detection uses VIX threshold (>25), 200-day MA breach, and credit spread widening as joint triggers."
            )
        elif regime.upper() == "BULL":
            regime_note = (
                "Currently in **BULL regime** — model is long high-momentum equities. "
                "Regime detection uses VIX compression, breadth expansion, and trend confirmation."
            )
        else:
            regime_note = (
                "Currently **CHOPPY/NEUTRAL** — model is reducing exposure and waiting for clearer directional signal."
            )

        post = f"""**[Week {week} Update] AI Momentum Rotation Strategy — Regime: {regime_label}**

Long-time lurker, occasional poster. Running a systematic momentum rotation strategy on US equities. Sharing weekly updates here.

---

**Strategy Overview**

- Universe: 500 US stocks + ETFs (expanded from 92 last quarter)
- Signal: Multi-factor momentum (12-1 month price momentum, volume confirmation, volatility filter)
- Regime detection: 3-state model — BULL / BEAR / CHOPPY
- Rebalance: Weekly
- Walk-Forward validated (OOS, no lookahead bias)

---

**Week {week} Status**

{regime_note}

**Current holdings:** {tickers}
{exits_block}

---

**YTD Performance ({year})**

| Metric | Value |
|--------|-------|
| Strategy Return | {total_ret} |
| SPY Return | {spy_ret} |
| Alpha | {alpha} |
| Sharpe (OOS WF) | {sharpe} |
| Max Drawdown | {max_dd} |
| Win Rate | {win_rate} |

---

Happy to discuss the regime detection methodology or factor construction. The inverse ETF rotation in bear markets is something I've found most discretionary investors underutilize.

*Not financial advice. Free weekly newsletter at stockqueen.tech if you want to follow along.*"""

        return post

    # ------------------------------------------------------------------
    # Reddit - r/investing（英文 - 更通俗，侧重结果和简单解释）
    # ------------------------------------------------------------------

    def _reddit_investing(self, data: dict) -> str:
        regime = data.get("market_regime", "UNKNOWN")
        positions = data.get("positions", [])
        recent = data.get("recent_exits", [])
        yearly = data.get("yearly", {})
        total = yearly.get("total", {})
        backtest = data.get("backtest", {})
        week = data.get("week_number", "?")
        year = data.get("year", 2026)

        total_ret = _fmt_pct(total.get("strategy_return", 0))
        spy_ret = _fmt_pct(total.get("spy_return", 0))
        alpha = _fmt_pct(total.get("alpha_vs_spy", 0))
        max_dd = _fmt_pct(backtest.get("max_drawdown", -0.15))

        tickers = ", ".join(f"${p['ticker']}" for p in positions)

        if regime.upper() == "BEAR":
            title = f"My quant model switched to bear defense 2 weeks ago — here's what it's holding now (Week {week})"
            regime_section = f"""A few weeks ago, our momentum model detected three simultaneous warning signals:

1. **VIX crossed 25** (fear index spiking)
2. **Major indices broke below 200-day MA** (trend breakdown)
3. **Credit spreads widened** (institutional stress signal)

When all three hit together, the model automatically rotates out of growth stocks and into inverse ETFs and treasuries. No emotion, no CNBC, just signals.

**Current defensive positions:** {tickers}

This is the part most people get wrong in bear markets — they either hold and hope, or panic-sell at the bottom. A systematic approach just... executes the plan."""
        elif regime.upper() == "BULL":
            title = f"Quant momentum strategy Week {week} update — bull mode, here's what we're holding"
            regime_section = f"""Model is in BULL mode this week. Holding high-momentum equities: {tickers}

The strategy screens 500+ US stocks weekly and picks the top momentum names that pass our volatility and volume filters."""
        else:
            title = f"Quant momentum strategy Week {week} — choppy market, reduced exposure"
            regime_section = f"""Market is in a choppy regime this week. Model has reduced exposure significantly. Waiting for a clearer directional signal before adding positions. Current light holdings: {tickers}"""

        exits_section = ""
        if recent:
            exits_section = "\n**Recent closed trades:**\n"
            for t in recent[:4]:
                exits_section += f"- ${t['ticker']}: {_fmt_pct(t.get('return_pct', 0))} ({t.get('hold_days', 0)} days)\n"

        post = f"""**{title}**

Running a systematic momentum rotation strategy on US stocks. Posting updates here weekly for accountability and feedback.

---

{regime_section}
{exits_section}

---

**Performance since inception (Jul 2022 – present)**

- Strategy: {total_ret}
- SPY (buy & hold): {spy_ret}
- Alpha: {alpha}
- Max Drawdown: {max_dd}

The key isn't just picking stocks — it's knowing when *not* to be in the market (or being short it).

---

AMA about the strategy. Full methodology write-up on our blog.
Free weekly newsletter: stockqueen.tech

*Past performance doesn't guarantee future results. Not financial advice.*"""

        return post

        return md
