"""
StockQueen C5 — Retail Sentiment Regime Gate

每日盘后（10:10 NZT）检测散户炒作 Regime，输出 meme_mode 供 ED 策略入场门控。

数据源：
  1. Fear and Greed Index（替代 CBOE P/C 比率，完全免费无认证）
     来源：https://api.alternative.me/fng/
  2. Reddit r/wallstreetbets 热帖提及量（免费，User-Agent 即可）

判断逻辑（加权投票）：
  Fear and Greed: 75-100 (Extreme Greed)  → +2（散户疯狂贪心）
  Fear and Greed: 55-75 (Greed)           → +1（散户贪心）
  Fear and Greed: 25-75 (Normal)          → 0（正常）
  Fear and Greed: 0-25 (Extreme Fear)     → -1（市场恐慌）

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

# Fear and Greed Index API（替代 CBOE P/C 比率）
FEAR_GREED_API_URL = "https://api.alternative.me/fng/?limit=1"

WSB_HOT_URL = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=100"
WSB_USER_AGENT = "StockQueen Research/1.0 (research@stockqueen.app)"

# StockTwits 散户情绪 API（免费）
STOCKTWITS_API_URL = "https://api.stocktwits.com/api/2/trending/symbols"

# Fear and Greed 分类阈值（0-100）
FEAR_GREED_EXTREME_GREED = 75    # 75-100: 极度贪心 (+2分)
FEAR_GREED_GREED = 55            # 55-75: 贪心 (+1分)
FEAR_GREED_FEAR = 25             # 0-25: 极度恐慌 (-1分)

WSB_ZSCORE_MEME_THRESHOLD = 2.0
WSB_MEME_TICKER_MIN_COUNT = 3
WSB_BASELINE_DAYS = 7

TABLE = "retail_sentiment_regime"

# VIX 波动率恐慌指数
VIX_EXTREME_FEAR = 35      # > 35: 极度恐慌
VIX_HIGH_FEAR = 25         # 25-35: 高度恐慌
VIX_NORMAL = 15            # < 15: 贪婪

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

async def _fetch_fear_and_greed_index() -> Optional[float]:
    """
    从 alternative.me 获取 Fear and Greed Index（0-100）。
    完全免费，无需认证，替代 CBOE P/C 比率。

    返回值：0-100 的浮点数
    """
    headers = {"User-Agent": WSB_USER_AGENT}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                FEAR_GREED_API_URL, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                # 解析响应
                if data.get("data"):
                    fng_value = float(data["data"][0].get("value", 0))
                    fng_class = data["data"][0].get("value_classification", "Unknown")
                    logger.info(f"[C5/FNG] Fear and Greed Index={fng_value:.1f} ({fng_class})")
                    return fng_value
                else:
                    logger.warning("[C5/FNG] 响应中无数据")
                    return None

    except Exception as e:
        logger.warning(f"[C5/FNG] 获取失败: {e}")
        return None


async def _fetch_market_sentiment_alternative() -> dict[str, float]:
    """
    获取整体市场情绪（备选方案，因 StockTwits 反爬虫）。
    采用 Fear_and_Greed 的情绪分类映射到 -100 到 +100 的评分。

    返回格式：
    {
        "bullish_pct": 65.5,     # 看涨占比（推导）
        "bearish_pct": 34.5,     # 看跌占比（推导）
        "sentiment_score": 15.5  # 综合情绪评分（-100 到 +100）
        "source": "fng_based"    # 数据来源说明
    }
    """
    try:
        # 尝试从 StockTwits API 获取
        headers = {"User-Agent": WSB_USER_AGENT}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                STOCKTWITS_API_URL, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("data"):
                        symbols = data["data"][:20]
                        bullish_count = sum(1 for s in symbols if s.get("watchlist", 0) > 0)
                        bullish_pct = (bullish_count / len(symbols) * 100) if symbols else 0
                        sentiment_score = (bullish_pct - 50) * 2
                        result = {
                            "bullish_pct": round(bullish_pct, 1),
                            "bearish_pct": round(100 - bullish_pct, 1),
                            "sentiment_score": round(sentiment_score, 1),
                            "source": "stocktwits",
                        }
                        logger.info(f"[C5/ST] StockTwits 数据成功: {result}")
                        return result
    except Exception as e:
        logger.debug(f"[C5/ST] StockTwits 获取失败，使用备选: {e}")

    # 备选方案：用 Fear_and_Greed 推导市场情绪
    # 这不完全准确，但提供一个基础的情绪信号
    try:
        # 获取最新 FNG 指数以映射情绪
        fng_val = await _fetch_fear_and_greed_index()
        if fng_val is not None:
            # 将 FNG (0-100) 映射到情绪评分 (-100 到 +100)
            sentiment_score = (fng_val - 50) * 2
            bullish_pct = (fng_val / 100) * 100  # 用 FNG 作为代理

            result = {
                "bullish_pct": round(bullish_pct, 1),
                "bearish_pct": round(100 - bullish_pct, 1),
                "sentiment_score": round(sentiment_score, 1),
                "source": "fng_proxy",
            }
            logger.info(f"[C5/Sentiment] 使用 FNG 代理情绪: {result}")
            return result
    except Exception as e:
        logger.warning(f"[C5/Sentiment] 备选方案也失败: {e}")

    return {}


async def _fetch_vix_from_cnbc() -> Optional[float]:
    """
    从 CNBC API 获取 VIX 实时报价（波动率指数）。
    备选方案，因 Massive 不支持 VIX。

    VIX 是恐慌指数，反映市场预期波动率：
    - VIX < 15: 市场平静，贪婪
    - VIX 15-25: 正常
    - VIX 25-35: 高度恐慌
    - VIX > 35: 极度恐慌

    返回值：VIX 数值（通常 10-100 范围）
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cnbc.com",
        }

        async with aiohttp.ClientSession() as session:
            # 尝试从 CNBC 获取 VIX 页面
            async with session.get(
                "https://www.cnbc.com/quotes/VIX",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[C5/VIX] CNBC 返回 {resp.status}")
                    return None

                html = await resp.text()

                # 简单的正则提取
                import re
                match = re.search(r'"price":\s*"?(\d+\.?\d*)"?', html)
                if match:
                    vix_value = float(match.group(1))
                    logger.info(f"[C5/VIX] VIX={vix_value:.2f}")
                    return vix_value
                else:
                    logger.warning("[C5/VIX] 无法从 HTML 中提取 VIX 值")
                    return None

    except Exception as e:
        logger.warning(f"[C5/VIX] CNBC 获取失败: {e}")
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
    fng_index: Optional[float],
    vix_value: Optional[float],
    stocktwits_sentiment: dict,
    wsb_zscores: list[dict],
) -> tuple[bool, str, str, int]:
    """
    四源加权投票，返回 (meme_mode, meme_intensity, signal, score)。

    数据源权重分配：
    - Fear and Greed Index (40%)
    - VIX 波动率 (35%)
    - StockTwits 情绪 (15%)
    - WSB 异常标的 (10%)

    评分逻辑：总分 >= 3 → 散户模式
    """
    score = 0
    signals = []

    # 1. Fear and Greed Index (40%)
    fng_weight = 0.4
    if fng_index is not None:
        if fng_index >= FEAR_GREED_EXTREME_GREED:  # 75-100
            score += 2 * fng_weight
            signals.append(f"FNG{fng_index:.0f}(extreme_greed)")
        elif fng_index >= FEAR_GREED_GREED:  # 55-75
            score += 1 * fng_weight
            signals.append(f"FNG{fng_index:.0f}(greed)")
        elif fng_index >= FEAR_GREED_FEAR:  # 25-55
            signals.append(f"FNG{fng_index:.0f}(neutral)")
        else:  # 0-25
            score -= 1 * fng_weight
            signals.append(f"FNG{fng_index:.0f}(extreme_fear)")

    # 2. VIX 波动率 (35%)
    vix_weight = 0.35
    if vix_value is not None:
        if vix_value > VIX_EXTREME_FEAR:  # > 35
            score -= 1 * vix_weight
            signals.append(f"VIX{vix_value:.1f}(panic)")
        elif vix_value > VIX_HIGH_FEAR:  # 25-35
            # 中性，不加分
            signals.append(f"VIX{vix_value:.1f}(fear)")
        elif vix_value < VIX_NORMAL:  # < 15
            score += 2 * vix_weight
            signals.append(f"VIX{vix_value:.1f}(greed)")
        else:  # 15-25
            score += 1 * vix_weight
            signals.append(f"VIX{vix_value:.1f}(neutral)")

    # 3. StockTwits 情绪 (15%)
    st_weight = 0.15
    st_sentiment = stocktwits_sentiment.get("sentiment_score", 0)
    if st_sentiment > 0:  # 看涨
        if st_sentiment >= 30:  # 极度看涨
            score += 2 * st_weight
            signals.append(f"ST+{st_sentiment:.0f}(bull)")
        else:  # 中等看涨
            score += 1 * st_weight
            signals.append(f"ST+{st_sentiment:.0f}(slight_bull)")
    elif st_sentiment < 0:  # 看跌
        score -= 0.5 * st_weight
        signals.append(f"ST{st_sentiment:.0f}(bear)")
    else:
        signals.append("ST=0(neutral)")

    # 4. WSB 异常标的 (10%)
    wsb_weight = 0.10
    meme_tickers = [x for x in wsb_zscores if x["zscore"] > WSB_ZSCORE_MEME_THRESHOLD]
    if len(meme_tickers) >= WSB_MEME_TICKER_MIN_COUNT:
        score += 2 * wsb_weight
        signals.append(f"WSB{len(meme_tickers)}(extreme)")
    elif len(meme_tickers) >= 1:
        score += 1 * wsb_weight
        signals.append(f"WSB{len(meme_tickers)}(active)")
    else:
        signals.append("WSB=0(normal)")

    # 综合判断
    combined_signal = " | ".join(signals)

    if score >= 3:
        return True, "extreme", combined_signal, score
    elif score >= 2:
        return True, "elevated", combined_signal, score
    elif score >= 0:
        return False, "normal", combined_signal, score
    else:
        return False, "fear", combined_signal, score


# ============================================================
# DeepSeek rationale（可选，失败不阻断）
# ============================================================

async def _generate_rationale(
    fng_index: Optional[float],
    fng_signal: str,
    meme_tickers: list[str],
    meme_intensity: str,
) -> str:
    fallback = _fallback_rationale(fng_index, fng_signal, meme_tickers, meme_intensity)
    try:
        from app.config.settings import settings
        if not getattr(settings, "deepseek_api_key", None):
            return fallback
        import httpx
        prompt = (
            f"市场数据：Fear and Greed指数={fng_index}({fng_signal})，"
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
    fng_index: Optional[float],
    fng_signal: str,
    meme_tickers: list[str],
    meme_intensity: str,
) -> str:
    label = {"extreme": "极度散户炒作", "elevated": "散户活跃",
              "normal": "正常", "fear": "市场恐慌"}.get(meme_intensity, meme_intensity)
    fng_part = f"FNG={fng_index:.0f}({fng_signal})" if fng_index is not None else "FNG不可用"
    wsb_part = f"WSB热炒:{','.join(meme_tickers[:5])}" if meme_tickers else "WSB正常"
    return f"{label} | {fng_part} | {wsb_part}"


# ============================================================
# 主入口
# ============================================================

async def run_retail_sentiment_scan(trade_date: Optional[str] = None) -> dict:
    """
    C5 主入口：Fear and Greed Index + WSB → 判断 meme_mode → 写 DB → 返回摘要。
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

    # Step 1: Fear and Greed Index（40% 权重）
    fng_index = await _fetch_fear_and_greed_index()
    data_sources["fear_and_greed"] = fng_index is not None

    # Step 2: VIX 波动率（35% 权重）
    vix_value = await _fetch_vix_from_cnbc()
    data_sources["vix"] = vix_value is not None

    # Step 3: 市场情绪（15% 权重）- StockTwits 或备选方案
    market_sentiment = await _fetch_market_sentiment_alternative()
    data_sources["market_sentiment"] = bool(market_sentiment)

    # Step 4: WSB（10% 权重）
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

    # Step 5: 综合判断
    if not any(data_sources.values()):
        logger.error("[C5] 所有数据源均失败，降级 meme_mode=False")
        meme_mode, meme_intensity, combined_signal = False, "unavailable", "unavailable"
    else:
        meme_mode, meme_intensity, combined_signal, score = _classify_regime(
            fng_index, vix_value, market_sentiment, wsb_zscores
        )
        logger.info(
            f"[C5] 综合评分={score:.2f} → meme_mode={meme_mode} intensity={meme_intensity} "
            f"FNG={fng_index} VIX={vix_value} Sentiment={market_sentiment.get('sentiment_score', 'N/A')}"
        )

    # Step 6: rationale
    rationale = await _generate_rationale(fng_index, combined_signal, meme_tickers, meme_intensity)

    # Step 7: upsert DB
    # 临时方案：用 pc_ratio 字段存储 fng_index（向后兼容）
    row = {
        "date": trade_date,
        "pc_ratio": float(fng_index) if fng_index is not None else None,
        "pc_signal": combined_signal[:200],  # 字段长度限制，存储综合信号
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
        "fng_index": fng_index,
        "vix_value": vix_value,
        "market_sentiment_score": market_sentiment.get("sentiment_score"),
        "wsb_meme_count": len(meme_tickers),
        "wsb_meme_tickers": meme_tickers[:10],
        "combined_signal": combined_signal,
        "rationale": rationale,
        "data_sources_available": data_sources,
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
