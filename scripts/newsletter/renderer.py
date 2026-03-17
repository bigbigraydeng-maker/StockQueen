"""
StockQueen Newsletter - 模板渲染模块
根据数据包渲染4种 Newsletter HTML + 4种社交媒体内容
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("newsletter.renderer")


# ======================================================================
# 工具函数
# ======================================================================

def _fmt_pct(value, with_sign=True) -> str:
    """格式化百分比: 0.041 → '+4.1%', 5.368 → '+536.8%'
    所有数据源均以小数存储收益率，统一乘以100转换为百分比
    """
    if value is None:
        return "N/A"
    pct = value * 100
    if with_sign:
        return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{pct:.1f}%"


def _fmt_price(value) -> str:
    """格式化价格: 125.5 → '$125.50'"""
    if value is None or value == 0:
        return "N/A"
    return f"${value:,.2f}"


def _color(value) -> str:
    """根据正负返回颜色代码"""
    if value is None:
        return "#64748b"
    return "#059669" if value >= 0 else "#dc2626"


def _regime_label(regime: str, lang: str = "en") -> str:
    """市场状态标签"""
    labels = {
        "en": {"BULL": "Bullish", "BEAR": "Bearish Defense", "CHOPPY": "Choppy / Neutral", "UNKNOWN": "Unknown"},
        "zh": {"BULL": "牛市进攻", "BEAR": "熊市防御", "CHOPPY": "震荡市", "UNKNOWN": "未知"},
    }
    return labels.get(lang, labels["en"]).get(regime.upper(), regime)


def _regime_color(regime: str) -> str:
    """市场状态背景色"""
    colors = {
        "BULL": ("#f0fdf4", "#166534", "#059669"),  # bg, text, border
        "BEAR": ("#fef2f2", "#991b1b", "#dc2626"),
        "CHOPPY": ("#fef3c7", "#92400e", "#f59e0b"),
    }
    return colors.get(regime.upper(), ("#f8fafc", "#475569", "#94a3b8"))


# ======================================================================
# 邮件 HTML 基础结构
# ======================================================================

def _email_header(lang: str = "en") -> str:
    subtitle = "每周量化策略报告" if lang == "zh" else "Weekly Quantitative Strategy Report"
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StockQueen Weekly Report</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 0; background: #f1f5f9;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px; letter-spacing: 1px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">{subtitle}</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">"""


def _email_footer(lang: str = "en", is_free: bool = True) -> str:
    if lang == "zh":
        team = "StockQueen 量化研究团队 | 瑞德资本"
        unsub = "取消订阅"
        if is_free:
            upgrade_cta = """
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 24px; border-radius: 12px; text-align: center; margin: 24px 0;">
            <p style="color: #e0e7ff; font-size: 14px; margin: 0 0 12px 0;">想要获取完整买卖信号、进仓价、止损位？</p>
            <a href="https://stockqueen.tech/subscribe-zh.html" style="display: inline-block; background: #fff; color: #4f46e5; padding: 12px 28px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px;">升级付费版 →</a>
        </div>"""
        else:
            upgrade_cta = ""
    else:
        team = "StockQueen Quantitative Research | Rayde Capital"
        unsub = "Unsubscribe"
        if is_free:
            upgrade_cta = """
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 24px; border-radius: 12px; text-align: center; margin: 24px 0;">
            <p style="color: #e0e7ff; font-size: 14px; margin: 0 0 12px 0;">Want full buy/sell signals with entry prices and stop-loss levels?</p>
            <a href="https://stockqueen.tech/subscribe.html" style="display: inline-block; background: #fff; color: #4f46e5; padding: 12px 28px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px;">Upgrade to Premium →</a>
        </div>"""
        else:
            upgrade_cta = ""

    return f"""{upgrade_cta}
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0; line-height: 1.8;">
            {team}<br>
            <a href="https://stockqueen.tech" style="color: #0891b2; text-decoration: none;">stockqueen.tech</a>
            &nbsp;|&nbsp;
            <a href="{{{{unsubscribe_url}}}}" style="color: #94a3b8; text-decoration: underline;">{unsub}</a>
        </p>
    </div>
</body>
</html>"""


# ======================================================================
# 各内容区块
# ======================================================================

def _section_date_regime(data: dict, lang: str) -> str:
    """日期 + 市场状态横幅"""
    regime = data.get("market_regime", "UNKNOWN")
    bg, text_color, border = _regime_color(regime)
    label = _regime_label(regime, lang)

    if lang == "zh":
        date_str = f"{data['year']}年 第{data['week_number']}周"
        regime_prefix = "市场状态"
    else:
        date_str = f"Week {data['week_number']}, {data['year']}"
        regime_prefix = "Market Regime"

    return f"""
        <p style="color: #64748b; font-size: 12px; margin-bottom: 16px;">{date_str} | {data.get('generated_at', '')}</p>
        <div style="background: {bg}; border-left: 4px solid {border}; padding: 14px 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
            <p style="color: {text_color}; font-size: 14px; margin: 0; font-weight: 600;">
                {regime_prefix}: {label}
            </p>
        </div>"""


def _section_performance_summary(data: dict, lang: str) -> str:
    """本周策略收益 vs SPY/QQQ 三格摘要"""
    # 计算本周收益（用持仓的平均 return_pct）
    positions = data.get("positions", [])
    if positions:
        avg_return = sum(p.get("return_pct", 0) for p in positions) / len(positions)
    else:
        avg_return = 0

    # 从年度数据获取 YTD
    yearly = data.get("yearly", {})
    total = yearly.get("total", {})
    strategy_total = total.get("strategy_return", 0)
    spy_total = total.get("spy_return", 0)

    if lang == "zh":
        labels = ("持仓平均收益", "总收益", "vs SPY 超额")
    else:
        labels = ("Avg Position Return", "Total Return", "Alpha vs SPY")

    alpha = strategy_total - spy_total

    return f"""
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <tr>
                <td style="padding: 14px 8px; background: #f8fafc; border-radius: 8px 0 0 8px; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[0]}</p>
                    <p style="color: {_color(avg_return)}; font-size: 24px; font-weight: bold; margin: 4px 0 0 0;">{_fmt_pct(avg_return)}</p>
                </td>
                <td style="padding: 14px 8px; background: #f8fafc; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[1]}</p>
                    <p style="color: {_color(strategy_total)}; font-size: 24px; font-weight: bold; margin: 4px 0 0 0;">{_fmt_pct(strategy_total)}</p>
                </td>
                <td style="padding: 14px 8px; background: #f8fafc; border-radius: 0 8px 8px 0; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[2]}</p>
                    <p style="color: {_color(alpha)}; font-size: 24px; font-weight: bold; margin: 4px 0 0 0;">{_fmt_pct(alpha)}</p>
                </td>
            </tr>
        </table>"""


def _section_recent_exits(data: dict, lang: str) -> str:
    """本周平仓记录（免费版可看的「操作回顾」）"""
    exits = data.get("recent_exits", [])
    if not exits:
        return ""

    if lang == "zh":
        title = "本周操作回顾"
        cols = ("标的", "收益", "持有天数")
    else:
        title = "This Week's Closed Trades"
        cols = ("Ticker", "Return", "Hold Days")

    rows = ""
    for t in exits[:8]:  # 最多显示8条
        ret = t.get("return_pct", 0)
        days = t.get("hold_days", 0)
        rows += f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 12px;"><strong>{t.get('ticker', '')}</strong></td>
                    <td style="padding: 10px 12px; text-align: right; color: {_color(ret)}; font-weight: 600;">{_fmt_pct(ret)}</td>
                    <td style="padding: 10px 12px; text-align: right; color: #64748b;">{days}d</td>
                </tr>"""

    return f"""
        <h2 style="color: #0f172a; font-size: 18px; margin: 24px 0 12px 0;">{title}</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <thead>
                <tr style="background: #f1f5f9;">
                    <th style="padding: 10px 12px; text-align: left; font-size: 12px; color: #475569;">{cols[0]}</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #475569;">{cols[1]}</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #475569;">{cols[2]}</th>
                </tr>
            </thead>
            <tbody>{rows}
            </tbody>
        </table>"""


def _section_holdings_free(data: dict, lang: str) -> str:
    """免费版持仓列表：只显示代码，不显示价格"""
    positions = data.get("positions", [])
    if not positions:
        return ""

    if lang == "zh":
        title = "当前持仓"
        note = "升级付费版查看完整进仓价、止损位和止盈位"
    else:
        title = "Current Holdings"
        note = "Upgrade to see entry prices, stop-loss, and take-profit levels"

    tickers_html = ""
    for p in positions:
        ret = p.get("return_pct", 0)
        tickers_html += f"""
            <span style="display: inline-block; background: #f1f5f9; padding: 6px 14px; border-radius: 20px; margin: 4px; font-weight: 600; font-size: 14px;">
                {p['ticker']} <span style="color: {_color(ret)}; font-size: 12px;">{_fmt_pct(ret)}</span>
            </span>"""

    return f"""
        <h2 style="color: #0f172a; font-size: 18px; margin: 24px 0 12px 0;">{title}</h2>
        <div style="margin-bottom: 8px;">{tickers_html}
        </div>
        <p style="color: #94a3b8; font-size: 12px; font-style: italic; margin: 0 0 24px 0;">{note}</p>"""


def _section_holdings_paid(data: dict, lang: str) -> str:
    """付费版完整持仓表：含价格、止损、止盈"""
    positions = data.get("positions", [])
    if not positions:
        return ""

    if lang == "zh":
        title = "完整持仓明细"
        cols = ("标的", "进仓价", "现价", "收益", "止损", "止盈")
    else:
        title = "Full Position Details"
        cols = ("Ticker", "Entry", "Current", "Return", "Stop Loss", "Take Profit")

    rows = ""
    for p in positions:
        ret = p.get("return_pct", 0)
        rows += f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 8px; font-weight: 600;">{p['ticker']}</td>
                    <td style="padding: 10px 8px; text-align: right;">{_fmt_price(p.get('entry_price'))}</td>
                    <td style="padding: 10px 8px; text-align: right;">{_fmt_price(p.get('current_price'))}</td>
                    <td style="padding: 10px 8px; text-align: right; color: {_color(ret)}; font-weight: 600;">{_fmt_pct(ret)}</td>
                    <td style="padding: 10px 8px; text-align: right; color: #dc2626;">{_fmt_price(p.get('stop_loss'))}</td>
                    <td style="padding: 10px 8px; text-align: right; color: #059669;">{_fmt_price(p.get('take_profit'))}</td>
                </tr>"""

    return f"""
        <h2 style="color: #0f172a; font-size: 18px; margin: 24px 0 12px 0;">{title}</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 13px;">
            <thead>
                <tr style="background: #f1f5f9;">
                    <th style="padding: 10px 8px; text-align: left; font-size: 11px; color: #475569;">{cols[0]}</th>
                    <th style="padding: 10px 8px; text-align: right; font-size: 11px; color: #475569;">{cols[1]}</th>
                    <th style="padding: 10px 8px; text-align: right; font-size: 11px; color: #475569;">{cols[2]}</th>
                    <th style="padding: 10px 8px; text-align: right; font-size: 11px; color: #475569;">{cols[3]}</th>
                    <th style="padding: 10px 8px; text-align: right; font-size: 11px; color: #475569;">{cols[4]}</th>
                    <th style="padding: 10px 8px; text-align: right; font-size: 11px; color: #475569;">{cols[5]}</th>
                </tr>
            </thead>
            <tbody>{rows}
            </tbody>
        </table>"""


def _section_new_signals(data: dict, lang: str) -> str:
    """付费版：新买入/卖出信号"""
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])

    if not entries and not exits:
        return ""

    html = ""

    if entries:
        if lang == "zh":
            title = f"本周新买入信号 ({len(entries)})"
        else:
            title = f"New Buy Signals ({len(entries)})"

        rows = ""
        for p in entries:
            rows += f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 12px;"><strong style="color: #059669;">{p['ticker']}</strong></td>
                    <td style="padding: 10px 12px; text-align: right;">{_fmt_price(p.get('entry_price'))}</td>
                    <td style="padding: 10px 12px; text-align: right; color: #dc2626;">{_fmt_price(p.get('stop_loss'))}</td>
                    <td style="padding: 10px 12px; text-align: right; color: #059669;">{_fmt_price(p.get('take_profit'))}</td>
                </tr>"""

        entry_col = "进仓价" if lang == "zh" else "Entry Price"
        sl_col = "止损" if lang == "zh" else "Stop Loss"
        tp_col = "止盈" if lang == "zh" else "Take Profit"

        html += f"""
        <h2 style="color: #059669; font-size: 18px; margin: 24px 0 12px 0;">🟢 {title}</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <thead>
                <tr style="background: #f0fdf4;">
                    <th style="padding: 10px 12px; text-align: left; font-size: 12px; color: #166534;">Ticker</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #166534;">{entry_col}</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #166534;">{sl_col}</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #166534;">{tp_col}</th>
                </tr>
            </thead>
            <tbody>{rows}
            </tbody>
        </table>"""

    if exits:
        if lang == "zh":
            title = f"本周卖出信号 ({len(exits)})"
        else:
            title = f"Exit Signals ({len(exits)})"

        rows = ""
        for p in exits:
            ret = p.get("return_pct", 0)
            rows += f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 12px;"><strong style="color: #dc2626;">{p['ticker']}</strong></td>
                    <td style="padding: 10px 12px; text-align: right;">{_fmt_price(p.get('entry_price'))}</td>
                    <td style="padding: 10px 12px; text-align: right; color: {_color(ret)}; font-weight: 600;">{_fmt_pct(ret)}</td>
                </tr>"""

        entry_col = "进仓价" if lang == "zh" else "Entry"
        ret_col = "收益" if lang == "zh" else "Return"

        html += f"""
        <h2 style="color: #dc2626; font-size: 18px; margin: 24px 0 12px 0;">🔴 {title}</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <thead>
                <tr style="background: #fef2f2;">
                    <th style="padding: 10px 12px; text-align: left; font-size: 12px; color: #991b1b;">Ticker</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #991b1b;">{entry_col}</th>
                    <th style="padding: 10px 12px; text-align: right; font-size: 12px; color: #991b1b;">{ret_col}</th>
                </tr>
            </thead>
            <tbody>{rows}
            </tbody>
        </table>"""

    return html


def _section_signal_count_cta(data: dict, lang: str) -> str:
    """免费版 CTA：本周有N个新信号 → 升级查看"""
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])
    total = len(entries) + len(exits)

    if total == 0:
        return ""

    if lang == "zh":
        text = f"本周有 <strong>{total}</strong> 个新交易信号"
        cta = "升级查看完整信号 →"
        url = "https://stockqueen.tech/subscribe-zh.html"
    else:
        text = f"<strong>{total}</strong> new trading signals this week"
        cta = "Upgrade to see full signals →"
        url = "https://stockqueen.tech/subscribe.html"

    return f"""
        <div style="background: #eff6ff; border: 2px dashed #3b82f6; padding: 20px; border-radius: 12px; text-align: center; margin: 24px 0;">
            <p style="color: #1e40af; font-size: 16px; margin: 0 0 12px 0;">{text}</p>
            <a href="{url}" style="display: inline-block; background: #3b82f6; color: #fff; padding: 10px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px;">{cta}</a>
        </div>"""


def _section_stats_summary(data: dict, lang: str) -> str:
    """历史统计摘要"""
    summary = data.get("trade_summary", {})
    if not summary:
        return ""

    if lang == "zh":
        title = "策略统计"
        labels = ("总交易", "胜率", "平均收益", "平均持仓天数")
    else:
        title = "Strategy Statistics"
        labels = ("Total Trades", "Win Rate", "Avg Return", "Avg Hold Days")

    total = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate", 0)
    avg_ret = summary.get("avg_return", 0)
    avg_days = summary.get("avg_hold_days", 0)

    return f"""
        <h2 style="color: #0f172a; font-size: 18px; margin: 24px 0 12px 0;">{title}</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <tr>
                <td style="padding: 12px; background: #f8fafc; text-align: center; width: 25%; border-radius: 8px 0 0 8px;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[0]}</p>
                    <p style="color: #0f172a; font-size: 20px; font-weight: bold; margin: 4px 0 0 0;">{total}</p>
                </td>
                <td style="padding: 12px; background: #f8fafc; text-align: center; width: 25%;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[1]}</p>
                    <p style="color: #0f172a; font-size: 20px; font-weight: bold; margin: 4px 0 0 0;">{_fmt_pct(win_rate, with_sign=False)}</p>
                </td>
                <td style="padding: 12px; background: #f8fafc; text-align: center; width: 25%;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[2]}</p>
                    <p style="color: {_color(avg_ret)}; font-size: 20px; font-weight: bold; margin: 4px 0 0 0;">{_fmt_pct(avg_ret)}</p>
                </td>
                <td style="padding: 12px; background: #f8fafc; text-align: center; width: 25%; border-radius: 0 8px 8px 0;">
                    <p style="color: #64748b; font-size: 11px; margin: 0;">{labels[3]}</p>
                    <p style="color: #0f172a; font-size: 20px; font-weight: bold; margin: 4px 0 0 0;">{avg_days:.0f}</p>
                </td>
            </tr>
        </table>"""


def _section_view_full_report(data: dict, lang: str) -> str:
    """查看完整报告 CTA 按钮"""
    if lang == "zh":
        text = "查看完整报告"
    else:
        text = "View Full Report"

    return f"""
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/weekly-report/"
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%);
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px;
                      font-weight: 600; font-size: 14px;">
                {text}
            </a>
        </div>"""


# ======================================================================
# 完整渲染器
# ======================================================================

class NewsletterRenderer:
    """渲染4种 Newsletter 版本"""

    def render_free(self, data: dict, lang: str = "en") -> str:
        """
        免费版 Newsletter
        - 市场状态
        - 本周策略收益 vs SPY/QQQ
        - 操作回顾（已平仓交易）
        - 持仓代码（无价格）
        - CTA：本周有N个新信号 → 升级查看
        """
        html = _email_header(lang)
        html += _section_date_regime(data, lang)
        html += _section_performance_summary(data, lang)
        html += _section_recent_exits(data, lang)
        html += _section_holdings_free(data, lang)
        html += _section_signal_count_cta(data, lang)
        html += _section_stats_summary(data, lang)
        html += _section_view_full_report(data, lang)
        html += _email_footer(lang, is_free=True)
        return html

    def render_paid(self, data: dict, lang: str = "en") -> str:
        """
        付费版 Newsletter
        - 所有免费版内容 +
        - 新买入信号（代码 + 进仓价）
        - 新卖出信号（代码 + 退出价 + 收益）
        - 完整持仓明细（进仓价 + 止盈 + 止损）
        """
        html = _email_header(lang)
        html += _section_date_regime(data, lang)
        html += _section_performance_summary(data, lang)
        html += _section_new_signals(data, lang)
        html += _section_holdings_paid(data, lang)
        html += _section_recent_exits(data, lang)
        html += _section_stats_summary(data, lang)
        html += _section_view_full_report(data, lang)
        html += _email_footer(lang, is_free=False)
        return html

    def render_all(self, data: dict) -> dict:
        """
        渲染全部4个版本
        返回: {"free-zh": html, "free-en": html, "paid-zh": html, "paid-en": html}
        """
        return {
            "free-zh": self.render_free(data, lang="zh"),
            "free-en": self.render_free(data, lang="en"),
            "paid-zh": self.render_paid(data, lang="zh"),
            "paid-en": self.render_paid(data, lang="en"),
        }
