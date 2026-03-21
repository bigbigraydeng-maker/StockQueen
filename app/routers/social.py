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
        data["week_number"] = tmpl.get("week_number", datetime.now().isocalendar()[1])
        data["year"] = tmpl.get("year", datetime.now().year)
        data["publish_date"] = tmpl.get("publish_date", datetime.now().strftime("%Y-%m-%d"))
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
    """加载字体，失败则降级为默认字体"""
    try:
        from PIL import ImageFont
        font_dir = ROOT / "app" / "static" / "fonts"
        return {
            "xl":  ImageFont.truetype(str(font_dir / "NotoSansSC-Bold.ttf"), 72),
            "lg":  ImageFont.truetype(str(font_dir / "NotoSansSC-Bold.ttf"), 56),
            "md":  ImageFont.truetype(str(font_dir / "NotoSansSC-Medium.ttf"), 36),
            "sm":  ImageFont.truetype(str(font_dir / "NotoSansSC-Regular.ttf"), 28),
            "xs":  ImageFont.truetype(str(font_dir / "NotoSansSC-Regular.ttf"), 22),
            "xxs": ImageFont.truetype(str(font_dir / "NotoSansSC-Regular.ttf"), 18),
        }
    except Exception:
        from PIL import ImageFont
        d = ImageFont.load_default()
        return {"xl": d, "lg": d, "md": d, "sm": d, "xs": d, "xxs": d}


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
    """创建带渐变背景的画布"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), color=PALETTE["bg_dark"])
    draw = ImageDraw.Draw(img)
    for y in range(H):
        r = int(15 + (30 - 15) * y / H)
        g = int(23 + (41 - 23) * y / H)
        b = int(42 + (59 - 42) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img, draw


def _draw_header(draw, fonts, week, year, subtitle="量化策略周报", W=1080):
    """绘制通用 Header（Logo + 副标题）"""
    draw.text((60, 55), "StockQueen", fill=PALETTE["gold"], font=fonts["lg"])
    draw.text((60, 125), f"第 {week} 周 {subtitle}  ·  {year}", fill=PALETTE["gray"], font=fonts["sm"])
    draw.line([(60, 172), (W - 60, 172)], fill=PALETTE["bg_mid"], width=2)


def _draw_footer(draw, fonts, H=1080, W=1080):
    """绘制通用 Footer"""
    draw.line([(60, H - 110), (W - 60, H - 110)], fill=PALETTE["bg_mid"], width=1)
    draw.text((60, H - 90), "每周免费获取量化信号 → stockqueen.tech",
              fill=PALETTE["gold"], font=fonts["xs"])
    draw.text((60, H - 58), "仅供参考，不构成投资建议  ·  Walk-Forward 验证，非过拟合",
              fill=PALETTE["dim"], font=fonts["xxs"])


def _fmt_pct(v, sign=True) -> str:
    if v is None:
        return "N/A"
    pct = v * 100
    if sign:
        return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    return f"{pct:.1f}%"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 1：weekly — 综合周报（现有功能升级）
# ─────────────────────────────────────────────────────────────────────────────

def _draw_weekly_card(data: dict):
    from PIL import ImageDraw
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    regime = data.get("market_regime", "UNKNOWN").upper()
    positions = data.get("positions", [])
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)
    total_ret = data["yearly"]["total"].get("strategy_return", 0)
    alpha = data["yearly"]["total"].get("alpha_vs_spy", 0)
    backtest = data.get("backtest", {})

    _draw_header(draw, fonts, week, year, "量化策略周报", W)

    # 市场状态
    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])
    draw.text((60, 200), REGIME_LABELS_ZH.get(regime, regime), fill=regime_color, font=fonts["lg"])

    # 4 指标卡片
    cards = [
        ("策略总收益", _fmt_pct(total_ret), PALETTE["green"] if total_ret >= 0 else PALETTE["red"]),
        ("Alpha vs SPY", _fmt_pct(alpha), PALETTE["green"] if alpha >= 0 else PALETTE["red"]),
        ("Sharpe (OOS)", str(backtest.get("walkforward_sharpe", "N/A")), PALETTE["gold"]),
        ("最大回撤", _fmt_pct(backtest.get("max_drawdown", 0)), PALETTE["red"]),
    ]
    card_w = (W - 120 - 30) // 4
    for i, (label, value, color) in enumerate(cards):
        x = 60 + i * (card_w + 10)
        y = 310
        draw.rounded_rectangle([x, y, x + card_w, y + 130], radius=12, fill=PALETTE["bg_card"])
        draw.text((x + card_w // 2, y + 24), value, fill=color, font=fonts["lg"], anchor="mt")
        draw.text((x + card_w // 2, y + 94), label, fill=PALETTE["gray"], font=fonts["xs"], anchor="mt")

    # 当前持仓
    draw.text((60, 490), "当前持仓", fill=PALETTE["gray"], font=fonts["sm"])
    tickers = "  ·  ".join(p["ticker"] for p in positions) if positions else "无持仓"
    draw.text((60, 535), tickers, fill=PALETTE["white"], font=fonts["md"])

    # Win rate + 本周信号
    win_rate = data["yearly"]["total"].get("win_rate", 0)
    new_signals = len(data.get("new_entries", [])) + len(data.get("new_exits", []))
    draw.text((60, 625), f"胜率 {_fmt_pct(win_rate, sign=False)}   本周信号 {new_signals} 个",
              fill=PALETTE["gray"], font=fonts["sm"])

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
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)
    regime = data.get("market_regime", "UNKNOWN").upper()

    _draw_header(draw, fonts, week, year, "当前持仓明细", W)

    # Regime badge
    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])
    draw.text((60, 200), REGIME_LABELS_ZH.get(regime, regime), fill=regime_color, font=fonts["md"])

    if not positions:
        draw.text((60, 320), "本周无持仓", fill=PALETTE["gray"], font=fonts["lg"])
    else:
        # 每行显示一个持仓
        row_h = min(72, (H - 350) // max(len(positions), 1))
        for idx, pos in enumerate(positions[:10]):
            y = 270 + idx * row_h
            ticker = pos["ticker"]
            ret = pos.get("return_pct", 0)
            hold_days = pos.get("hold_days", pos.get("days", 0))
            entry = pos.get("entry_price", 0)
            ret_color = PALETTE["green"] if ret >= 0 else PALETTE["red"]

            # 背景行（交替）
            bg = PALETTE["bg_card"] if idx % 2 == 0 else "#162032"
            draw.rounded_rectangle([60, y, W - 60, y + row_h - 4], radius=8, fill=bg)

            # ticker
            draw.text((80, y + row_h // 2), ticker, fill=PALETTE["white"],
                      font=fonts["md"], anchor="lm")
            # 入场价
            if entry:
                draw.text((320, y + row_h // 2), f"入场 ${entry:.2f}",
                          fill=PALETTE["gray"], font=fonts["xs"], anchor="lm")
            # 收益
            draw.text((W - 200, y + row_h // 2), _fmt_pct(ret),
                      fill=ret_color, font=fonts["md"], anchor="rm")
            # 持仓天数
            if hold_days:
                draw.text((W - 80, y + row_h // 2), f"{hold_days}天",
                          fill=PALETTE["dim"], font=fonts["xs"], anchor="rm")

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_positions_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 3：performance — 业绩对比
# ─────────────────────────────────────────────────────────────────────────────

def _draw_performance_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    total = data["yearly"]["total"]
    backtest = data.get("backtest", {})
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)

    strat_ret = total.get("strategy_return", 0)
    spy_ret = total.get("spy_return", 0)
    alpha = total.get("alpha_vs_spy", 0)
    sharpe = backtest.get("walkforward_sharpe", "N/A")
    max_dd = backtest.get("max_drawdown", 0)
    win_rate = total.get("win_rate", 0)

    _draw_header(draw, fonts, week, year, "策略业绩对比", W)

    # 大字展示：策略 vs SPY
    draw.text((60, 205), "策略收益", fill=PALETTE["gray"], font=fonts["sm"])
    strat_color = PALETTE["green"] if strat_ret >= 0 else PALETTE["red"]
    draw.text((60, 245), _fmt_pct(strat_ret), fill=strat_color, font=fonts["xl"])

    draw.text((580, 205), "SPY 买入持有", fill=PALETTE["gray"], font=fonts["sm"])
    spy_color = PALETTE["green"] if spy_ret >= 0 else PALETTE["red"]
    draw.text((580, 245), _fmt_pct(spy_ret), fill=spy_color, font=fonts["xl"])

    # Alpha 大字
    draw.line([(60, 360), (W - 60, 360)], fill=PALETTE["bg_mid"], width=1)
    draw.text((60, 385), "超额收益（Alpha）", fill=PALETTE["gray"], font=fonts["sm"])
    alpha_color = PALETTE["green"] if alpha >= 0 else PALETTE["red"]
    draw.text((60, 425), _fmt_pct(alpha), fill=alpha_color, font=fonts["xl"])

    # 视觉对比 Bar
    bar_y = 555
    bar_max_w = W - 180
    max_val = max(abs(strat_ret), abs(spy_ret), 0.01)
    # Strategy bar
    strat_bar_w = int(bar_max_w * abs(strat_ret) / max_val)
    draw.rounded_rectangle([60, bar_y, 60 + strat_bar_w, bar_y + 44], radius=8,
                           fill=PALETTE["green"] if strat_ret >= 0 else PALETTE["red"])
    draw.text((70, bar_y + 22), f"策略 {_fmt_pct(strat_ret)}", fill=PALETTE["white"],
              font=fonts["sm"], anchor="lm")
    # SPY bar
    spy_bar_w = int(bar_max_w * abs(spy_ret) / max_val)
    draw.rounded_rectangle([60, bar_y + 60, 60 + spy_bar_w, bar_y + 104], radius=8,
                           fill=PALETTE["blue"])
    draw.text((70, bar_y + 82), f"SPY   {_fmt_pct(spy_ret)}", fill=PALETTE["white"],
              font=fonts["sm"], anchor="lm")

    # 底部 4 指标
    metrics = [
        ("Sharpe (OOS)", str(sharpe), PALETTE["gold"]),
        ("最大回撤", _fmt_pct(max_dd), PALETTE["red"]),
        ("周胜率", _fmt_pct(win_rate, sign=False), PALETTE["green"]),
        ("Alpha", _fmt_pct(alpha), PALETTE["green"] if alpha >= 0 else PALETTE["red"]),
    ]
    card_w = (W - 120 - 30) // 4
    for i, (label, val, color) in enumerate(metrics):
        x = 60 + i * (card_w + 10)
        y = 720
        draw.rounded_rectangle([x, y, x + card_w, y + 120], radius=10, fill=PALETTE["bg_card"])
        draw.text((x + card_w // 2, y + 20), val, fill=color, font=fonts["lg"], anchor="mt")
        draw.text((x + card_w // 2, y + 84), label, fill=PALETTE["gray"], font=fonts["xs"], anchor="mt")

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_performance_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 4：regime — 市场状态分析
# ─────────────────────────────────────────────────────────────────────────────

def _draw_regime_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    regime = data.get("market_regime", "UNKNOWN").upper()
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)
    positions = data.get("positions", [])

    _draw_header(draw, fonts, week, year, "市场状态解读", W)

    # 超大 Regime 文字
    regime_color = REGIME_COLORS.get(regime, PALETTE["gray"])
    regime_label = {"BULL": "BULL 牛市", "BEAR": "BEAR 熊市", "CHOPPY": "CHOPPY 震荡"}.get(regime, regime)
    draw.text((W // 2, 290), regime_label, fill=regime_color, font=fonts["xl"], anchor="mm")

    # 状态副标题
    subtitle = {
        "BULL": "动量进攻模式  ·  持高动量成长股",
        "BEAR": "防御模式  ·  持做空 ETF + 国债",
        "CHOPPY": "观望模式  ·  轻仓等待信号",
    }.get(regime, "")
    draw.text((W // 2, 365), subtitle, fill=PALETTE["gray"], font=fonts["sm"], anchor="mm")

    # 触发信号说明
    signal_y = 430
    draw.line([(60, signal_y), (W - 60, signal_y)], fill=PALETTE["bg_mid"], width=1)

    signals_map = {
        "BULL": [
            "✅  VIX 低于 20（市场恐惧指数低）",
            "✅  主要指数站稳 200 日均线",
            "✅  动量因子得分排名前 20%",
            "✅  成交量放大，机构资金流入",
        ],
        "BEAR": [
            "🔴  VIX 突破 25（市场高度恐惧）",
            "🔴  主要指数跌破 200 日均线",
            "🔴  信贷利差扩大，信用风险上升",
            "🔴  系统自动切换至防御 ETF",
        ],
        "CHOPPY": [
            "🟡  VIX 在 18-25 区间震荡",
            "🟡  价格在均线附近反复穿越",
            "🟡  方向信号不明确，降低风险敞口",
            "🟡  等待明确突破信号再加仓",
        ],
    }
    signals = signals_map.get(regime, [])
    for i, sig in enumerate(signals):
        draw.text((80, signal_y + 30 + i * 58), sig, fill=PALETTE["white"], font=fonts["sm"])

    # 当前持仓摘要
    if positions:
        draw.line([(60, 720), (W - 60, 720)], fill=PALETTE["bg_mid"], width=1)
        draw.text((60, 740), "当前持仓", fill=PALETTE["gray"], font=fonts["xs"])
        tickers = "  ·  ".join(p["ticker"] for p in positions[:8])
        draw.text((60, 775), tickers, fill=PALETTE["white"], font=fonts["md"])

    _draw_footer(draw, fonts, H, W)
    return img, f"stockqueen_regime_wk{week}_{year}.png"


# ─────────────────────────────────────────────────────────────────────────────
# 图片类型 5：trade_recap — 本周操作回顾
# ─────────────────────────────────────────────────────────────────────────────

def _draw_trade_recap_card(data: dict):
    W, H = 1080, 1080
    img, draw = _make_canvas(W, H)
    fonts = _load_fonts(ROOT)

    new_entries = data.get("new_entries", [])
    new_exits = data.get("new_exits", [])
    recent_exits = data.get("recent_exits", [])
    week = data.get("week_number", "?")
    year = data.get("year", datetime.now().year)

    _draw_header(draw, fonts, week, year, "本周交易操作", W)

    cur_y = 200

    # 新买入
    draw.text((60, cur_y), f"📥 新买入  ({len(new_entries)} 笔)", fill=PALETTE["green"], font=fonts["md"])
    cur_y += 50
    if new_entries:
        for pos in new_entries[:6]:
            draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 52], radius=8, fill=PALETTE["bg_card"])
            draw.text((80, cur_y + 26), pos["ticker"], fill=PALETTE["white"], font=fonts["md"], anchor="lm")
            if pos.get("entry_price"):
                draw.text((300, cur_y + 26), f"${pos['entry_price']:.2f}",
                          fill=PALETTE["gray"], font=fonts["xs"], anchor="lm")
            draw.text((W - 80, cur_y + 26), "买入", fill=PALETTE["green"], font=fonts["xs"], anchor="rm")
            cur_y += 60
    else:
        draw.text((80, cur_y), "本周无新买入", fill=PALETTE["dim"], font=fonts["xs"])
        cur_y += 48

    cur_y += 20
    draw.line([(60, cur_y), (W - 60, cur_y)], fill=PALETTE["bg_mid"], width=1)
    cur_y += 20

    # 新卖出 + 近期平仓
    all_exits = new_exits + [e for e in recent_exits if e not in new_exits]
    draw.text((60, cur_y), f"📤 已平仓  ({len(all_exits)} 笔)", fill=PALETTE["red"], font=fonts["md"])
    cur_y += 50

    total_pnl = 0
    wins = 0
    if all_exits:
        for trade in all_exits[:6]:
            draw.rounded_rectangle([60, cur_y, W - 60, cur_y + 52], radius=8, fill=PALETTE["bg_card"])
            ret = trade.get("return_pct", 0)
            ret_color = PALETTE["green"] if ret >= 0 else PALETTE["red"]
            total_pnl += ret
            if ret >= 0:
                wins += 1
            draw.text((80, cur_y + 26), trade["ticker"], fill=PALETTE["white"], font=fonts["md"], anchor="lm")
            days = trade.get("hold_days", trade.get("days", 0))
            if days:
                draw.text((300, cur_y + 26), f"持仓 {days} 天",
                          fill=PALETTE["gray"], font=fonts["xs"], anchor="lm")
            draw.text((W - 80, cur_y + 26), _fmt_pct(ret),
                      fill=ret_color, font=fonts["md"], anchor="rm")
            cur_y += 60
    else:
        draw.text((80, cur_y), "本周无平仓操作", fill=PALETTE["dim"], font=fonts["xs"])
        cur_y += 48

    # 汇总
    if all_exits:
        avg_ret = total_pnl / len(all_exits)
        win_text = f"本批胜率 {wins}/{len(all_exits)}  ·  平均收益 {_fmt_pct(avg_ret)}"
        draw.text((60, max(cur_y + 10, H - 155)), win_text,
                  fill=PALETTE["gold"], font=fonts["xs"])

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
