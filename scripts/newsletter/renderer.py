"""
StockQueen Newsletter - 模板渲染模块
官网同款深色主题 + 渐变设计，4种 Newsletter HTML
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("newsletter.renderer")


# ======================================================================
# 工具函数
# ======================================================================

def _fmt_pct(value, with_sign=True) -> str:
    """格式化百分比: 0.041 → '+4.1%', 5.368 → '+536.8%'"""
    if value is None:
        return "N/A"
    pct = value * 100
    if with_sign:
        return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{pct:.1f}%"


def _fmt_price(value) -> str:
    if value is None or value == 0:
        return "N/A"
    return f"${value:,.2f}"


def _color(value) -> str:
    if value is None:
        return "#94a3b8"
    return "#34d399" if value >= 0 else "#f87171"


def _regime_label(regime: str, lang: str = "en") -> str:
    labels = {
        "en": {"BULL": "Bullish", "BEAR": "Bearish Defense", "CHOPPY": "Choppy / Neutral", "UNKNOWN": "Unknown"},
        "zh": {"BULL": "牛市进攻", "BEAR": "熊市防御", "CHOPPY": "震荡市", "UNKNOWN": "未知"},
    }
    return labels.get(lang, labels["en"]).get(regime.upper(), regime)


def _regime_emoji(regime: str) -> str:
    return {"BULL": "🟢", "BEAR": "🔴", "CHOPPY": "🟡"}.get(regime.upper(), "⚪")


def _regime_colors(regime: str) -> tuple:
    """返回 (bg, text, border, glow) 颜色"""
    return {
        "BULL": ("#052e16", "#34d399", "#059669", "rgba(52,211,153,0.15)"),
        "BEAR": ("#450a0a", "#f87171", "#dc2626", "rgba(248,113,113,0.15)"),
        "CHOPPY": ("#451a03", "#fbbf24", "#f59e0b", "rgba(251,191,36,0.15)"),
    }.get(regime.upper(), ("#1e293b", "#94a3b8", "#475569", "rgba(148,163,184,0.1)"))


# ======================================================================
# 邮件 HTML — 深色主题（与官网 #0b0f19 一致）
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
<body style="margin: 0; padding: 0; background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <!-- Outer wrapper for email clients -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #0b0f19;">
        <tr><td align="center" style="padding: 20px 10px;">
    <!-- Main container -->
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
        <!-- Header with gradient -->
        <tr><td style="background: linear-gradient(135deg, #312e81 0%, #0e7490 100%); padding: 32px 30px 24px; border-radius: 16px 16px 0 0; text-align: center;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                <td style="text-align: center;">
                    <!-- Logo text with gradient feel -->
                    <h1 style="margin: 0; font-size: 32px; font-weight: 800; letter-spacing: 1px;">
                        <span style="color: #818cf8;">Stock</span><span style="color: #22d3ee;">Queen</span>
                    </h1>
                    <p style="color: #a5b4fc; margin: 6px 0 0 0; font-size: 13px; letter-spacing: 2px; text-transform: uppercase;">{subtitle}</p>
                </td>
            </tr></table>
        </td></tr>
        <!-- Content area -->
        <tr><td style="background: #111827; padding: 0;">
            <div style="padding: 28px 30px;">"""


def _email_footer(lang: str = "en", is_free: bool = True) -> str:
    if lang == "zh":
        team = "StockQueen 量化研究团队 | 瑞得资本"
        unsub = "取消订阅"
        website = "访问官网"
    else:
        team = "StockQueen Quant Research | Rayde Capital"
        unsub = "Unsubscribe"
        website = "Visit Website"

    # Upgrade CTA for free version
    upgrade_cta = ""
    if is_free:
        if lang == "zh":
            upgrade_cta = """
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 28px 0;">
                <tr><td style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 28px; border-radius: 12px; text-align: center;">
                    <p style="color: #e0e7ff; font-size: 15px; margin: 0 0 16px 0; line-height: 1.6;">想要获取完整买卖信号、进仓价、止损位？</p>
                    <a href="https://stockqueen.tech/subscribe-zh.html" style="display: inline-block; background: #ffffff; color: #4f46e5; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px;">升级付费版 →</a>
                </td></tr>
            </table>"""
        else:
            upgrade_cta = """
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 28px 0;">
                <tr><td style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 28px; border-radius: 12px; text-align: center;">
                    <p style="color: #e0e7ff; font-size: 15px; margin: 0 0 16px 0; line-height: 1.6;">Want full buy/sell signals with entry prices and stop-loss levels?</p>
                    <a href="https://stockqueen.tech/subscribe.html" style="display: inline-block; background: #ffffff; color: #4f46e5; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px;">Upgrade to Premium →</a>
                </td></tr>
            </table>"""

    return f"""{upgrade_cta}
            </div>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background: #0d1117; padding: 24px 30px; border-radius: 0 0 16px 16px; border-top: 1px solid #1e293b;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td style="text-align: center;">
                    <p style="color: #4b5563; font-size: 12px; margin: 0 0 8px 0;">{team}</p>
                    <p style="margin: 0; font-size: 12px;">
                        <a href="https://stockqueen.tech" style="color: #6366f1; text-decoration: none;">{website}</a>
                        <span style="color: #374151;">&nbsp;&nbsp;|&nbsp;&nbsp;</span>
                        <a href="{{{{unsubscribe_url}}}}" style="color: #4b5563; text-decoration: underline;">{unsub}</a>
                    </p>
                </td></tr>
            </table>
        </td></tr>
    </table>
        </td></tr>
    </table>
</body>
</html>"""


# ======================================================================
# 内容区块 — 深色卡片风格
# ======================================================================

def _section_date_regime(data: dict, lang: str) -> str:
    regime = data.get("market_regime", "UNKNOWN")
    bg, text_color, border, glow = _regime_colors(regime)
    label = _regime_label(regime, lang)
    emoji = _regime_emoji(regime)

    if lang == "zh":
        date_str = f"{data['year']}年 第{data['week_number']}周"
        regime_prefix = "市场状态"
    else:
        date_str = f"Week {data['week_number']}, {data['year']}"
        regime_prefix = "Market Regime"

    return f"""
            <p style="color: #6b7280; font-size: 12px; margin: 0 0 16px 0; letter-spacing: 1px;">{date_str} | {data.get('generated_at', '')}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px;">
                <tr><td style="background: {glow}; border-left: 4px solid {border}; padding: 16px 20px; border-radius: 0 10px 10px 0;">
                    <p style="color: {text_color}; font-size: 15px; margin: 0; font-weight: 700;">
                        {emoji} {regime_prefix}: {label}
                    </p>
                </td></tr>
            </table>"""


def _section_performance_summary(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    avg_return = sum(p.get("return_pct", 0) for p in positions) / len(positions) if positions else 0

    yearly = data.get("yearly", {})
    total = yearly.get("total", {})
    strategy_total = total.get("strategy_return", 0)
    spy_total = total.get("spy_return", 0)
    alpha = strategy_total - spy_total

    if lang == "zh":
        labels = ("持仓平均收益", "总收益", "vs SPY 超额")
    else:
        labels = ("Avg Position Return", "Total Return", "Alpha vs SPY")

    def _metric_cell(label, value, is_first=False, is_last=False):
        br_left = "10px" if is_first else "0"
        br_right = "10px" if is_last else "0"
        return f"""<td style="padding: 18px 8px; background: #1e293b; width: 33%; text-align: center; border-radius: {br_left} {br_right} {br_right} {br_left};">
                        <p style="color: #6b7280; font-size: 10px; margin: 0; text-transform: uppercase; letter-spacing: 1px;">{label}</p>
                        <p style="color: {_color(value)}; font-size: 26px; font-weight: 800; margin: 6px 0 0 0; letter-spacing: -1px;">{_fmt_pct(value)}</p>
                    </td>"""

    return f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="4" style="margin-bottom: 24px; border-collapse: separate;">
                <tr>
                    {_metric_cell(labels[0], avg_return, is_first=True)}
                    {_metric_cell(labels[1], strategy_total)}
                    {_metric_cell(labels[2], alpha, is_last=True)}
                </tr>
            </table>"""


def _section_title(text: str, emoji: str = "") -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"""
            <h2 style="color: #f1f5f9; font-size: 17px; margin: 28px 0 14px 0; padding-bottom: 8px; border-bottom: 1px solid #1e293b; font-weight: 700;">{prefix}{text}</h2>"""


def _section_recent_exits(data: dict, lang: str) -> str:
    exits = data.get("recent_exits", [])
    if not exits:
        return ""

    title = "本周操作回顾" if lang == "zh" else "This Week's Closed Trades"
    cols = ("标的", "收益", "持有") if lang == "zh" else ("Ticker", "Return", "Hold")

    rows = ""
    for i, t in enumerate(exits[:8]):
        ret = t.get("return_pct", 0)
        days = t.get("hold_days", 0)
        bg = "#1a2332" if i % 2 == 0 else "#111827"
        rows += f"""
                    <tr>
                        <td style="padding: 12px 16px; background: {bg}; font-weight: 700; color: #e2e8f0;">{t.get('ticker', '')}</td>
                        <td style="padding: 12px 16px; background: {bg}; text-align: right; color: {_color(ret)}; font-weight: 700;">{_fmt_pct(ret)}</td>
                        <td style="padding: 12px 16px; background: {bg}; text-align: right; color: #6b7280;">{days}d</td>
                    </tr>"""

    return f"""{_section_title(title, "📊")}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px; border-radius: 10px; overflow: hidden;">
                <thead>
                    <tr>
                        <th style="padding: 10px 16px; background: #0f172a; text-align: left; font-size: 11px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[0]}</th>
                        <th style="padding: 10px 16px; background: #0f172a; text-align: right; font-size: 11px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[1]}</th>
                        <th style="padding: 10px 16px; background: #0f172a; text-align: right; font-size: 11px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[2]}</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>"""


def _section_holdings_free(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    if not positions:
        return ""

    title = "当前持仓" if lang == "zh" else "Current Holdings"
    note = "升级付费版查看完整进仓价、止损位和止盈位" if lang == "zh" else "Upgrade to see entry prices, stop-loss, and take-profit levels"

    tickers_html = ""
    for p in positions:
        ret = p.get("return_pct", 0)
        tickers_html += f"""<span style="display: inline-block; background: #1e293b; padding: 8px 16px; border-radius: 8px; margin: 4px; font-weight: 700; font-size: 14px; color: #e2e8f0; border: 1px solid #334155;">
                {p['ticker']} <span style="color: {_color(ret)}; font-size: 12px; font-weight: 600;">{_fmt_pct(ret)}</span>
            </span>"""

    return f"""{_section_title(title, "💼")}
            <div style="margin-bottom: 10px;">{tickers_html}
            </div>
            <p style="color: #4b5563; font-size: 12px; font-style: italic; margin: 4px 0 24px 0;">🔒 {note}</p>"""


def _section_holdings_paid(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    if not positions:
        return ""

    title = "完整持仓明细" if lang == "zh" else "Full Position Details"
    cols = ("标的", "进仓", "现价", "收益", "止损", "止盈") if lang == "zh" else ("Ticker", "Entry", "Now", "Return", "SL", "TP")

    rows = ""
    for i, p in enumerate(positions):
        ret = p.get("return_pct", 0)
        bg = "#1a2332" if i % 2 == 0 else "#111827"
        rows += f"""
                    <tr>
                        <td style="padding: 11px 8px; background: {bg}; font-weight: 700; color: #e2e8f0;">{p['ticker']}</td>
                        <td style="padding: 11px 8px; background: {bg}; text-align: right; color: #94a3b8;">{_fmt_price(p.get('entry_price'))}</td>
                        <td style="padding: 11px 8px; background: {bg}; text-align: right; color: #e2e8f0;">{_fmt_price(p.get('current_price'))}</td>
                        <td style="padding: 11px 8px; background: {bg}; text-align: right; color: {_color(ret)}; font-weight: 700;">{_fmt_pct(ret)}</td>
                        <td style="padding: 11px 8px; background: {bg}; text-align: right; color: #f87171;">{_fmt_price(p.get('stop_loss'))}</td>
                        <td style="padding: 11px 8px; background: {bg}; text-align: right; color: #34d399;">{_fmt_price(p.get('take_profit'))}</td>
                    </tr>"""

    return f"""{_section_title(title, "📋")}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px; font-size: 13px; border-radius: 10px; overflow: hidden;">
                <thead>
                    <tr>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: left; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[0]}</th>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: right; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[1]}</th>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: right; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[2]}</th>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: right; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[3]}</th>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: right; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[4]}</th>
                        <th style="padding: 10px 8px; background: #0f172a; text-align: right; font-size: 10px; color: #6366f1; text-transform: uppercase; letter-spacing: 1px;">{cols[5]}</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>"""


def _section_new_signals(data: dict, lang: str) -> str:
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])
    if not entries and not exits:
        return ""

    html = ""

    if entries:
        title = f"本周新买入信号 ({len(entries)})" if lang == "zh" else f"New Buy Signals ({len(entries)})"
        entry_col = "进仓价" if lang == "zh" else "Entry"
        sl_col = "止损" if lang == "zh" else "SL"
        tp_col = "止盈" if lang == "zh" else "TP"

        rows = ""
        for i, p in enumerate(entries):
            bg = "#0a1f12" if i % 2 == 0 else "#0d2818"
            rows += f"""
                    <tr>
                        <td style="padding: 12px; background: {bg}; font-weight: 700; color: #34d399;">{p['ticker']}</td>
                        <td style="padding: 12px; background: {bg}; text-align: right; color: #e2e8f0;">{_fmt_price(p.get('entry_price'))}</td>
                        <td style="padding: 12px; background: {bg}; text-align: right; color: #f87171;">{_fmt_price(p.get('stop_loss'))}</td>
                        <td style="padding: 12px; background: {bg}; text-align: right; color: #34d399;">{_fmt_price(p.get('take_profit'))}</td>
                    </tr>"""

        html += f"""{_section_title(title, "🟢")}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px; border: 1px solid #059669; border-radius: 10px; overflow: hidden;">
                <thead>
                    <tr>
                        <th style="padding: 10px 12px; background: #052e16; text-align: left; font-size: 11px; color: #34d399; text-transform: uppercase; letter-spacing: 1px;">Ticker</th>
                        <th style="padding: 10px 12px; background: #052e16; text-align: right; font-size: 11px; color: #34d399; text-transform: uppercase; letter-spacing: 1px;">{entry_col}</th>
                        <th style="padding: 10px 12px; background: #052e16; text-align: right; font-size: 11px; color: #34d399; text-transform: uppercase; letter-spacing: 1px;">{sl_col}</th>
                        <th style="padding: 10px 12px; background: #052e16; text-align: right; font-size: 11px; color: #34d399; text-transform: uppercase; letter-spacing: 1px;">{tp_col}</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>"""

    if exits:
        title = f"本周卖出信号 ({len(exits)})" if lang == "zh" else f"Exit Signals ({len(exits)})"
        entry_col = "进仓价" if lang == "zh" else "Entry"
        ret_col = "收益" if lang == "zh" else "Return"

        rows = ""
        for i, p in enumerate(exits):
            ret = p.get("return_pct", 0)
            bg = "#1a0a0a" if i % 2 == 0 else "#200d0d"
            rows += f"""
                    <tr>
                        <td style="padding: 12px; background: {bg}; font-weight: 700; color: #f87171;">{p['ticker']}</td>
                        <td style="padding: 12px; background: {bg}; text-align: right; color: #e2e8f0;">{_fmt_price(p.get('entry_price'))}</td>
                        <td style="padding: 12px; background: {bg}; text-align: right; color: {_color(ret)}; font-weight: 700;">{_fmt_pct(ret)}</td>
                    </tr>"""

        html += f"""{_section_title(title, "🔴")}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 24px; border: 1px solid #dc2626; border-radius: 10px; overflow: hidden;">
                <thead>
                    <tr>
                        <th style="padding: 10px 12px; background: #450a0a; text-align: left; font-size: 11px; color: #f87171; text-transform: uppercase; letter-spacing: 1px;">Ticker</th>
                        <th style="padding: 10px 12px; background: #450a0a; text-align: right; font-size: 11px; color: #f87171; text-transform: uppercase; letter-spacing: 1px;">{entry_col}</th>
                        <th style="padding: 10px 12px; background: #450a0a; text-align: right; font-size: 11px; color: #f87171; text-transform: uppercase; letter-spacing: 1px;">{ret_col}</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>"""

    return html


def _section_signal_count_cta(data: dict, lang: str) -> str:
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
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 24px 0;">
                <tr><td style="background: #1e1b4b; border: 1px dashed #6366f1; padding: 24px; border-radius: 12px; text-align: center;">
                    <p style="color: #a5b4fc; font-size: 16px; margin: 0 0 16px 0; line-height: 1.6;">{text}</p>
                    <a href="{url}" style="display: inline-block; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: #fff; padding: 12px 28px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 14px;">{cta}</a>
                </td></tr>
            </table>"""


def _section_stats_summary(data: dict, lang: str) -> str:
    summary = data.get("trade_summary", {})
    if not summary:
        return ""

    title = "策略统计" if lang == "zh" else "Strategy Statistics"
    labels = ("总交易", "胜率", "平均收益", "持仓天数") if lang == "zh" else ("Trades", "Win Rate", "Avg Return", "Hold Days")

    total_trades = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate", 0)
    avg_ret = summary.get("avg_return", 0)
    avg_days = summary.get("avg_hold_days", 0)

    def _stat_cell(label, value_str, color="#e2e8f0"):
        return f"""<td style="padding: 14px 6px; background: #1e293b; text-align: center; width: 25%;">
                        <p style="color: #4b5563; font-size: 9px; margin: 0; text-transform: uppercase; letter-spacing: 1px;">{label}</p>
                        <p style="color: {color}; font-size: 20px; font-weight: 800; margin: 4px 0 0 0;">{value_str}</p>
                    </td>"""

    return f"""{_section_title(title, "📈")}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="3" style="margin-bottom: 24px; border-collapse: separate;">
                <tr>
                    {_stat_cell(labels[0], str(total_trades))}
                    {_stat_cell(labels[1], _fmt_pct(win_rate, with_sign=False), "#22d3ee")}
                    {_stat_cell(labels[2], _fmt_pct(avg_ret), _color(avg_ret))}
                    {_stat_cell(labels[3], f"{avg_days:.0f}d")}
                </tr>
            </table>"""


def _section_view_full_report(data: dict, lang: str) -> str:
    text = "查看完整报告" if lang == "zh" else "View Full Report on Web"
    return f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 28px 0;">
                <tr><td style="text-align: center;">
                    <a href="https://stockqueen.tech/weekly-report/"
                       style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%);
                              color: white; padding: 14px 36px; text-decoration: none; border-radius: 10px;
                              font-weight: 700; font-size: 15px; letter-spacing: 0.5px;">
                        {text} →
                    </a>
                </td></tr>
            </table>"""


# ======================================================================
# 完整渲染器
# ======================================================================

class NewsletterRenderer:
    """渲染4种 Newsletter 版本"""

    def render_free(self, data: dict, lang: str = "en") -> str:
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
        return {
            "free-zh": self.render_free(data, lang="zh"),
            "free-en": self.render_free(data, lang="en"),
            "paid-zh": self.render_paid(data, lang="zh"),
            "paid-en": self.render_paid(data, lang="en"),
        }
