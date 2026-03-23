"""
StockQueen C5 — Retail Sentiment Regime Gate

每日盘后（10:10 NZT）检测散户炒作 Regime，输出 meme_mode 供 ED 策略入场门控。

数据源：
  1. CBOE Equity Put/Call 比率（最关键，免费）
  2. Reddit r/wallstreetbets 热帖提及量（免费，User-Agent 即可）

判断逻辑（加权投票）：
  P/C < 0.45  → +2（散户疯狂买 Call = 贪婪）
  P/C 0.45-0.65 → 0（正常）
  P/C > 0.80  → -1（恐慌）
  WSB 异常 ticker >= 3 只 → +2
  WSB 异常 ticker 1-2 只 → +1
  总分 >= 3 → extreme meme_mode=True
  总分 == 2 → elevated meme_mode=True
  总分 <= 1 → normal/fear meme_mode=False
"""

import asyncio
import logging
import re
import statistics
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from app.database import get_db

logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

CBOE_CSV_URL = (
    "https://cdn.cboe.com/api/global/us_options_market_statistics/"
    "daily-options-data/{date}-options-ratios.csv"
)

WSB_HOT_URL = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=100"
WSB_USER_AGENT = "StockQueen Research/1.0 (research@stockqueen.app)"

PC_GREED_THRESHOLD = 0.45
PC_NORMAL_UPPER    = 0.65
PC_FEAR_THRESHOLD  = 0.80

WSB_ZSCORE_MEME_THRESHOLD = 2.0
WSB_MEME_TICKER_MIN_COUNT = 3
WSB_BASELINE_DAYS = 7

TABLE = "retail_sentiment_regime"

_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')
_STOPWORDS = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "WHO", "GET", "USD", "ETF",
    "CEO", "IPO", "SEC", "FED", "IMF", "GDP", "WSB", "DD", "YOLO",
    "OTM", "ATM", "ITM", "AMC", "SPY", "QQQ", "IWM", "VIX",
}


# ============================================================
# 数据获取
# ============================================================

async def _fetch_cboe_pc_ratio(trade_date: str) -> Optional[float]:
    """从 CBOE CDN 获取当日 EQUITY_PC_RATIO，失败往前最多回退 3 天。"""
    headers = {"User-Agent": WSB_USER_AGENT}
    for delta in range(3):
        dt = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=delta)
        url = CBOE_CSV_URL.format(date=dt.strftime("%Y-%m-%d"))
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    text = await resp.text()
                    val = _parse_cboe_csv(text)
                    if val is not None:
                        logger.info(f"[C5/CBOE] {dt.date()} EQUITY_PC_RATIO={val:.4f}")
                        return val
        except Exception as e:
            logger.warning(f"[C5/CBOE] {url} 失败: {e}")
    return None


def _parse_cboe_csv(csv_text: str) -> Optional[float]:
    """解析 CBOE CSV，模糊匹配 EQUITY_PC_RATIO 字段。"""
    lines = [l.strip() for l in csv_text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    headers = [h.strip().upper().replace(" ", "_") for h in lines[0].split(",")]
    for col in ("EQUITY_PC_RATIO", "EQUITY_P/C_RATIO", "PC_RATIO"):
        if col in headers:
            idx = headers.index(col)
            try:
                return float(lines[1].split(",")[idx].strip())
            except (ValueError, IndexError):
                continue
    return None


async def _fetch_wsb_mentions() -> dict[str, int]:
    """从 r/wallstreetbets hot.json 提取 ticker 提及次数。"""
    headers = {"User-Agent": WSB_USER_AGENT}
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    WSB_HOT_URL, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 429:
                        if attempt == 0:
                            await asyncio.sleep(3)
                            continue
                        logger.warning("[C5/WSB] Reddit 429 限流，跳过")
                        return {}
                    resp.raise_for_status()
                    data = await resp.json()
                    counts = _parse_wsb_mentions(data)
                    logger.info(f"[C5/WSB] 提取 {len(counts)} 个 ticker")
                    return counts
        except Exception as e:
            logger.warning(f"[C5/WSB] 请求失败: {e}")
            return {}
    return {}


def _parse_wsb_mentions(data: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for post in data.get("data", {}).get("children", []):
        title = post.get("data", {}).get("title", "")
        flair = post.get("data", {}).get("link_flair_text", "") or ""
        for m in _TICKER_RE.finditer(f"{title} {flair}"):
            t = m.group(1)
            if t not in _STOPWORDS:
                counts[t] = counts.get(t, 0) + 1
    return counts


# ============================================================
# Z-Score 计算
# ============================================================

def _compute_wsb_zscores(
    today_counts: dict[str, int],
    baseline_rows: list[dict],
) -> list[dict]:
    """计算当日 WSB 提及量的 z-score（相对过去 7 天均值）。"""
    historical: dict[str, list[int]] = {}
    for row in baseline_rows:
        for item in (row.get("wsb_top_mentions") or []):
            t = item.get("ticker", "")
            if t:
                historical.setdefault(t, []).append(item.get("count", 0))

    results = []
    for ticker, count in today_counts.items():
        if count < 2:
            continue
        hist = historical.get(ticker, [])
        if len(hist) >= 3:
            mean  = statistics.mean(hist)
            stdev = statistics.stdev(hist) if len(hist) > 1 else 1.0
            zscore = (count - mean) / max(stdev, 0.5)
        else:
            zscore = float(count - 2) / 2.0  # 冷启动近似
        results.append({"ticker": ticker, "count": count, "zscore": round(zscore, 2)})

    results.sort(key=lambda x: x["zscore"], reverse=True)
    return results[:30]


# ============================================================
# 综合判断
# ============================================================

def _classify_regime(
    pc_ratio: Optional[float],
    wsb_zscores: list[dict],
) -> tuple[bool, str, str, int]:
    """
    两源加权投票，返回 (meme_mode, meme_intensity, pc_signal, score)。
    """
    score = 0
    pc_signal = "unavailable"

    if pc_ratio is not None:
        if pc_ratio < PC_GREED_THRESHOLD:
            score += 2
            pc_signal = "greed"
        elif pc_ratio <= PC_NORMAL_UPPER:
            pc_signal = "neutral"
        elif pc_ratio <= PC_FEAR_THRESHOLD:
            pc_signal = "neutral_high"
        else:
            score -= 1
            pc_signal = "fear"

    meme_tickers = [x for x in wsb_zscores if x["zscore"] > WSB_ZSCORE_MEME_THRESHOLD]
    if len(meme_tickers) >= WSB_MEME_TICKER_MIN_COUNT:
        score += 2
    elif len(meme_tickers) >= 1:
        score += 1

    if score >= 3:
        return True, "extreme", pc_signal, score
    elif score >= 2:
        return True, "elevated", pc_signal, score
    elif score >= 0:
        return False, "normal", pc_signal, score
    else:
        return False, "fear", pc_signal, score


# ============================================================
# DeepSeek rationale（可选，失败不阻断）
# ============================================================

async def _generate_rationale(
    pc_ratio: Optional[float],
    pc_signal: str,
    meme_tickers: list[str],
    meme_intensity: str,
) -> str:
    fallback = _fallback_rationale(pc_ratio, pc_signal, meme_tickers, meme_intensity)
    try:
        from app.config.settings import settings
        if not getattr(settings, "deepseek_api_key", None):
            return fallback
        import httpx
        prompt = (
            f"市场数据：P/C比率={pc_ratio}({pc_signal})，"
            f"WSB异常标的={meme_tickers[:5]}，强度={meme_intensity}。"
            f"用30字以内中文解释当前{'是否处于'}散户炒作模式。"
        )
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.deepseek_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 80,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[C5] DeepSeek rationale 失败: {e}")
        return fallback


def _fallback_rationale(
    pc_ratio: Optional[float],
    pc_signal: str,
    meme_tickers: list[str],
    meme_intensity: str,
) -> str:
    label = {"extreme": "极度散户炒作", "elevated": "散户活跃",
              "normal": "正常", "fear": "市场恐慌"}.get(meme_intensity, meme_intensity)
    pc_part = f"P/C={pc_ratio:.2f}({pc_signal})" if pc_ratio else "P/C不可用"
    wsb_part = f"WSB热炒:{','.join(meme_tickers[:5])}" if meme_tickers else "WSB正常"
    return f"{label} | {pc_part} | {wsb_part}"


# ============================================================
# 主入口
# ============================================================

async def run_retail_sentiment_scan(trade_date: Optional[str] = None) -> dict:
    """
    C5 主入口：CBOE + WSB → 判断 meme_mode → 写 DB → 返回摘要。
    任意数据源失败不阻断，两源均失败时降级为 meme_mode=False。
    """
    if trade_date is None:
        import pytz
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        trade_date = now_et.strftime("%Y-%m-%d") if now_et.hour >= 17 \
            else (now_et - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"[C5] 散户情绪扫描开始，交易日={trade_date}")
    data_sources: dict[str, bool] = {}

    # Step 1: CBOE
    pc_ratio = await _fetch_cboe_pc_ratio(trade_date)
    data_sources["cboe"] = pc_ratio is not None

    # Step 2: WSB
    today_counts = await _fetch_wsb_mentions()
    data_sources["wsb"] = bool(today_counts)

    # 历史基线
    baseline_rows: list[dict] = []
    try:
        db = get_db()
        cutoff = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=WSB_BASELINE_DAYS)).strftime("%Y-%m-%d")
        res = db.table(TABLE).select("wsb_top_mentions").gte("date", cutoff).lt("date", trade_date).execute()
        baseline_rows = res.data or []
    except Exception as e:
        logger.warning(f"[C5] 历史基线加载失败: {e}")

    wsb_zscores = _compute_wsb_zscores(today_counts, baseline_rows)
    meme_tickers = [x["ticker"] for x in wsb_zscores if x["zscore"] > WSB_ZSCORE_MEME_THRESHOLD]

    # Step 3: 综合判断
    if not any(data_sources.values()):
        logger.error("[C5] 所有数据源均失败，降级 meme_mode=False")
        meme_mode, meme_intensity, pc_signal = False, "unavailable", "unavailable"
    else:
        meme_mode, meme_intensity, pc_signal, score = _classify_regime(pc_ratio, wsb_zscores)
        logger.info(f"[C5] score={score} → meme_mode={meme_mode} intensity={meme_intensity}")

    # Step 4: rationale
    rationale = await _generate_rationale(pc_ratio, pc_signal, meme_tickers, meme_intensity)

    # Step 5: upsert DB
    row = {
        "date": trade_date,
        "pc_ratio": float(pc_ratio) if pc_ratio is not None else None,
        "pc_signal": pc_signal,
        "wsb_top_mentions": wsb_zscores[:20],
        "wsb_meme_tickers": meme_tickers,
        "meme_mode": meme_mode,
        "meme_intensity": meme_intensity,
        "rationale": rationale,
        "data_sources": data_sources,
    }
    try:
        db = get_db()
        db.table(TABLE).upsert(row, on_conflict="date").execute()
        logger.info(f"[C5] DB 写入成功: {trade_date} meme_mode={meme_mode} intensity={meme_intensity}")
    except Exception as e:
        logger.error(f"[C5] DB 写入失败: {e}", exc_info=True)

    return {
        "date": trade_date,
        "meme_mode": meme_mode,
        "meme_intensity": meme_intensity,
        "pc_ratio": pc_ratio,
        "pc_signal": pc_signal,
        "wsb_meme_count": len(meme_tickers),
        "wsb_meme_tickers": meme_tickers[:10],
        "rationale": rationale,
        "status": "ok",
    }


# ============================================================
# ED 门控查询（供 event_driven_service 调用）
# ============================================================

async def get_today_meme_mode(trade_date: Optional[str] = None) -> tuple[bool, str]:
    """
    查询当日 meme_mode。DB 查不到时返回 (False, "数据未就绪")，不阻断 ED。
    """
    if trade_date is None:
        import pytz
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        trade_date = now_et.strftime("%Y-%m-%d") if now_et.hour >= 17 \
            else (now_et - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        db = get_db()
        res = db.table(TABLE).select("meme_mode,meme_intensity,rationale") \
                .eq("date", trade_date).limit(1).execute()
        if res.data:
            r = res.data[0]
            return r["meme_mode"], r.get("rationale", "")
        logger.warning(f"[C5] {trade_date} 无数据，ED 不受限")
        return False, "数据未就绪"
    except Exception as e:
        logger.warning(f"[C5] meme_mode 查询异常: {e}，ED 不受限")
        return False, f"查询异常: {e}"
