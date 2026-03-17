"""
StockQueen Newsletter - 社交媒体内容生成模块
生成 Facebook, Twitter, LinkedIn, 微信公众号内容
"""

import logging
from datetime import datetime

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
            "wechat-zh": str (Markdown)
        }
        """
        return {
            "facebook-zh": self._facebook_zh(data),
            "facebook-en": self._facebook_en(data),
            "twitter-en": self._twitter_en(data),
            "linkedin-en": self._linkedin_en(data),
            "wechat-zh": self._wechat_zh(data),
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
