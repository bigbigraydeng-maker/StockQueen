"""
StockQueen Newsletter - 模板渲染模块 V4
强制浅色模式（防止Gmail暗色反转）+ 丰富内容（策略洞察+市场解读）
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("newsletter.renderer")


# ======================================================================
# 工具函数
# ======================================================================

def _fmt_pct(value, with_sign=True) -> str:
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
        return "#64748b"
    return "#16a34a" if value >= 0 else "#dc2626"


def _regime_label(regime: str, lang: str = "en") -> str:
    labels = {
        "en": {"BULL": "Bullish", "BEAR": "Bearish Defense", "CHOPPY": "Choppy / Neutral", "UNKNOWN": "Unknown"},
        "zh": {"BULL": "牛市进攻", "BEAR": "熊市防御", "CHOPPY": "震荡中性", "UNKNOWN": "未知"},
    }
    return labels.get(lang, labels["en"]).get(regime.upper(), regime)


def _regime_emoji(regime: str) -> str:
    return {"BULL": "🟢", "BEAR": "🔴", "CHOPPY": "🟡"}.get(regime.upper(), "⚪")


def _regime_style(regime: str) -> dict:
    return {
        "BULL": {"bg": "#dcfce7", "text": "#14532d", "border": "#22c55e", "badge_bg": "#22c55e", "badge_text": "#fff"},
        "BEAR": {"bg": "#fee2e2", "text": "#7f1d1d", "border": "#ef4444", "badge_bg": "#ef4444", "badge_text": "#fff"},
        "CHOPPY": {"bg": "#fef9c3", "text": "#713f12", "border": "#eab308", "badge_bg": "#eab308", "badge_text": "#fff"},
    }.get(regime.upper(), {"bg": "#f1f5f9", "text": "#334155", "border": "#94a3b8", "badge_bg": "#94a3b8", "badge_text": "#fff"})


def _generate_market_insight(data: dict, lang: str) -> str:
    """根据数据动态生成市场洞察段落"""
    regime = data.get("market_regime", "UNKNOWN").upper()
    positions = data.get("positions", [])
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])
    tickers = [p['ticker'] for p in positions]

    # 检测防御性持仓
    defensive = [t for t in tickers if t in ('SHY', 'SH', 'PSQ', 'DOG', 'RWM', 'VGIT', 'GLD', 'TLT', 'IEF')]
    offensive = [t for t in tickers if t not in defensive]

    if lang == "zh":
        if regime == "BEAR":
            insight = f"本周市场情绪偏弱，StockQueen 量化模型检测到熊市信号，已切换至<strong>防御模式</strong>。"
            if defensive:
                insight += f" 当前持有 {len(defensive)} 个防御性标的（{', '.join(defensive[:3])}{'等' if len(defensive) > 3 else ''}），"
                insight += "通过做空ETF和国债ETF对冲下行风险，保护资本安全。"
            if entries:
                insight += f" 本周新建仓 {len(entries)} 个标的。"
            if exits:
                insight += f" 同时止盈/止损 {len(exits)} 个持仓。"
        elif regime == "BULL":
            insight = f"量化模型识别牛市动量信号，StockQueen 进入<strong>进攻模式</strong>。"
            if offensive:
                insight += f" 重仓成长型标的（{', '.join(offensive[:3])}{'等' if len(offensive) > 3 else ''}），"
                insight += "追踪动量因子获取超额收益。"
        else:
            insight = "市场处于震荡格局，StockQueen 采取<strong>均衡配置</strong>策略，在进攻与防守间寻求平衡。"

        insight += " 策略核心：<em>通过Regime Detection模型自动识别市场状态，动态调整持仓结构</em>。"
    else:
        if regime == "BEAR":
            insight = f"Market sentiment turned bearish this week. StockQueen's quantitative model detected bear signals and switched to <strong>defensive mode</strong>."
            if defensive:
                insight += f" Currently holding {len(defensive)} defensive positions ({', '.join(defensive[:3])}{'...' if len(defensive) > 3 else ''}), "
                insight += "hedging downside risk through inverse ETFs and treasury bonds."
            if entries:
                insight += f" {len(entries)} new positions opened."
            if exits:
                insight += f" {len(exits)} positions closed."
        elif regime == "BULL":
            insight = f"Quantitative model detected bullish momentum. StockQueen entered <strong>offensive mode</strong>."
            if offensive:
                insight += f" Concentrated in growth stocks ({', '.join(offensive[:3])}{'...' if len(offensive) > 3 else ''}), "
                insight += "capturing momentum-driven alpha."
        else:
            insight = "Markets remain choppy. StockQueen deployed a <strong>balanced allocation</strong>, balancing offense and defense."

        insight += " <em>Strategy: Regime Detection model auto-identifies market states and dynamically adjusts portfolio structure.</em>"

    return insight


def _generate_watchlist_note(data: dict, lang: str) -> str:
    """生成下周关注点"""
    regime = data.get("market_regime", "UNKNOWN").upper()

    if lang == "zh":
        if regime == "BEAR":
            return "📌 <strong>下周关注：</strong>若市场企稳信号出现（VIX回落 + 主要指数站上20日均线），模型可能切换至进攻模式，届时将轮换为成长型标的。继续监控美联储政策信号和经济数据。"
        elif regime == "BULL":
            return "📌 <strong>下周关注：</strong>动量信号仍然强劲，但需警惕过热风险。Trailing Stop 机制将在回撤超过阈值时自动止损保护利润。关注财报季数据和宏观经济指标。"
        else:
            return "📌 <strong>下周关注：</strong>市场方向不明确，模型保持中性姿态。关注美联储会议纪要和就业数据，等待明确的趋势信号再做调整。"
    else:
        if regime == "BEAR":
            return "📌 <strong>Watch Next Week:</strong> If stabilization signals emerge (VIX decline + major indices reclaim 20-day MA), the model may switch to offensive mode. Monitoring Fed policy signals and economic data."
        elif regime == "BULL":
            return "📌 <strong>Watch Next Week:</strong> Momentum remains strong, but watch for overheating. Trailing Stop mechanism protects profits on pullbacks. Key focus: earnings season and macro data."
        else:
            return "📌 <strong>Watch Next Week:</strong> Direction unclear — model stays neutral. Watching Fed minutes and jobs data for clearer trend signals."


# ======================================================================
# 邮件 HTML 结构 — 强制浅色模式
# ======================================================================

def _email_header(lang: str = "en", is_paid: bool = False) -> str:
    subtitle = "每周量化策略报告" if lang == "zh" else "Weekly Quantitative Strategy Report"

    # Premium vs Free badge
    if is_paid:
        if lang == "zh":
            badge = '<span style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #78350f; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 1px; margin-top: 10px;">⭐ 高级会员版</span>'
        else:
            badge = '<span style="display: inline-block; background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #78350f; font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 1px; margin-top: 10px;">⭐ PREMIUM</span>'
    else:
        if lang == "zh":
            badge = '<span style="display: inline-block; background: rgba(148,163,184,0.2); color: #94a3b8; font-size: 10px; font-weight: 600; padding: 3px 10px; border-radius: 20px; letter-spacing: 1px; margin-top: 10px;">免费版</span>'
        else:
            badge = '<span style="display: inline-block; background: rgba(148,163,184,0.2); color: #94a3b8; font-size: 10px; font-weight: 600; padding: 3px 10px; border-radius: 20px; letter-spacing: 1px; margin-top: 10px;">FREE EDITION</span>'

    # color-scheme: light only 强制Gmail不做暗色转换
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light only">
    <meta name="supported-color-schemes" content="light only">
    <title>StockQueen Weekly Report</title>
    <style>
        :root {{ color-scheme: light only; }}
        @media (prefers-color-scheme: dark) {{
            .email-body, .content-cell, .metric-card, .table-row-alt, .table-row {{
                background-color: #ffffff !important;
                color: #1e293b !important;
            }}
        }}
    </style>
</head>
<body class="email-body" style="margin: 0; padding: 0; background-color: #eef2f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; -webkit-font-smoothing: antialiased; color-scheme: light only; -webkit-text-size-adjust: none;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#eef2f7" style="background-color: #eef2f7;">
        <tr><td align="center" style="padding: 20px 12px 32px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
        <!-- ====== HEADER ====== -->
        <tr><td bgcolor="#1e1b4b" style="background-color: #1e1b4b; padding: 32px 28px 24px; text-align: center; border-radius: 14px 14px 0 0;">
            <h1 style="margin: 0; font-size: 30px; font-weight: 800;">
                <span style="color: #a5b4fc;">Stock</span><span style="color: #67e8f9;">Queen</span>
            </h1>
            <p style="color: #7c8db5; margin: 6px 0 0; font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase;">{subtitle}</p>
            <p style="margin: 0;">{badge}</p>
        </td></tr>"""


def _email_footer(lang: str = "en", is_free: bool = True) -> str:
    if lang == "zh":
        team = "StockQueen 量化研究团队 | 瑞德资本"
        unsub = "取消订阅"
        website = "访问官网"
        website_url = "https://stockqueen.tech/index-zh.html"
        disclaimer = "本报告仅供教育参考，不构成投资建议。过往业绩不代表未来表现。投资有风险，入市需谨慎。"
    else:
        team = "StockQueen Quant Research | Rayde Capital"
        unsub = "Unsubscribe"
        website = "Visit Website"
        website_url = "https://stockqueen.tech/"
        disclaimer = "For educational purposes only. Not investment advice. Past performance does not guarantee future results."

    upgrade = ""
    if is_free:
        if lang == "zh":
            upgrade = """
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 0 24px 20px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#4f46e5" style="background-color: #4f46e5; padding: 24px; border-radius: 12px; text-align: center;">
                    <p style="color: #e0e7ff; font-size: 15px; margin: 0 0 14px; line-height: 1.6;">想要获取完整买卖信号、进仓价、止损位？</p>
                    <a href="https://stockqueen.tech/subscribe-zh.html" style="display: inline-block; background: #ffffff; color: #4f46e5; padding: 12px 32px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 14px;">升级付费版 →</a>
                </td></tr>
            </table>
        </td></tr>"""
        else:
            upgrade = """
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 0 24px 20px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#4f46e5" style="background-color: #4f46e5; padding: 24px; border-radius: 12px; text-align: center;">
                    <p style="color: #e0e7ff; font-size: 15px; margin: 0 0 14px; line-height: 1.6;">Want full buy/sell signals with entry prices and stop-loss?</p>
                    <a href="https://stockqueen.tech/subscribe.html" style="display: inline-block; background: #ffffff; color: #4f46e5; padding: 12px 32px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 14px;">Upgrade to Premium →</a>
                </td></tr>
            </table>
        </td></tr>"""

    return f"""{upgrade}
        <!-- Disclaimer -->
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 0 24px 20px;">
            <p style="color: #b0b8c8; font-size: 10px; margin: 0; line-height: 1.6; text-align: center; border-top: 1px solid #eef2f7; padding-top: 14px;">{disclaimer}</p>
        </td></tr>
        <!-- ====== FOOTER ====== -->
        <tr><td bgcolor="#0f172a" style="background-color: #0f172a; padding: 24px 28px; text-align: center; border-radius: 0 0 14px 14px;">
            <p style="color: #475569; font-size: 11px; margin: 0 0 8px;">{team}</p>
            <p style="margin: 0; font-size: 11px;">
                <a href="{website_url}" style="color: #818cf8; text-decoration: none; font-weight: 600;">{website}</a>
                <span style="color: #334155;"> &nbsp;|&nbsp; </span>
                <a href="{{{{unsubscribe_url}}}}" style="color: #475569; text-decoration: underline;">{unsub}</a>
            </p>
        </td></tr>
    </table>
        </td></tr>
    </table>
</body>
</html>"""


# ======================================================================
# 内容区块
# ======================================================================

def _open_content() -> str:
    return """
        <tr><td bgcolor="#ffffff" class="content-cell" style="background-color: #ffffff; padding: 24px 24px 0;">"""


def _close_content() -> str:
    return """
        </td></tr>"""


def _section_date_regime(data: dict, lang: str) -> str:
    regime = data.get("market_regime", "UNKNOWN")
    rs = _regime_style(regime)
    label = _regime_label(regime, lang)
    emoji = _regime_emoji(regime)

    if lang == "zh":
        date_str = f"{data['year']}年 第{data['week_number']}周"
    else:
        date_str = f"Week {data['week_number']}, {data['year']}"

    return f"""{_open_content()}
            <!-- Date -->
            <p style="color: #94a3b8; font-size: 12px; margin: 0 0 14px;">{date_str} &middot; {data.get('generated_at', '')}</p>
            <!-- Regime Badge -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
                <tr>
                    <td bgcolor="{rs['bg']}" style="background-color: {rs['bg']}; border: 1px solid {rs['border']}; border-radius: 10px; padding: 14px 18px;">
                        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
                            <td bgcolor="{rs['badge_bg']}" style="background-color: {rs['badge_bg']}; width: 32px; height: 32px; border-radius: 8px; text-align: center; font-size: 15px; line-height: 32px;">{emoji}</td>
                            <td style="padding-left: 12px;">
                                <p style="color: {rs['text']}; font-size: 16px; margin: 0; font-weight: 700;">{label}</p>
                            </td>
                        </tr></table>
                    </td>
                </tr>
            </table>"""


def _section_market_insight(data: dict, lang: str) -> str:
    """策略洞察段落 — 这是让newsletter有灵魂的部分"""
    insight = _generate_market_insight(data, lang)
    title = "本周策略洞察" if lang == "zh" else "Weekly Strategy Insight"

    return f"""
            <!-- Market Insight -->
            <p style="color: #334155; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 8px; color: #6366f1;">{title}</p>
            <p style="color: #334155; font-size: 14px; line-height: 1.75; margin: 0 0 20px;">{insight}</p>"""


def _section_performance(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    avg_return = sum(p.get("return_pct", 0) for p in positions) / len(positions) if positions else 0

    # 使用当年 YTD 数据（时间段一致），避免跨年比较失真
    yearly = data.get("yearly", {})
    current_year = str(data.get("year", "2026"))
    years_list = yearly.get("years", [])
    ytd_entry = next(
        (y for y in years_list if current_year in str(y.get("year", ""))),
        None
    )
    if ytd_entry:
        strategy_total = ytd_entry.get("strategy_return", 0)
        spy_ytd = ytd_entry.get("spy_return", 0)
        alpha = strategy_total - spy_ytd
    else:
        # 降级：用 total 字段但至少 alpha 用 alpha_vs_spy 字段
        total = yearly.get("total", {})
        strategy_total = total.get("strategy_return", 0)
        alpha = total.get("alpha_vs_spy", 0)

    if ytd_entry:
        ytd_label_zh, ytd_label_en = "年度收益 YTD", "YTD Return"
    else:
        ytd_label_zh, ytd_label_en = "累计收益 (6yr)", "Cumulative (6yr)"

    if lang == "zh":
        labels = ("持仓平均", ytd_label_zh, "超额收益 vs SPY")
    else:
        labels = ("Avg Return", ytd_label_en, "Alpha vs SPY")

    def _card(label, value):
        cl = _color(value)
        return f"""<td width="33%" class="metric-card" bgcolor="#f8fafc" style="background-color: #f8fafc; padding: 16px 6px; text-align: center; border-radius: 10px;">
                        <p style="color: #94a3b8; font-size: 10px; margin: 0; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">{label}</p>
                        <p style="color: {cl}; font-size: 24px; font-weight: 800; margin: 4px 0 0;">{_fmt_pct(value)}</p>
                    </td>"""

    return f"""
            <!-- Performance -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="6" style="margin-bottom: 20px; border-collapse: separate;">
                <tr>
                    {_card(labels[0], avg_return)}
                    {_card(labels[1], strategy_total)}
                    {_card(labels[2], alpha)}
                </tr>
            </table>
        {_close_content()}"""


def _th(text: str) -> str:
    # 浅色表头 — 暗模式下反转后仍可读（e0e7ff→深蓝底白字，3730a3→浅色）
    return f'<th bgcolor="#e0e7ff" style="background-color: #e0e7ff; padding: 9px 8px; text-align: right; font-size: 10px; color: #3730a3; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{text}</th>'


def _th_left(text: str) -> str:
    return f'<th bgcolor="#e0e7ff" style="background-color: #e0e7ff; padding: 9px 8px; text-align: left; font-size: 10px; color: #3730a3; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{text}</th>'


def _section_holdings_paid(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    if not positions:
        return ""

    title = "📋 完整持仓明细" if lang == "zh" else "📋 Full Position Details"
    cols = ("标的", "进仓", "现价", "盈亏", "止损", "止盈") if lang == "zh" else ("Ticker", "Entry", "Now", "P&L", "SL", "TP")

    rows = ""
    for i, p in enumerate(positions):
        ret = p.get("return_pct", 0)
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        cls = "table-row-alt" if i % 2 == 0 else "table-row"
        rows += f"""
                    <tr>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; font-weight: 700; color: #1e293b;">{p['ticker']}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #64748b; font-size: 13px;">{_fmt_price(p.get('entry_price'))}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #1e293b; font-size: 13px;">{_fmt_price(p.get('current_price'))}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: right; color: {_color(ret)}; font-weight: 700; font-size: 13px;">{_fmt_pct(ret)}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #dc2626; font-size: 12px;">{_fmt_price(p.get('stop_loss'))}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #16a34a; font-size: 12px;">{_fmt_price(p.get('take_profit'))}</td>
                    </tr>"""

    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; font-size: 13px;">
                <thead><tr>
                    {_th_left(cols[0])}
                    {_th(cols[1])}
                    {_th(cols[2])}
                    {_th(cols[3])}
                    {_th(cols[4])}
                    {_th(cols[5])}
                </tr></thead>
                <tbody>{rows}
                </tbody>
            </table>
        {_close_content()}"""


def _section_holdings_free(data: dict, lang: str) -> str:
    positions = data.get("positions", [])
    if not positions:
        return ""

    title = "💼 当前持仓" if lang == "zh" else "💼 Current Holdings"
    note = "🔒 升级付费版查看完整进仓价、止损位和止盈位" if lang == "zh" else "🔒 Upgrade to see entry prices, stop-loss & take-profit"

    tickers_html = ""
    for p in positions:
        ret = p.get("return_pct", 0)
        cl = _color(ret)
        tickers_html += f"""<td style="padding: 4px;">
                <table role="presentation" cellpadding="0" cellspacing="0"><tr>
                    <td bgcolor="#f1f5f9" style="background-color: #f1f5f9; padding: 8px 14px; border-radius: 8px; border: 1px solid #e2e8f0;">
                        <span style="font-weight: 700; color: #1e293b; font-size: 14px;">{p['ticker']}</span>
                        <span style="color: {cl}; font-size: 12px; font-weight: 600;"> {_fmt_pct(ret)}</span>
                    </td>
                </tr></table>
            </td>"""

    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom: 8px;"><tr>
                {tickers_html}
            </tr></table>
            <p style="color: #94a3b8; font-size: 12px; margin: 6px 0 0;">{note}</p>
        {_close_content()}"""


def _section_pending_entries(data: dict, lang: str) -> str:
    """待入场队列 + 选股理由（rotation_positions.pending_entry + 快照得分）"""
    items = data.get("pending_entries") or []
    if not items:
        return ""

    title = "⏳ 待确认入场（pending_entry）" if lang == "zh" else "⏳ Pending Entry Queue"
    intro = (
        "以下标的已进入待入场队列，尚未记为 active；理由来自体制/周快照多因子得分或对冲层逻辑。"
        if lang == "zh"
        else "Queued for entry — not active yet. Rationale comes from regime + weekly snapshot scores, or hedge-sleeve rules."
    )
    cols = ("标的", "类型", "快照/得分", "止损/止盈", "选股理由") if lang == "zh" else ("Ticker", "Type", "Snapshot / Score", "SL / TP", "Rationale")

    rows = ""
    for i, p in enumerate(items):
        bg = "#fffbeb" if i % 2 == 0 else "#ffffff"
        cls = "table-row-alt" if i % 2 == 0 else "table-row"
        rtxt = p.get("reason_zh") if lang == "zh" else p.get("reason_en")
        ptype = (p.get("position_type") or "alpha").upper()
        snap_d = p.get("snapshot_date") or "—"
        sc = p.get("score")
        if isinstance(sc, (int, float)):
            snap_score = f"{snap_d} · {sc:.2f}"
        else:
            snap_score = snap_d
        sl_tp = f"{_fmt_price(p.get('stop_loss'))} / {_fmt_price(p.get('take_profit'))}"
        rows += f"""
                    <tr>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #fef3c7; font-weight: 700; color: #1e293b;">{p["ticker"]}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #fef3c7; color: #92400e; font-size: 12px;">{ptype}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #fef3c7; text-align: left; color: #64748b; font-size: 12px;">{snap_score}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 8px; border-bottom: 1px solid #fef3c7; text-align: right; color: #64748b; font-size: 12px;">{sl_tp}</td>
                        <td class="{cls}" bgcolor="{bg}" style="background-color: {bg}; padding: 10px 10px; border-bottom: 1px solid #fef3c7; color: #334155; font-size: 13px; line-height: 1.65;">{rtxt}</td>
                    </tr>"""

    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 8px;">{title}</p>
            <p style="color: #64748b; font-size: 13px; line-height: 1.6; margin: 0 0 14px;">{intro}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #fde68a; border-radius: 10px; overflow: hidden; font-size: 13px;">
                <thead><tr>
                    {_th_left(cols[0])}
                    <th bgcolor="#fef3c7" style="background-color: #fef3c7; padding: 9px 8px; text-align: center; font-size: 10px; color: #92400e; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{cols[1]}</th>
                    {_th_left(cols[2])}
                    {_th(cols[3])}
                    {_th_left(cols[4])}
                </tr></thead>
                <tbody>{rows}
                </tbody>
            </table>
        {_close_content()}"""


def _section_new_signals(data: dict, lang: str) -> str:
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])
    if not entries and not exits:
        return ""

    html = ""

    if entries:
        title = f"🟢 本周新买入 ({len(entries)})" if lang == "zh" else f"🟢 New Buy Signals ({len(entries)})"
        entry_col = "进仓价" if lang == "zh" else "Entry"
        sl_col = "止损" if lang == "zh" else "SL"
        tp_col = "止盈" if lang == "zh" else "TP"

        rows = ""
        for i, p in enumerate(entries):
            bg = "#f0fdf4" if i % 2 == 0 else "#ffffff"
            rows += f"""
                    <tr>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #dcfce7; font-weight: 700; color: #14532d;">{p['ticker']}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #dcfce7; text-align: right; color: #1e293b;">{_fmt_price(p.get('entry_price'))}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #dcfce7; text-align: right; color: #dc2626;">{_fmt_price(p.get('stop_loss'))}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #dcfce7; text-align: right; color: #16a34a;">{_fmt_price(p.get('take_profit'))}</td>
                    </tr>"""

        html += f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border: 2px solid #22c55e; border-radius: 10px; overflow: hidden;">
                <thead><tr>
                    <th bgcolor="#dcfce7" style="background-color: #dcfce7; padding: 9px 12px; text-align: left; font-size: 10px; color: #14532d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">Ticker</th>
                    <th bgcolor="#dcfce7" style="background-color: #dcfce7; padding: 9px 12px; text-align: right; font-size: 10px; color: #14532d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{entry_col}</th>
                    <th bgcolor="#dcfce7" style="background-color: #dcfce7; padding: 9px 12px; text-align: right; font-size: 10px; color: #14532d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{sl_col}</th>
                    <th bgcolor="#dcfce7" style="background-color: #dcfce7; padding: 9px 12px; text-align: right; font-size: 10px; color: #14532d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{tp_col}</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        {_close_content()}"""

    if exits:
        title = f"🔴 本周卖出 ({len(exits)})" if lang == "zh" else f"🔴 Exit Signals ({len(exits)})"
        entry_col = "进仓价" if lang == "zh" else "Entry"
        ret_col = "收益" if lang == "zh" else "Return"

        rows = ""
        for i, p in enumerate(exits):
            ret = p.get("return_pct", 0)
            bg = "#fef2f2" if i % 2 == 0 else "#ffffff"
            rows += f"""
                    <tr>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #fecaca; font-weight: 700; color: #7f1d1d;">{p['ticker']}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #fecaca; text-align: right; color: #1e293b;">{_fmt_price(p.get('entry_price'))}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 12px; border-bottom: 1px solid #fecaca; text-align: right; color: {_color(ret)}; font-weight: 700;">{_fmt_pct(ret)}</td>
                    </tr>"""

        html += f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border: 2px solid #ef4444; border-radius: 10px; overflow: hidden;">
                <thead><tr>
                    <th bgcolor="#fee2e2" style="background-color: #fee2e2; padding: 9px 12px; text-align: left; font-size: 10px; color: #7f1d1d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">Ticker</th>
                    <th bgcolor="#fee2e2" style="background-color: #fee2e2; padding: 9px 12px; text-align: right; font-size: 10px; color: #7f1d1d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{entry_col}</th>
                    <th bgcolor="#fee2e2" style="background-color: #fee2e2; padding: 9px 12px; text-align: right; font-size: 10px; color: #7f1d1d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;">{ret_col}</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        {_close_content()}"""

    return html


_EXCLUDE_TICKERS = {"AXTI"}  # 手动排除（数据异常等）


def _section_recent_exits(data: dict, lang: str) -> str:
    exits = [e for e in data.get("recent_exits", []) if e.get("ticker") not in _EXCLUDE_TICKERS]
    if not exits:
        return ""

    title = "📊 本周平仓回顾" if lang == "zh" else "📊 Closed Trades"
    cols = ("标的", "收益", "持有") if lang == "zh" else ("Ticker", "Return", "Hold")

    rows = ""
    for i, t in enumerate(exits[:6]):
        ret = t.get("return_pct", 0)
        days = t.get("hold_days", 0)
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        rows += f"""
                    <tr>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 14px; border-bottom: 1px solid #f1f5f9; font-weight: 700; color: #1e293b;">{t.get('ticker', '')}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 14px; border-bottom: 1px solid #f1f5f9; text-align: right; color: {_color(ret)}; font-weight: 700;">{_fmt_pct(ret)}</td>
                        <td bgcolor="{bg}" style="background-color: {bg}; padding: 10px 14px; border-bottom: 1px solid #f1f5f9; text-align: right; color: #94a3b8; font-size: 13px;">{days}d</td>
                    </tr>"""

    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden;">
                <thead><tr>
                    {_th_left(cols[0])}
                    {_th(cols[1])}
                    {_th(cols[2])}
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        {_close_content()}"""


def _section_signal_count_cta(data: dict, lang: str) -> str:
    """Free 版的锁定信号预告 — 显示数量但隐藏细节，强烈升级CTA"""
    entries = data.get("new_entries", [])
    exits = data.get("new_exits", [])
    total = len(entries) + len(exits)
    if total == 0:
        return ""

    if lang == "zh":
        url = "https://stockqueen.tech/subscribe-zh.html"
        # 构建锁定的信号预告
        entry_tickers = ", ".join([e['ticker'] for e in entries[:2]]) + ("..." if len(entries) > 2 else "") if entries else ""
        exit_tickers = ", ".join([e['ticker'] for e in exits[:2]]) + ("..." if len(exits) > 2 else "") if exits else ""

        locked_items = ""
        if entries:
            locked_items += f"""
                        <tr><td style="padding: 8px 0;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                                <td bgcolor="#f0fdf4" style="background-color: #f0fdf4; padding: 12px 16px; border-radius: 8px; border: 1px solid #bbf7d0;">
                                    <p style="margin: 0; font-size: 14px; color: #14532d; font-weight: 700;">🟢 {len(entries)} 个新买入信号</p>
                                    <p style="margin: 4px 0 0; font-size: 12px; color: #16a34a;">{entry_tickers} — <span style="color: #94a3b8;">进仓价/止损/止盈 🔒</span></p>
                                </td>
                            </tr></table>
                        </td></tr>"""
        if exits:
            locked_items += f"""
                        <tr><td style="padding: 8px 0;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                                <td bgcolor="#fef2f2" style="background-color: #fef2f2; padding: 12px 16px; border-radius: 8px; border: 1px solid #fecaca;">
                                    <p style="margin: 0; font-size: 14px; color: #7f1d1d; font-weight: 700;">🔴 {len(exits)} 个卖出信号</p>
                                    <p style="margin: 4px 0 0; font-size: 12px; color: #dc2626;">{exit_tickers} — <span style="color: #94a3b8;">进仓价/收益率 🔒</span></p>
                                </td>
                            </tr></table>
                        </td></tr>"""

        return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 16px 24px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f8fafc" style="background-color: #f8fafc; border: 2px dashed #818cf8; padding: 20px; border-radius: 12px;">
                    <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 8px; text-align: center;">🔐 本周 {total} 个交易信号</p>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{locked_items}
                    </table>
                    <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 16px auto 0;"><tr>
                        <td bgcolor="#4f46e5" style="background-color: #4f46e5; border-radius: 8px;">
                            <a href="{url}" style="display: inline-block; color: #ffffff; padding: 12px 32px; text-decoration: none; font-weight: 700; font-size: 14px;">🔓 解锁完整信号 →</a>
                        </td>
                    </tr></table>
                </td></tr>
            </table>
        </td></tr>"""
    else:
        url = "https://stockqueen.tech/subscribe.html"
        entry_tickers = ", ".join([e['ticker'] for e in entries[:2]]) + ("..." if len(entries) > 2 else "") if entries else ""
        exit_tickers = ", ".join([e['ticker'] for e in exits[:2]]) + ("..." if len(exits) > 2 else "") if exits else ""

        locked_items = ""
        if entries:
            locked_items += f"""
                        <tr><td style="padding: 8px 0;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                                <td bgcolor="#f0fdf4" style="background-color: #f0fdf4; padding: 12px 16px; border-radius: 8px; border: 1px solid #bbf7d0;">
                                    <p style="margin: 0; font-size: 14px; color: #14532d; font-weight: 700;">🟢 {len(entries)} New Buy Signal{'s' if len(entries) > 1 else ''}</p>
                                    <p style="margin: 4px 0 0; font-size: 12px; color: #16a34a;">{entry_tickers} — <span style="color: #94a3b8;">Entry/SL/TP 🔒</span></p>
                                </td>
                            </tr></table>
                        </td></tr>"""
        if exits:
            locked_items += f"""
                        <tr><td style="padding: 8px 0;">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                                <td bgcolor="#fef2f2" style="background-color: #fef2f2; padding: 12px 16px; border-radius: 8px; border: 1px solid #fecaca;">
                                    <p style="margin: 0; font-size: 14px; color: #7f1d1d; font-weight: 700;">🔴 {len(exits)} Exit Signal{'s' if len(exits) > 1 else ''}</p>
                                    <p style="margin: 4px 0 0; font-size: 12px; color: #dc2626;">{exit_tickers} — <span style="color: #94a3b8;">Entry/Return 🔒</span></p>
                                </td>
                            </tr></table>
                        </td></tr>"""

        return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 16px 24px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f8fafc" style="background-color: #f8fafc; border: 2px dashed #818cf8; padding: 20px; border-radius: 12px;">
                    <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 8px; text-align: center;">🔐 {total} Trading Signals This Week</p>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{locked_items}
                    </table>
                    <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 16px auto 0;"><tr>
                        <td bgcolor="#4f46e5" style="background-color: #4f46e5; border-radius: 8px;">
                            <a href="{url}" style="display: inline-block; color: #ffffff; padding: 12px 32px; text-decoration: none; font-weight: 700; font-size: 14px;">🔓 Unlock Full Signals →</a>
                        </td>
                    </tr></table>
                </td></tr>
            </table>
        </td></tr>"""


def _section_watchlist(data: dict, lang: str, editorial: dict = None) -> str:
    """下周关注/展望 — 优先使用 editorial 中的 next_week_outlook，否则自动生成"""
    editorial = editorial or {}
    outlook = editorial.get("next_week_outlook", {})
    custom_text = outlook.get(lang, outlook.get("en", ""))
    if custom_text:
        # 将换行符转为 <br> 以在 HTML 中正确显示
        note = custom_text.replace("\n\n", "<br><br>").replace("\n", "<br>")
    else:
        note = _generate_watchlist_note(data, lang)
    title = "🔮 下周展望" if lang == "zh" else "🔮 Next Week Outlook"
    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f0f4ff" style="background-color: #f0f4ff; padding: 16px 18px; border-radius: 10px; border-left: 4px solid #6366f1;">
                    <p style="color: #334155; font-size: 13px; line-height: 1.7; margin: 0;">{note}</p>
                </td></tr>
            </table>
        {_close_content()}"""


def _section_stats(data: dict, lang: str) -> str:
    summary = data.get("trade_summary", {})
    if not summary:
        return ""

    title = "📈 策略统计" if lang == "zh" else "📈 Strategy Stats"
    labels = ("总交易", "胜率", "平均收益", "持仓天数") if lang == "zh" else ("Trades", "Win Rate", "Avg Return", "Hold")

    total_trades = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate", 0)
    avg_ret = summary.get("avg_return", 0)
    avg_days = summary.get("avg_hold_days", 0)

    def _stat(label, val, color="#1e293b"):
        return f"""<td width="25%" bgcolor="#f8fafc" style="background-color: #f8fafc; padding: 12px 4px; text-align: center; border-radius: 8px;">
                        <p style="color: #94a3b8; font-size: 9px; margin: 0; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600;">{label}</p>
                        <p style="color: {color}; font-size: 18px; font-weight: 800; margin: 3px 0 0;">{val}</p>
                    </td>"""

    return f"""{_open_content()}
            <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 12px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="4" style="border-collapse: separate;">
                <tr>
                    {_stat(labels[0], str(total_trades))}
                    {_stat(labels[1], _fmt_pct(win_rate, with_sign=False), "#0891b2")}
                    {_stat(labels[2], _fmt_pct(avg_ret), _color(avg_ret))}
                    {_stat(labels[3], f"{avg_days:.0f}d")}
                </tr>
            </table>
        {_close_content()}"""


def _section_cta_button(data: dict, lang: str) -> str:
    text = "查看完整报告 →" if lang == "zh" else "View Full Report →"
    url = "https://stockqueen.tech/weekly-report/index-zh.html" if lang == "zh" else "https://stockqueen.tech/weekly-report/"
    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 20px 24px 24px; text-align: center;">
            <a href="{url}"
               style="display: inline-block; background-color: #4f46e5; color: #ffffff; padding: 14px 36px; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 15px;">
                {text}
            </a>
        </td></tr>"""


# ======================================================================
# 富内容区块（付费版专属）
# ======================================================================

def _section_strategy_pulse(editorial: dict, lang: str) -> str:
    """策略脉搏 — 本周关键决策背后的思考"""
    pulse = editorial.get("strategy_pulse", {})
    text = pulse.get(lang, pulse.get("en", ""))
    if not text:
        return ""

    title = "📡 本周策略脉搏" if lang == "zh" else "📡 Strategy Pulse"
    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 20px 24px 0;">
            <p style="color: #6366f1; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px;">{title}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f0f4ff" style="background-color: #f0f4ff; padding: 18px 20px; border-radius: 10px; border-left: 4px solid #6366f1;">
                    <p style="color: #1e293b; font-size: 14px; line-height: 1.8; margin: 0;">{text}</p>
                </td></tr>
            </table>
        </td></tr>"""


def _section_quant_insight(editorial: dict, lang: str) -> str:
    """量化洞察 — 每周深度分析，付费版核心价值"""
    insight = editorial.get("quant_insight", {})
    title_key = "title_zh" if lang == "zh" else "title_en"
    body_key = "body_zh" if lang == "zh" else "body_en"
    title = insight.get(title_key, "")
    body = insight.get(body_key, "")
    if not title or not body:
        return ""

    section_label = "💡 量化洞察" if lang == "zh" else "💡 Quant Insight"
    # 将换行符转为<br>
    body_html = body.replace("\n\n", "</p><p style='color: #334155; font-size: 14px; line-height: 1.8; margin: 12px 0 0;'>").replace("\n", "<br>")

    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 20px 24px 0;">
            <!-- 分隔线 -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
                <tr><td style="border-top: 2px solid #e0e7ff; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
            <p style="color: #6366f1; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px;">{section_label}</p>
            <p style="color: #1e293b; font-size: 18px; font-weight: 800; margin: 0 0 14px; line-height: 1.4;">{title}</p>
            <p style="color: #334155; font-size: 14px; line-height: 1.8; margin: 0 0 0;">{body_html}</p>
        </td></tr>"""


def _section_strategy_notes(editorial: dict, lang: str) -> str:
    """策略更新备注 — 模型变化/因子调整透明披露"""
    notes = editorial.get("strategy_notes", {})
    text = notes.get(lang, notes.get("en", ""))
    if not text:
        return ""

    title = "🔧 策略更新" if lang == "zh" else "🔧 Strategy Notes"
    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 16px 24px 0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#fffbeb" style="background-color: #fffbeb; padding: 16px 18px; border-radius: 10px; border-left: 4px solid #f59e0b;">
                    <p style="color: #92400e; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin: 0 0 6px;">{title}</p>
                    <p style="color: #78350f; font-size: 13px; line-height: 1.7; margin: 0;">{text}</p>
                </td></tr>
            </table>
        </td></tr>"""


def _section_blog_feature(editorial: dict, lang: str) -> str:
    """博客精选 — 连接Newsletter和内容库，免费版也有（引流）"""
    blog = editorial.get("blog_feature", {})
    title_key = "title_zh" if lang == "zh" else "title_en"
    summary_key = "summary_zh" if lang == "zh" else "summary_en"
    url_key = "url_zh" if lang == "zh" else "url_en"

    title = blog.get(title_key, "")
    summary = blog.get(summary_key, "")
    url = blog.get(url_key, "https://stockqueen.tech/blog/")
    if not title:
        return ""

    section_label = "📝 本周博客" if lang == "zh" else "📝 From the Blog"
    read_more = "阅读全文 →" if lang == "zh" else "Read More →"

    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 20px 24px 0;">
            <!-- 分隔线 -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
                <tr><td style="border-top: 1px solid #f1f5f9; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
            <p style="color: #0891b2; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px;">{section_label}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f0f9ff" style="background-color: #f0f9ff; padding: 18px 20px; border-radius: 10px; border: 1px solid #bae6fd;">
                    <p style="color: #1e293b; font-size: 15px; font-weight: 700; margin: 0 0 8px; line-height: 1.4;">{title}</p>
                    <p style="color: #475569; font-size: 13px; line-height: 1.7; margin: 0 0 14px;">{summary}</p>
                    <a href="{url}" style="display: inline-block; color: #0284c7; font-size: 13px; font-weight: 700; text-decoration: none;">{read_more}</a>
                </td></tr>
            </table>
        </td></tr>"""


def _section_product_news(editorial: dict, lang: str) -> str:
    """产品动态 — 功能上线/版本更新"""
    news = editorial.get("product_news", {})
    if not news.get("has_update", False):
        return ""

    title_key = "title_zh" if lang == "zh" else "title_en"
    body_key = "body_zh" if lang == "zh" else "body_en"
    url_key = "url_zh" if lang == "zh" else "url_en"

    title = news.get(title_key, "")
    body = news.get(body_key, "")
    url = news.get(url_key, "")
    if not title:
        return ""

    section_label = "🚀 产品动态" if lang == "zh" else "🚀 Product News"
    detail_link = f'<a href="{url}" style="color: #7c3aed; font-size: 12px; font-weight: 700; text-decoration: none;">{"了解详情 →" if lang == "zh" else "Learn More →"}</a>' if url else ""

    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 16px 24px 0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#faf5ff" style="background-color: #faf5ff; padding: 16px 18px; border-radius: 10px; border: 1px solid #e9d5ff;">
                    <p style="color: #6d28d9; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin: 0 0 6px;">{section_label}</p>
                    <p style="color: #4c1d95; font-size: 14px; font-weight: 700; margin: 0 0 6px;">{title}</p>
                    <p style="color: #5b21b6; font-size: 13px; line-height: 1.7; margin: 0 0 10px;">{body}</p>
                    {detail_link}
                </td></tr>
            </table>
        </td></tr>"""


def _section_free_teaser_insight(editorial: dict, lang: str) -> str:
    """免费版洞察预告 — 让读者看到付费内容的价值，驱动升级"""
    teaser = editorial.get("free_teaser_insight", {})
    text = teaser.get(lang, teaser.get("en", ""))
    if not text:
        return ""

    if lang == "zh":
        upgrade_url = "https://stockqueen.tech/subscribe-zh.html#premium"
        upgrade_text = "升级付费版，获取完整深度分析 →"
        label = "💡 本周洞察预览"
    else:
        upgrade_url = "https://stockqueen.tech/subscribe.html#premium"
        upgrade_text = "Upgrade for full deep-dive analysis →"
        label = "💡 This Week's Insight Preview"

    return f"""
        <tr><td bgcolor="#ffffff" style="background-color: #ffffff; padding: 20px 24px 0;">
            <!-- 分隔线 -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 20px;">
                <tr><td style="border-top: 1px solid #f1f5f9; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
            <p style="color: #6366f1; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px;">{label}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr><td bgcolor="#f8fafc" style="background-color: #f8fafc; padding: 18px 20px; border-radius: 10px; border: 1px solid #e2e8f0;">
                    <p style="color: #334155; font-size: 14px; line-height: 1.8; margin: 0 0 16px;">{text}</p>
                    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
                        <td bgcolor="#4f46e5" style="background-color: #4f46e5; border-radius: 8px;">
                            <a href="{upgrade_url}" style="display: inline-block; color: #ffffff; padding: 10px 24px; text-decoration: none; font-weight: 700; font-size: 13px;">{upgrade_text}</a>
                        </td>
                    </tr></table>
                </td></tr>
            </table>
        </td></tr>"""


# ======================================================================
# 渲染器
# ======================================================================

class NewsletterRenderer:
    def render_free(self, data: dict, lang: str = "en", editorial: dict = None) -> str:
        """
        免费版：暂时与付费版内容一致（付费体系搭建前）
        editorial: weekly_content_template.json 内容
        """
        return self.render_paid(data, lang=lang, editorial=editorial)

    def render_paid(self, data: dict, lang: str = "en", editorial: dict = None) -> str:
        """
        付费版：完整信号 + 策略脉搏 + 量化洞察 + 博客精选 + 产品动态
        editorial: weekly_content_template.json 内容
        """
        editorial = editorial or {}
        html = _email_header(lang, is_paid=True)
        html += _section_date_regime(data, lang)
        html += _section_strategy_pulse(editorial, lang)       # 策略脉搏（付费专属）
        html += _section_performance(data, lang)
        html += _section_new_signals(data, lang)               # 完整买卖信号
        html += _section_holdings_paid(data, lang)             # 完整持仓表
        html += _section_pending_entries(data, lang)          # pending_entry + 选股理由
        html += _section_recent_exits(data, lang)
        html += _section_quant_insight(editorial, lang)        # 量化深度分析（核心价值）
        html += _section_strategy_notes(editorial, lang)       # 策略更新透明披露
        html += _section_blog_feature(editorial, lang)         # 博客精选
        html += _section_product_news(editorial, lang)         # 产品动态
        html += _section_watchlist(data, lang, editorial)      # 下周展望
        html += _section_stats(data, lang)
        html += _section_cta_button(data, lang)
        html += _email_footer(lang, is_free=False)
        return html

    def render_all(self, data: dict, editorial: dict = None) -> dict:
        return {
            "free-zh": self.render_free(data, lang="zh", editorial=editorial),
            "free-en": self.render_free(data, lang="en", editorial=editorial),
            "paid-zh": self.render_paid(data, lang="zh", editorial=editorial),
            "paid-en": self.render_paid(data, lang="en", editorial=editorial),
        }
