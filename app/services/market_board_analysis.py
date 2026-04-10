"""
整体大盘板块：基于 ETF 快照涨跌幅的启发式中文总结（非投资建议）。

规则尽量保守：数据缺失则跳过该条，避免臆测。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pct(qmap: Dict[str, Any], ticker: str) -> Optional[float]:
    q = qmap.get(ticker.upper())
    if not q:
        return None
    v = q.get("change_percent")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_pct(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def build_market_board_analysis(quotes_raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    返回供 Jinja 使用的 analysis 字典；报价过少时返回 None。
    """
    if not quotes_raw:
        return None

    def p(t: str) -> Optional[float]:
        return _pct(quotes_raw, t)

    bullets: List[Dict[str, str]] = []

    spy, iwm, qqq, smh = p("SPY"), p("IWM"), p("QQQ"), p("SMH")
    if spy is not None and iwm is not None:
        diff = iwm - spy
        if diff > 0.25:
            bullets.append({
                "text": f"广度：小盘（IWM {_fmt_pct(iwm)}）相对强于标普（SPY {_fmt_pct(spy)}），资金风险偏好偏广谱。",
                "li_class": "text-sq-green",
            })
        elif diff < -0.25:
            bullets.append({
                "text": f"广度：大盘（SPY {_fmt_pct(spy)}）强于小盘（IWM {_fmt_pct(iwm)}），注意是否权重股撑指数、内部分化。",
                "li_class": "text-amber-400/90",
            })
        else:
            bullets.append({
                "text": f"广度：大小盘日内接近（SPY {_fmt_pct(spy)} vs IWM {_fmt_pct(iwm)}），等待收盘确认方向。",
                "li_class": "text-gray-300",
            })

    hyg = p("HYG")
    if hyg is not None:
        if hyg > 0.12:
            bullets.append({
                "text": f"信用：高收益债 HYG {_fmt_pct(hyg)}，短线偏愿意承担信用风险。",
                "li_class": "text-sq-green",
            })
        elif hyg < -0.12:
            bullets.append({
                "text": f"信用：HYG {_fmt_pct(hyg)} 走弱，风险偏好有所收敛，可与股指交叉验证。",
                "li_class": "text-sq-red",
            })
        else:
            bullets.append({
                "text": f"信用：HYG {_fmt_pct(hyg)}，变化不大。",
                "li_class": "text-gray-400",
            })

    vixy = p("VIXY")
    if vixy is not None:
        if vixy > 0.35:
            bullets.append({
                "text": f"波动：VIXY（波动率期货 ETF）{_fmt_pct(vixy)}，短线避险情绪升温。",
                "li_class": "text-amber-400/90",
            })
        elif vixy < -0.2:
            bullets.append({
                "text": f"波动：VIXY {_fmt_pct(vixy)}，短线恐慌情绪缓和。",
                "li_class": "text-gray-300",
            })
        else:
            bullets.append({
                "text": f"波动：VIXY {_fmt_pct(vixy)}，波动率中性。",
                "li_class": "text-gray-400",
            })

    shy, ief, tlt = p("SHY"), p("IEF"), p("TLT")
    if all(x is not None for x in (shy, ief, tlt)):
        if shy < -0.05 and ief < -0.05 and tlt < -0.05:
            bullets.append({
                "text": "久期：短/中/长国债 ETF 普遍走弱（价格下跌），若对应收益率上行，对高估值成长股偏压制，需结合实盘利率。",
                "li_class": "text-amber-400/90",
            })
        elif shy > 0.05 and ief > 0.05 and tlt > 0.05:
            bullets.append({
                "text": "久期：国债 ETF 普遍走强（价格上涨），债市偏强，对成长股估值相对友好。",
                "li_class": "text-sq-green",
            })
        else:
            bullets.append({
                "text": f"久期：SHY/ IEF/ TLT 分化（{_fmt_pct(shy)} / {_fmt_pct(ief)} / {_fmt_pct(tlt)}），曲线可能在变陡或变平，建议对照现券收益率。",
                "li_class": "text-gray-300",
            })
    elif tlt is not None:
        bullets.append({
            "text": f"长端：TLT {_fmt_pct(tlt)}（国债 ETF 价格；与收益率方向通常相反）。",
            "li_class": "text-gray-300",
        })

    uup, fxy = p("UUP"), p("FXY")
    if uup is not None:
        uup_txt = f"美元多头 UUP {_fmt_pct(uup)}"
        if fxy is not None:
            uup_txt += f"；日元 ETF FXY {_fmt_pct(fxy)}（与 USDJPY 大体反向，可作套息情绪参考）"
        bullets.append({"text": uup_txt + "。", "li_class": "text-gray-300"})

    gld, uso, cper = p("GLD"), p("USO"), p("CPER")
    if any(x is not None for x in (gld, uso, cper)):
        parts = []
        if gld is not None:
            parts.append(f"黄金 {_fmt_pct(gld)}")
        if uso is not None:
            parts.append(f"原油 {_fmt_pct(uso)}")
        if cper is not None:
            parts.append(f"铜 {_fmt_pct(cper)}")
        bullets.append({
            "text": "商品：" + " · ".join(parts) + "（铜偏宏观景气预期）。",
            "li_class": "text-gray-300",
        })

    xlk, xle, arkk = p("XLK"), p("XLE"), p("ARKK")
    if smh is not None and qqq is not None and smh - qqq > 0.2:
        bullets.append({
            "text": f"成长：半导体 SMH {_fmt_pct(smh)} 相对纳指 QQQ {_fmt_pct(qqq)} 更强，科技链偏强。",
            "li_class": "text-sq-green",
        })
    if arkk is not None and abs(arkk) > 0.25:
        bullets.append({
            "text": f"情绪：ARKK {_fmt_pct(arkk)}，高 Beta 成长情绪{'偏热' if arkk > 0 else '偏弱'}。",
            "li_class": "text-violet-300/90" if arkk > 0 else "text-gray-400",
        })
    if xle is not None and xlk is not None and xle - xlk > 0.2:
        bullets.append({
            "text": f"板块：能源 XLE 相对科技 XLK 更强，关注油价与通胀预期联动。",
            "li_class": "text-amber-400/90",
        })

    if not bullets:
        return None

    risk_on = 0
    if spy is not None and spy > 0:
        risk_on += 1
    if hyg is not None and hyg > 0:
        risk_on += 1
    if vixy is not None and vixy < 0:
        risk_on += 1
    risk_off = 0
    if spy is not None and spy < 0:
        risk_off += 1
    if hyg is not None and hyg < 0:
        risk_off += 1
    if vixy is not None and vixy > 0.25:
        risk_off += 1

    if risk_on >= 2 and risk_off <= 1:
        headline = "综合观感：短线偏 risk-on（股指/信用/波动等信号多数偏暖），仍注意广度与久期。"
        tone = "green"
    elif risk_off >= 2 and risk_on <= 1:
        headline = "综合观感：偏 risk-off 或防御（股指/信用/波动等信号偏冷），宜控节奏。"
        tone = "red"
    else:
        headline = "综合观感：指标分化，单一维度勿过度解读；建议交叉验证后再定调。"
        tone = "amber"

    return {
        "headline": headline,
        "tone": tone,
        "bullets": bullets[:8],
        "disclaimer": "由 ETF 快照涨跌幅规则自动生成，仅供盘中快速扫读，不构成投资建议；名义收益率与即期汇率请以专业终端为准。",
    }
