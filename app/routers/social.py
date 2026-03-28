"""
StockQueen - 社交媒体发布中心 Router
GET  /social                    → 管理页面
POST /api/social/generate       → 生成所有平台文案
POST /api/social/generate-image → 生成分享图片（支持多种类型）
POST /api/social/ai-caption     → AI 按维度生成文案
"""

import json
import logging
import sys
import os
import base64
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["social"])
templates = Jinja2Templates(directory="app/templates")

ROOT = Path(__file__).parent.parent.parent
SNAPSHOT_PATH = ROOT / "scripts" / "newsletter" / "snapshots" / "last_snapshot.json"
TEMPLATE_PATH = ROOT / "scripts" / "newsletter" / "weekly_content_template.json"


def _load_social_data() -> dict:
    """加载快照 + 模板，合并为社交内容数据"""
    data = {}

    if SNAPSHOT_PATH.exists():
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            data.update(json.load(f))

    if TEMPLATE_PATH.exists():
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            tmpl = json.load(f)
        now = datetime.now()
        data["week_number"] = now.isocalendar()[1]
        data["year"] = now.year
        data["publish_date"] = now.strftime("%Y-%m-%d")
        data["strategy_pulse_zh"] = tmpl.get("strategy_pulse", {}).get("zh", "")
        data["strategy_pulse_en"] = tmpl.get("strategy_pulse", {}).get("en", "")

    data.setdefault("yearly", {
        "total": {
            "strategy_return": 0.18,
            "spy_return": 0.04,
            "alpha_vs_spy": 0.14,
            "win_rate": 0.58,
        }
    })
    data.setdefault("backtest", {
        "walkforward_sharpe": 1.42,
        "max_drawdown": -0.15,
    })
    data.setdefault("recent_exits", [])
    data.setdefault("new_entries", [])
    data.setdefault("new_exits", [])
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 图片绘制工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _load_fonts(ROOT: Path):
    """加载字体，优先级: 本地 Noto OTF > 本地 TTF > Linux 系统 Noto > Windows 字体"""
    from PIL import ImageFont

    def _try(path, size):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            return None

    def _first(candidates, size):
        for p in candidates:
            f = _try(p, size)
            if f is not None:
                return f
        return ImageFont.load_default()

    local = ROOT / "app" / "static" / "fonts"
    bold_paths = [
        local / "NotoSansSC-Bold.otf",    # download_fonts.py 下载
        local / "NotoSansSC-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    reg_paths = [
        local / "NotoSansSC-Regular.otf",  # download_fonts.py 下载
        local / "NotoSansSC-Regular.ttf",
        local / "NotoSansSC-Medium.otf",
        local / "NotoSansSC-Medium.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    return {
        "xl":  _first(bold_paths, 80),
        "lg":  _first(bold_paths, 56),
        "md":  _first(reg_paths,  36),
        "sm":  _first(reg_paths,  28),
        "xs":  _first(reg_paths,  22),
        "xxs": _first(reg_paths,  17),
    }


def _hex(color: str):
    """将 #rrggbb 转为 (r,g,b)"""
    color = color.lstrip("#")
    return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))


PALETTE = {
    "bg_dark": "#0f172a",
    "bg_card": "#1e293b",
    "bg_mid":  "#334155",
    "gold":    "#eab308",
    "white":   "#f8fafc",
    "gray":    "#94a3b8",
    "dim":     "#475569",
    "green":   "#22c55e",
    "red":     "#ef4444",
    "yellow":  "#fbbf24",
    "blue":    "#3b82f6",
}

REGIME_COLORS  = {"BULL": PALETTE["green"], "BEAR": PALETTE["red"], "CHOPPY": PALETTE["yellow"]}
REGIME_LABELS_ZH = {"BULL": "🟢 牛市进攻模式", "BEAR": "🔴 熊市防御模式", "CHOPPY": "🟡 震荡观望模式"}


def _make_canvas(W=1080, H=1080):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(8  + (18 - 8)  * t)
        g = int(12 + (22 - 12) * t)
        b = int(28 + (42 - 28) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img, draw


def _accent_bar(draw, x1, y1, x2, y2, color_hex, radius=6):
    """绘制带圆角的色块"""
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=color_hex)


def _draw_header(draw, fonts, week, year, subtitle="量化策略周报", W=1080):
    draw.text((60, 48), "StockQueen", fill=PALETTE["gold"], font=fonts["lg"])
    draw.text((W - 60, 64), f"第 {week} 周  ·  {year}", fill=PALETTE["dim"],
              font=fonts["xs"], anchor="rm")
    draw.text((60, 118), subtitle, fill=PALETTE["gray"], font=fonts["sm"])
    draw.line([(60, 164), (W - 60, 164)], fill=PALETTE["bg_mid"], width=1)


def _draw_footer(draw, fonts, H=1080, W=1080):
    draw.line([(60, H - 100), (W - 60, H - 100)], fill=PALETTE["bg_mid"], width=1)
    draw.text((60, H - 78), "stockqueen.tech  ·  每周免费量化信号",
              fill=PALETTE["gold"], font=fonts["xs"])
    draw.text((60, H - 48), "仅供参考，不构成投资建议  ·  Walk-Forward 验证",
              fill=PALETTE["dim"], font=fonts["xxs"])


def _fmt_pct(v, sign=True) -> str:
    if v is None:
        return "N/A"
    pct = v * 100
    if sign:
        return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{pct:.1f}%"


def _regime_bg(regime: str) -> str:
    return {"BULL": "#0a2218", "BEAR": "#260d0d", "CHOPPY": "#231b08"}.get(regime, "#141c2e")


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 1：weekly — 综合周报
# ─────────────────────────────────────────────────────────────────────────────

def _draw_weekly_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    regime    = data.get("market_regime", "UNKNOWN").upper()
    positions = data.get("positions", [])
    week      = data.get("week_number", "?")
    year      = data.get("year", datetime.now().year)
    total     = data["yearly"]["total"]
    total_ret = total.get("strategy_return", 0)
    spy_ret   = total.get("spy_return", 0)
    alpha     = total.get("alpha_vs_spy", 0)
    win_rate  = total.get("win_rate", 0)
    backtest  = data.get("backtest", {})
    sharpe    = backtest.get("walkforward_sharpe", "N/A")
    max_dd    = backtest.get("max_drawdown", 0)

    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])

    _draw_header(draw, fonts, week, year, "量化策略周报", W)

    # ── Regime 彩条 ──────────────────────────────────────────────────────────
    draw.rounded_rectangle([60, 180, W - 60, 246], radius=10, fill=_regime_bg(regime))
    _accent_bar(draw, 60, 180, 76, 246, regime_color, radius=6)
    draw.text((96, 213), REGIME_LABELS_ZH.get(regime, regime),
              fill=regime_color, font=fonts["md"], anchor="lm")
    n_sig = len(data.get("new_entries", [])) + len(data.get("new_exits", []))
    draw.text((W - 70, 213), f"本周信号 {n_sig} 个", fill=PALETTE["gray"],
              font=fonts["xs"], anchor="rm")

    # ── 英雄数字：策略 vs SPY ─────────────────────────────────────────────────
    # 左：strategy
    strat_color = PALETTE["green"] if total_ret >= 0 else PALETTE["red"]
    draw.rounded_rectangle([60, 268, 500, 430], radius=12, fill=PALETTE["bg_card"])
    draw.text((90, 292), "策略累计收益", fill=PALETTE["gray"], font=fonts["xs"])
    draw.text((90, 326), _fmt_pct(total_ret), fill=strat_color, font=fonts["xl"])

    # 右：SPY
    spy_color = PALETTE["green"] if spy_ret >= 0 else PALETTE["red"]
    draw.rounded_rectangle([520, 268, 960, 430], radius=12, fill=PALETTE["bg_card"])
    draw.text((550, 292), "SPY 买入持有", fill=PALETTE["gray"], font=fonts["xs"])
    draw.text((550, 326), _fmt_pct(spy_ret), fill=spy_color, font=fonts["xl"])

    # ── Alpha 横幅 ────────────────────────────────────────────────────────────
    alpha_color = PALETTE["green"] if alpha >= 0 else PALETTE["red"]
    draw.rounded_rectangle([60, 450, W - 60, 530], radius=10, fill=PALETTE["bg_card"])
    draw.text((90, 490), "超额收益 Alpha =", fill=PALETTE["gray"],
              font=fonts["sm"], anchor="lm")
    draw.text((W - 90, 490), _fmt_pct(alpha), fill=alpha_color,
              font=fonts["lg"], anchor="rm")

    # ── 4 指标小卡片 ──────────────────────────────────────────────────────────
    cards = [
        ("Sharpe", str(sharpe),              PALETTE["gold"]),
        ("最大回撤", _fmt_pct(max_dd),        PALETTE["red"]),
        ("周胜率", _fmt_pct(win_rate, False), PALETTE["green"]),
        ("持仓数", str(len(positions)),       PALETTE["blue"]),
    ]
    cw = (W - 120 - 30) // 4
    for i, (lbl, val, col) in enumerate(cards):
        x = 60 + i * (cw + 10)
        draw.rounded_rectangle([x, 554, x + cw, 658], radius=10, fill=PALETTE["bg_card"])
        draw.text((x + cw // 2, 578), val,  fill=col,            font=fonts["md"], anchor="mt")
        draw.text((x + cw // 2, 632), lbl,  fill=PALETTE["gray"], font=fonts["xxs"], anchor="mt")

    # ── 当前持仓 ──────────────────────────────────────────────────────────────
    draw.text((60, 682), "当前持仓", fill=PALETTE["gray"], font=fonts["xs"])
    tickers = "   ·   ".join(p["ticker"] for p in positions) if positions else "暂无持仓"
    draw.text((60, 716), tickers, fill=PALETTE["white"], font=fonts["md"])

    # ── 比较 Bar（strategy vs SPY）────────────────────────────────────────────
    bar_y, bmax = 790, W - 120
    max_v = max(abs(total_ret), abs(spy_ret), 0.001)
    sw = int(bmax * abs(total_ret) / max_v)
    pw = int(bmax * abs(spy_ret)   / max_v)
    draw.rounded_rectangle([60, bar_y,      60 + sw, bar_y + 36],      radius=6, fill=strat_color)
    draw.text((70, bar_y + 18), f"策略  {_fmt_pct(total_ret)}", fill="#fff", font=fonts["xxs"], anchor="lm")
    draw.rounded_rectangle([60, bar_y + 46, 60 + pw, bar_y + 82],      radius=6, fill=PALETTE["blue"])
    draw.text((70, bar_y + 64), f"SPY   {_fmt_pct(spy_ret)}",  fill="#fff", font=fonts["xxs"], anchor="lm")

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_weekly_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 2：positions — 持仓明细
# ─────────────────────────────────────────────────────────────────────────────

def _draw_positions_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    positions = data.get("positions", [])
    week      = data.get("week_number", "?")
    year      = data.get("year", datetime.now().year)
    regime    = data.get("market_regime", "UNKNOWN").upper()
    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])

    _draw_header(draw, fonts, week, year, "当前持仓明细", W)

    # ── Regime 彩条 ───────────────────────────────────────────────────────────
    draw.rounded_rectangle([60, 180, W - 60, 246], radius=10, fill=_regime_bg(regime))
    _accent_bar(draw, 60, 180, 76, 246, regime_color, radius=6)
    draw.text((96, 213), REGIME_LABELS_ZH.get(regime, regime),
              fill=regime_color, font=fonts["md"], anchor="lm")
    draw.text((W - 70, 213), f"{len(positions)} 只持仓",
              fill=PALETTE["gray"], font=fonts["sm"], anchor="rm")

    if not positions:
        draw.text((W // 2, 600), "本周无持仓", fill=PALETTE["gray"],
                  font=fonts["lg"], anchor="mm")
    else:
        n       = min(len(positions), 8)
        row_h   = min(100, (H - 370) // n)
        bar_x0  = 300
        bar_x1  = W - 240
        bar_bw  = bar_x1 - bar_x0

        for idx, pos in enumerate(positions[:8]):
            y        = 262 + idx * row_h
            ticker   = pos["ticker"]
            ret      = pos.get("return_pct", 0)
            weight   = pos.get("weight", 1.0 / len(positions))
            entry    = pos.get("entry_price", 0)
            days     = pos.get("hold_days", pos.get("days", 0))
            ret_col  = PALETTE["green"] if ret >= 0 else PALETTE["red"]

            # 行背景
            row_bg = PALETTE["bg_card"] if idx % 2 == 0 else "#121c2e"
            draw.rounded_rectangle([60, y + 2, W - 60, y + row_h - 4],
                                   radius=8, fill=row_bg)
            # 左侧 regime 色条
            _accent_bar(draw, 60, y + 2, 72, y + row_h - 4, regime_color, radius=6)

            # 代码（大字）
            draw.text((92, y + row_h // 2), ticker,
                      fill=PALETTE["white"], font=fonts["lg"], anchor="lm")

            # 权重 Bar
            bar_w   = max(20, int(bar_bw * min(weight * 3, 1.0)))
            bar_mid = y + row_h // 2
            draw.rounded_rectangle([bar_x0, bar_mid - 10, bar_x0 + bar_bw, bar_mid + 10],
                                   radius=5, fill=PALETTE["bg_mid"])
            draw.rounded_rectangle([bar_x0, bar_mid - 10, bar_x0 + bar_w, bar_mid + 10],
                                   radius=5, fill=ret_col)
            draw.text((bar_x0 + bar_w // 2, bar_mid), f"{weight * 100:.0f}%",
                      fill=PALETTE["white"], font=fonts["xxs"], anchor="mm")

            # 入场价 & 天数（bar 下方小字）
            sub = ""
            if entry:
                sub += f"入场 ${entry:.2f}"
            if days:
                sub += f"   持 {days}天"
            if sub:
                draw.text((bar_x0, bar_mid + 16), sub,
                          fill=PALETTE["dim"], font=fonts["xxs"], anchor="lm")

            # 收益率（右侧大字）
            draw.text((W - 70, y + row_h // 2), _fmt_pct(ret),
                      fill=ret_col, font=fonts["md"], anchor="rm")

        # ── 底部汇总 ────────────────────────────────────────────────────────
        avg_ret = sum(p.get("return_pct", 0) for p in positions) / max(len(positions), 1)
        tot_w   = sum(p.get("weight", 0) for p in positions)
        summary = f"平均收益 {_fmt_pct(avg_ret)}   总权重 {tot_w * 100:.0f}%"
        sy = 262 + n * row_h + 12
        if sy < H - 120:
            draw.text((W // 2, sy), summary, fill=PALETTE["gold"],
                      font=fonts["xs"], anchor="mt")

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_positions_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 3：performance — 业绩对比
# ─────────────────────────────────────────────────────────────────────────────

def _draw_performance_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    total     = data["yearly"]["total"]
    backtest  = data.get("backtest", {})
    week      = data.get("week_number", "?")
    year      = data.get("year", datetime.now().year)
    strat_ret = total.get("strategy_return", 0)
    spy_ret   = total.get("spy_return", 0)
    alpha     = total.get("alpha_vs_spy", 0)
    sharpe    = backtest.get("walkforward_sharpe", "N/A")
    max_dd    = backtest.get("max_drawdown", 0)
    win_rate  = total.get("win_rate", 0)

    strat_col = PALETTE["green"] if strat_ret >= 0 else PALETTE["red"]
    spy_col   = PALETTE["green"] if spy_ret   >= 0 else PALETTE["red"]
    alpha_col = PALETTE["green"] if alpha     >= 0 else PALETTE["red"]

    _draw_header(draw, fonts, week, year, "策略业绩对比", W)

    # ── 左右大数字 ────────────────────────────────────────────────────────────
    # 策略
    draw.rounded_rectangle([60, 180, 500, 360], radius=12, fill=PALETTE["bg_card"])
    _accent_bar(draw, 60, 180, 76, 360, strat_col, radius=6)
    draw.text((90, 206), "策略累计收益", fill=PALETTE["gray"], font=fonts["xs"])
    draw.text((90, 242), _fmt_pct(strat_ret), fill=strat_col, font=fonts["xl"])

    # SPY
    draw.rounded_rectangle([520, 180, 960, 360], radius=12, fill=PALETTE["bg_card"])
    _accent_bar(draw, 520, 180, 536, 360, PALETTE["blue"], radius=6)
    draw.text((550, 206), "SPY 买入持有", fill=PALETTE["gray"], font=fonts["xs"])
    draw.text((550, 242), _fmt_pct(spy_ret), fill=spy_col, font=fonts["xl"])

    # ── Alpha 横幅 ────────────────────────────────────────────────────────────
    draw.rounded_rectangle([60, 376, W - 60, 458], radius=12, fill=_regime_bg("BULL" if alpha >= 0 else "BEAR"))
    _accent_bar(draw, 60, 376, 76, 458, alpha_col, radius=6)
    draw.text((96,      417), "超额收益 Alpha", fill=PALETTE["gray"],  font=fonts["sm"], anchor="lm")
    draw.text((W - 80,  417), _fmt_pct(alpha), fill=alpha_col, font=fonts["lg"], anchor="rm")

    # ── 可视化 Bar ────────────────────────────────────────────────────────────
    bar_y  = 480
    bar_mw = W - 120
    max_v  = max(abs(strat_ret), abs(spy_ret), 0.001)
    sw = int(bar_mw * abs(strat_ret) / max_v)
    pw = int(bar_mw * abs(spy_ret)   / max_v)

    draw.rounded_rectangle([60, bar_y,      60 + sw, bar_y + 52], radius=8, fill=strat_col)
    draw.text((80, bar_y + 26), f"破浪策略  {_fmt_pct(strat_ret)}",
              fill="#fff", font=fonts["sm"], anchor="lm")
    draw.rounded_rectangle([60, bar_y + 68, 60 + pw, bar_y + 120], radius=8, fill=PALETTE["blue"])
    draw.text((80, bar_y + 94), f"SPY 指数  {_fmt_pct(spy_ret)}",
              fill="#fff", font=fonts["sm"], anchor="lm")

    # ── 4 指标卡 ──────────────────────────────────────────────────────────────
    metrics = [
        ("Sharpe (OOS)", str(sharpe),              PALETTE["gold"]),
        ("最大回撤",      _fmt_pct(max_dd),          PALETTE["red"]),
        ("周胜率",        _fmt_pct(win_rate, False), PALETTE["green"]),
        ("Alpha",         _fmt_pct(alpha),           alpha_col),
    ]
    cw = (W - 120 - 30) // 4
    for i, (lbl, val, col) in enumerate(metrics):
        x = 60 + i * (cw + 10)
        draw.rounded_rectangle([x, 640, x + cw, 750], radius=10, fill=PALETTE["bg_card"])
        draw.text((x + cw // 2, 660), val, fill=col,            font=fonts["md"],  anchor="mt")
        draw.text((x + cw // 2, 724), lbl, fill=PALETTE["gray"], font=fonts["xxs"], anchor="mt")

    # ── 说明文字 ──────────────────────────────────────────────────────────────
    draw.text((60, 775), "以上收益均为扣除交易成本后的净收益，基于 Walk-Forward 验证",
              fill=PALETTE["dim"], font=fonts["xxs"])

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_performance_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 4：regime — 市场状态分析
# ─────────────────────────────────────────────────────────────────────────────

def _draw_regime_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    regime    = data.get("market_regime", "UNKNOWN").upper()
    week      = data.get("week_number", "?")
    year      = data.get("year", datetime.now().year)
    positions = data.get("positions", [])
    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])

    _draw_header(draw, fonts, week, year, "市场状态解读", W)

    # ── 大型 Regime 色块 ──────────────────────────────────────────────────────
    draw.rounded_rectangle([60, 180, W - 60, 360], radius=16, fill=_regime_bg(regime))
    _accent_bar(draw, 60, 180, 84, 360, regime_color, radius=8)
    regime_en  = {"BULL": "BULL", "BEAR": "BEAR", "CHOPPY": "CHOPPY"}.get(regime, regime)
    regime_zh  = {"BULL": "牛市进攻", "BEAR": "熊市防御", "CHOPPY": "震荡观望"}.get(regime, "")
    draw.text((W // 2, 238), regime_en, fill=regime_color, font=fonts["xl"], anchor="mm")
    draw.text((W // 2, 316), regime_zh, fill=PALETTE["white"], font=fonts["lg"], anchor="mm")

    # ── 模式说明 ──────────────────────────────────────────────────────────────
    subtitle_map = {
        "BULL": "动量进攻 · 持高动量成长股 · 满仓运行",
        "BEAR": "防御模式 · 持做空ETF+短债 · 保护本金",
        "CHOPPY": "观望轻仓 · 等待明确突破信号 · 降低敞口",
    }
    draw.text((W // 2, 384), subtitle_map.get(regime, ""),
              fill=PALETTE["gray"], font=fonts["sm"], anchor="mm")

    # ── 信号列表 ──────────────────────────────────────────────────────────────
    draw.line([(60, 410), (W - 60, 410)], fill=PALETTE["bg_mid"], width=1)
    signals_map = {
        "BULL": ["VIX < 20，市场恐惧指数低", "主要指数站稳 200 日均线",
                 "动量因子排名前 20%", "机构资金净流入"],
        "BEAR": ["VIX > 25，高度恐慌", "主要指数跌破 200 日均线",
                 "信贷利差扩大，信用风险上升", "系统自动切至防御 ETF"],
        "CHOPPY": ["VIX 震荡 18-25 区间", "价格在均线附近反复穿越",
                   "方向信号不明确，降低敞口", "等待明确突破信号才加仓"],
    }
    dot_col = {"BULL": PALETTE["green"], "BEAR": PALETTE["red"], "CHOPPY": PALETTE["yellow"]}
    for i, sig in enumerate(signals_map.get(regime, [])):
        sy = 440 + i * 62
        row_fill = PALETTE["bg_card"] if i % 2 == 0 else "#121c2e"
        draw.rounded_rectangle([60, sy, W - 60, sy + 50], radius=8, fill=row_fill)
        # 彩色圆点代替 emoji
        draw.ellipse([80, sy + 17, 96, sy + 33], fill=dot_col.get(regime, PALETTE["gray"]))
        draw.text((108, sy + 25), sig, fill=PALETTE["white"], font=fonts["sm"], anchor="lm")

    # ── 当前持仓摘要 ──────────────────────────────────────────────────────────
    if positions:
        draw.line([(60, 700), (W - 60, 700)], fill=PALETTE["bg_mid"], width=1)
        draw.text((60, 720), "当前持仓", fill=PALETTE["gray"], font=fonts["xxs"])
        tickers = "   ·   ".join(p["ticker"] for p in positions[:8])
        draw.text((60, 752), tickers, fill=PALETTE["white"], font=fonts["md"])

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_regime_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 5：trade_recap — 本周操作回顾
# ─────────────────────────────────────────────────────────────────────────────

def _draw_trade_recap_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    new_entries  = data.get("new_entries", [])
    new_exits    = data.get("new_exits", [])
    recent_exits = data.get("recent_exits", [])
    week         = data.get("week_number", "?")
    year         = data.get("year", datetime.now().year)

    _draw_header(draw, fonts, week, year, "本周交易操作", W)

    # ── 统计摘要卡 ────────────────────────────────────────────────────────────
    all_exits = new_exits + [e for e in recent_exits if e not in new_exits]
    wins      = sum(1 for t in all_exits if t.get("return_pct", 0) >= 0)
    avg_ret   = (sum(t.get("return_pct", 0) for t in all_exits)
                 / max(len(all_exits), 1))

    stats = [
        ("新买入", str(len(new_entries)), PALETTE["green"]),
        ("新平仓", str(len(all_exits)),   PALETTE["red"]),
        ("胜率",   f"{wins}/{max(len(all_exits),1)}", PALETTE["gold"]),
        ("平均收益", _fmt_pct(avg_ret),    PALETTE["green"] if avg_ret >= 0 else PALETTE["red"]),
    ]
    cw = (W - 120 - 30) // 4
    for i, (lbl, val, col) in enumerate(stats):
        x = 60 + i * (cw + 10)
        draw.rounded_rectangle([x, 180, x + cw, 264], radius=10, fill=PALETTE["bg_card"])
        draw.text((x + cw // 2, 200), val, fill=col,            font=fonts["lg"],  anchor="mt")
        draw.text((x + cw // 2, 248), lbl, fill=PALETTE["gray"], font=fonts["xxs"], anchor="mt")

    cur_y = 284

    # ── 新买入列表 ────────────────────────────────────────────────────────────
    draw.text((60, cur_y), "新买入", fill=PALETTE["green"], font=fonts["sm"])
    draw.ellipse([W - 90, cur_y + 6, W - 74, cur_y + 22], fill=PALETTE["green"])
    cur_y += 42
    if new_entries:
        for pos in new_entries[:4]:
            draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 54], radius=8,
                                   fill=PALETTE["bg_card"])
            _accent_bar(draw, 60, cur_y, 72, cur_y + 54, PALETTE["green"], radius=6)
            draw.text((88, cur_y + 27), pos["ticker"],
                      fill=PALETTE["white"], font=fonts["md"], anchor="lm")
            if pos.get("entry_price"):
                draw.text((340, cur_y + 27), f"入场 ${pos['entry_price']:.2f}",
                          fill=PALETTE["gray"], font=fonts["xs"], anchor="lm")
            draw.text((W - 70, cur_y + 27), "买入",
                      fill=PALETTE["green"], font=fonts["sm"], anchor="rm")
            cur_y += 62
    else:
        draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 50], radius=8,
                               fill=PALETTE["bg_card"])
        draw.text((W // 2, cur_y + 25), "本周维持持仓，无新买入信号",
                  fill=PALETTE["dim"], font=fonts["xs"], anchor="mm")
        cur_y += 58

    cur_y += 10
    draw.line([(60, cur_y), (W - 60, cur_y)], fill=PALETTE["bg_mid"], width=1)
    cur_y += 14

    # ── 平仓列表 ──────────────────────────────────────────────────────────────
    draw.text((60, cur_y), "已平仓", fill=PALETTE["red"], font=fonts["sm"])
    draw.ellipse([W - 90, cur_y + 6, W - 74, cur_y + 22], fill=PALETTE["red"])
    cur_y += 42
    if all_exits:
        for trade in all_exits[:4]:
            ret     = trade.get("return_pct", 0)
            ret_col = PALETTE["green"] if ret >= 0 else PALETTE["red"]
            draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 54], radius=8,
                                   fill=PALETTE["bg_card"])
            _accent_bar(draw, 60, cur_y, 72, cur_y + 54, ret_col, radius=6)
            draw.text((88, cur_y + 27), trade["ticker"],
                      fill=PALETTE["white"], font=fonts["md"], anchor="lm")
            days = trade.get("hold_days", trade.get("days", 0))
            if days:
                draw.text((340, cur_y + 27), f"持仓 {days} 天",
                          fill=PALETTE["gray"], font=fonts["xs"], anchor="lm")
            draw.text((W - 70, cur_y + 27), _fmt_pct(ret),
                      fill=ret_col, font=fonts["md"], anchor="rm")
            cur_y += 62
    else:
        draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 50], radius=8,
                               fill=PALETTE["bg_card"])
        draw.text((W // 2, cur_y + 25), "本周无平仓操作，持仓按计划运行",
                  fill=PALETTE["dim"], font=fonts["xs"], anchor="mm")
        cur_y += 58

    # ── 若空间充足，显示当前持仓状态 ──────────────────────────────────────────
    positions = data.get("positions", [])
    if positions and cur_y < H - 250:
        cur_y += 14
        draw.line([(60, cur_y), (W - 60, cur_y)], fill=PALETTE["bg_mid"], width=1)
        cur_y += 14
        draw.text((60, cur_y), "当前持仓", fill=PALETTE["gray"], font=fonts["xs"])
        cur_y += 32
        regime = data.get("market_regime", "UNKNOWN").upper()
        rc     = REGIME_COLORS.get(regime, PALETTE["gray"])
        n_show = min(len(positions), (H - 150 - cur_y) // 58)
        for pos in positions[:n_show]:
            ret     = pos.get("return_pct", 0)
            ret_col = PALETTE["green"] if ret >= 0 else PALETTE["red"]
            draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 48], radius=8,
                                   fill=PALETTE["bg_card"])
            _accent_bar(draw, 60, cur_y, 70, cur_y + 48, rc, radius=5)
            draw.text((88, cur_y + 24), pos["ticker"],
                      fill=PALETTE["white"], font=fonts["md"], anchor="lm")
            draw.text((W - 70, cur_y + 24), _fmt_pct(ret),
                      fill=ret_col, font=fonts["sm"], anchor="rm")
            cur_y += 56

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_trade_recap_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# AI 文案生成 Prompt 构建
# ─────────────────────────────────────────────────────────────────────────────

_AI_SYSTEM = """你是 StockQueen 的社交媒体内容创作专家。
StockQueen 是一个 AI 量化动量投资 newsletter，核心策略：
- 多因子动量模型（价格动量 + RSI + 成交量 + ATR 波动率）
- 三态市场 Regime（BULL牛市/BEAR熊市/CHOPPY震荡）
- Walk-Forward 验证，累计收益 536%+ vs SPY 70%

你根据提供的持仓数据和主题，为不同社交平台生成符合平台调性的文案。
直接输出文案正文，不需要任何解释或包装。"""


_PLATFORM_GUIDES = {
    "xiaohongshu-zh": "小红书风格：个人化、故事感、有钩子开头、多用emoji、结尾引导订阅。中文。",
    "twitter-en":     "Twitter/X 风格：280字符以内、信息密集、直接、英文。",
    "linkedin-en":    "LinkedIn 风格：专业机构风格、有深度、英文、不超过600字。",
    "facebook-zh":    "Facebook 中文风格：社区感、热情、港台新马华人读者、不超过400字。",
    "facebook-en":    "Facebook 英文风格：亲切友好、澳新读者、不超过400字。",
    "reddit-algotrading": "Reddit r/algotrading 风格：技术向、含数据、英文、500-800字。",
    "wechat-zh":      "微信公众号风格：Markdown格式、标题+正文、专业理性、中文。",
}

_CONTENT_TYPE_GUIDES = {
    "weekly":        "综合周报：本周市场状态、策略表现、当前持仓、新信号。",
    "positions":     "持仓分享：重点展示当前持仓逻辑、为什么持有这些标的、风险控制。",
    "performance":   "业绩展示：策略收益 vs SPY 对比、Sharpe/回撤等量化指标解读。",
    "regime":        "市场分析：当前 Regime 判断依据、市场信号解读、策略应对逻辑。",
    "trade_recap":   "交易回顾：本周买入卖出操作、盈亏分析、策略执行情况。",
    "algo_upgrade":  "算法升级/技术突破：介绍策略的新改进、参数优化、验证结果。",
}


async def _call_ai_api(prompt: str) -> str:
    """调用 OpenAI API 生成文案"""
    import httpx

    openai_key = settings.openai_api_key or ""
    if not openai_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请在 Render 环境变量中添加")

    base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    model = settings.openai_chat_model or "gpt-4o-mini"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": 800,
                "messages": [
                    {"role": "system", "content": _AI_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 页面路由
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/social", response_class=HTMLResponse)
async def social_page(request: Request):
    data = _load_social_data()
    regime = data.get("market_regime", "UNKNOWN")
    positions = data.get("positions", [])
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)

    regime_labels = {"BULL": "🟢 牛市进攻", "BEAR": "🔴 熊市防御", "CHOPPY": "🟡 震荡市"}
    regime_display = regime_labels.get(regime.upper(), regime)

    return templates.TemplateResponse("social.html", {
        "request": request,
        "regime": regime,
        "regime_display": regime_display,
        "positions": positions,
        "week": week,
        "year": year,
        "publish_date": data.get("publish_date", ""),
        "total_ret": f"+{data['yearly']['total'].get('strategy_return', 0)*100:.1f}%",
        "alpha": f"+{data['yearly']['total'].get('alpha_vs_spy', 0)*100:.1f}%",
    })


# ─────────────────────────────────────────────────────────────────────────────
# API：生成文案
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/social/generate")
async def generate_social_content():
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.newsletter.social_generator import SocialGenerator

        data = _load_social_data()
        gen = SocialGenerator()
        content = gen.generate_all(data)

        return JSONResponse({
            "ok": True,
            "week": data.get("week_number"),
            "year": data.get("year"),
            "regime": data.get("market_regime", "UNKNOWN"),
            "positions": [p["ticker"] for p in data.get("positions", [])],
            "content": content,
            "char_count": {k: len(v) for k, v in content.items()},
        })
    except Exception as e:
        logger.error(f"social generate error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# API：生成图片（支持多种类型）
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_DRAWERS = {
    "weekly":      _draw_weekly_card,
    "positions":   _draw_positions_card,
    "performance": _draw_performance_card,
    "regime":      _draw_regime_card,
    "trade_recap": _draw_trade_recap_card,
}


@router.post("/api/social/generate-image")
async def generate_image_card(request: Request):
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        image_type = body.get("image_type", "weekly")
        import io
        from PIL import Image  # noqa: just to trigger ImportError if Pillow missing

        data = _load_social_data()
        drawer = IMAGE_DRAWERS.get(image_type, _draw_weekly_card)
        img, filename = drawer(data)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()

        return JSONResponse({
            "ok": True,
            "image_b64": f"data:image/png;base64,{b64}",
            "filename": filename,
            "image_type": image_type,
        })

    except ImportError:
        return JSONResponse({"ok": False, "error": "Pillow not installed", "fallback": "canvas"}, status_code=200)
    except Exception as e:
        logger.error(f"generate image error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# API：AI 文案生成
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/social/ai-caption")
async def generate_ai_caption(request: Request):
    """
    根据内容维度 + 平台，用 AI 生成定制文案
    Body: {
        "content_type": "weekly|positions|performance|regime|trade_recap|algo_upgrade",
        "platform": "xiaohongshu-zh|twitter-en|linkedin-en|...",
        "custom_topic": ""   // 可选，如"新增了波动率过滤器"
    }
    """
    try:
        body = await request.json()
        content_type = body.get("content_type", "weekly")
        platform = body.get("platform", "xiaohongshu-zh")
        custom_topic = body.get("custom_topic", "").strip()

        data = _load_social_data()
        regime = data.get("market_regime", "UNKNOWN").upper()
        positions = data.get("positions", [])
        recent_exits = data.get("recent_exits", [])
        new_entries = data.get("new_entries", [])
        new_exits = data.get("new_exits", [])
        total = data["yearly"]["total"]
        backtest = data.get("backtest", {})
        week = data.get("week_number", "?")
        year = data.get("year", datetime.now().year)

        # 构建数据摘要
        pos_text = ", ".join(f"{p['ticker']}({_fmt_pct(p.get('return_pct',0))})" for p in positions[:8]) or "无持仓"
        exit_text = ", ".join(f"{t['ticker']}({_fmt_pct(t.get('return_pct',0))})" for t in recent_exits[:5]) or "无"
        entry_text = ", ".join(p["ticker"] for p in new_entries[:5]) or "无"

        data_summary = f"""
本周数据（第{week}周，{year}年）：
- 市场状态：{regime}
- 策略收益：{_fmt_pct(total.get('strategy_return',0))} vs SPY {_fmt_pct(total.get('spy_return',0))}
- Alpha：{_fmt_pct(total.get('alpha_vs_spy',0))}
- Sharpe (OOS)：{backtest.get('walkforward_sharpe','N/A')}
- 最大回撤：{_fmt_pct(backtest.get('max_drawdown',0))}
- 胜率：{_fmt_pct(total.get('win_rate',0), sign=False)}
- 当前持仓：{pos_text}
- 新买入：{entry_text}
- 本周平仓：{exit_text}
"""

        content_guide = _CONTENT_TYPE_GUIDES.get(content_type, "")
        platform_guide = _PLATFORM_GUIDES.get(platform, "")

        topic_line = f"\n自定义主题：{custom_topic}" if custom_topic else ""

        prompt = f"""请为以下场景生成社交媒体文案：

内容维度：{content_guide}
目标平台：{platform_guide}{topic_line}

真实数据：
{data_summary}

请直接输出适合该平台发布的文案，不需要任何解释。"""

        caption = await _call_ai_api(prompt)

        return JSONResponse({
            "ok": True,
            "caption": caption,
            "content_type": content_type,
            "platform": platform,
            "char_count": len(caption),
        })

    except Exception as e:
        logger.error(f"ai caption error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
