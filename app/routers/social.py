"""
StockQueen - 社交媒体发布中心 Router
POST /api/social/generate   → 生成所有平台内容
POST /api/social/generate-image → 生成分享图片卡片
GET  /social                → 管理页面
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

    # 性能数据默认值（应从模板维护）
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


# ──────────────────────────────────────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/social", response_class=HTMLResponse)
async def social_page(request: Request):
    """社交媒体发布中心主页面"""
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


# ──────────────────────────────────────────────────────────────────────────────
# API：生成内容
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/api/social/generate")
async def generate_social_content():
    """读取快照数据，生成所有平台社交内容"""
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.newsletter.social_generator import SocialGenerator

        data = _load_social_data()
        gen = SocialGenerator()
        content = gen.generate_all(data)

        # 附加元数据
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


# ──────────────────────────────────────────────────────────────────────────────
# API：生成分享图片卡片
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/api/social/generate-image")
async def generate_image_card():
    """生成社交媒体分享图片卡片（PNG，返回 base64）"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        data = _load_social_data()
        regime = data.get("market_regime", "UNKNOWN")
        positions = data.get("positions", [])
        week = data.get("week_number", "?")
        year = data.get("year", datetime.now().year)
        total_ret = data["yearly"]["total"].get("strategy_return", 0)
        alpha = data["yearly"]["total"].get("alpha_vs_spy", 0)

        # ── 画布 1080×1080 (适合 Instagram/小红书) ──
        W, H = 1080, 1080
        img = Image.new("RGB", (W, H), color="#0f172a")
        draw = ImageDraw.Draw(img)

        # 背景渐变（手动分段）
        for y in range(H):
            r = int(15 + (30 - 15) * y / H)
            g = int(23 + (41 - 23) * y / H)
            b = int(42 + (59 - 42) * y / H)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # 加载字体（降级到默认字体如果找不到）
        try:
            font_dir = ROOT / "app" / "static" / "fonts"
            font_bold = ImageFont.truetype(str(font_dir / "NotoSansSC-Bold.ttf"), 56)
            font_med  = ImageFont.truetype(str(font_dir / "NotoSansSC-Medium.ttf"), 36)
            font_sm   = ImageFont.truetype(str(font_dir / "NotoSansSC-Regular.ttf"), 28)
            font_xs   = ImageFont.truetype(str(font_dir / "NotoSansSC-Regular.ttf"), 22)
        except Exception:
            font_bold = font_med = font_sm = font_xs = ImageFont.load_default()

        # 颜色
        GOLD   = "#eab308"
        WHITE  = "#f8fafc"
        GRAY   = "#94a3b8"
        GREEN  = "#22c55e"
        RED    = "#ef4444"
        YELLOW = "#fbbf24"

        regime_colors = {"BULL": GREEN, "BEAR": RED, "CHOPPY": YELLOW}
        regime_color = regime_colors.get(regime.upper(), GRAY)
        regime_labels = {"BULL": "🟢 牛市进攻模式", "BEAR": "🔴 熊市防御模式", "CHOPPY": "🟡 震荡观望模式"}
        regime_label = regime_labels.get(regime.upper(), regime)

        # Logo 区域
        draw.text((60, 60), "StockQueen", fill=GOLD, font=font_bold)
        draw.text((60, 128), f"第 {week} 周量化策略报告  ·  {year}", fill=GRAY, font=font_sm)

        # 分隔线
        draw.line([(60, 176), (W - 60, 176)], fill="#334155", width=2)

        # 市场状态大标题
        draw.text((60, 210), regime_label, fill=regime_color, font=font_bold)

        # 收益指标卡片
        cards = [
            ("策略总收益", f"+{total_ret*100:.1f}%", GREEN),
            ("超额 vs SPY",  f"+{alpha*100:.1f}%",    GREEN),
            ("Sharpe (OOS)", str(data["backtest"].get("walkforward_sharpe", "1.42")), GOLD),
            ("最大回撤",    f"{data['backtest'].get('max_drawdown', -0.15)*100:.1f}%", RED),
        ]
        card_w = (W - 120 - 30) // 4
        for i, (label, value, color) in enumerate(cards):
            x = 60 + i * (card_w + 10)
            y = 320
            # 卡片背景
            draw.rounded_rectangle([x, y, x + card_w, y + 130], radius=12, fill="#1e293b")
            # 数值
            draw.text((x + card_w // 2, y + 28), value, fill=color, font=font_bold, anchor="mt")
            # 标签
            draw.text((x + card_w // 2, y + 94), label, fill=GRAY, font=font_xs, anchor="mt")

        # 当前持仓
        draw.text((60, 490), "当前持仓", fill=GRAY, font=font_sm)
        tickers = [p["ticker"] for p in positions]
        ticker_str = "  ·  ".join(tickers) if tickers else "无持仓"
        draw.text((60, 538), ticker_str, fill=WHITE, font=font_med)

        # 分隔线
        draw.line([(60, 618), (W - 60, 618)], fill="#334155", width=1)

        # 二维码占位 / 订阅引导
        draw.text((60, 650), "每周免费获取量化信号 →", fill=GRAY, font=font_sm)
        draw.text((60, 700), "stockqueen.tech", fill=GOLD, font=font_bold)

        # 免责声明
        draw.text((60, H - 80), "仅供参考，不构成投资建议  ·  Walk-Forward 验证，非过拟合", fill="#475569", font=font_xs)

        # 输出为 base64
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()

        return JSONResponse({
            "ok": True,
            "image_b64": f"data:image/png;base64,{b64}",
            "filename": f"stockqueen_wk{week}_{year}.png",
        })

    except ImportError:
        # Pillow 未安装：返回 SVG 占位图（用 Canvas 在前端生成）
        return JSONResponse({
            "ok": False,
            "error": "Pillow not installed",
            "fallback": "canvas",
        }, status_code=200)
    except Exception as e:
        logger.error(f"generate image error: {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
