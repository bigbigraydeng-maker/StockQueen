"""
铃铛策略股票池 — 设计说明（INTRADAY_UNIVERSE）

目标
----
在 MAX_UNIVERSE_SIZE=50 约束下，偏向「日内可交易、成交活跃、波动足够」的标的，
使 30 分钟动能与 ATR/百分比止盈在统计上更可触发，而非偏防御蓝筹。

入选原则（人工清单，按季度复盘）
--------------------------------
1. **流动性**：美股主板，日均成交额通常处于全市场前列（具体阈值可后续用脚本量化：
   20 日平均美元成交额 ≥ 约 $50M 量级，随名单整体上调）。
2. **波动**：优先历史 beta / 已实现波动高于大盘的典型板块——大科技、半导体产业链、
   高 beta 平台/金融科技/出行，保留少量高流动 ETF 作基准与行业暴露。
3. **可执行性**：避免过窄 spread 的小盘仙股；本清单不含 OTC-only。
4. **结构**：约 8% 为宽基/行业 ETF（SPY/QQQ/XLK/XLV），其余为个股，便于动能分化。
5. **分层**：`INTRADAY_AUTO_ENTRY_DENY` 内标的仍参与打分与 SPY 对标，但执行层不会自动买入（见 `intraday_config` / `intraday_trader`）。

未纳入
------
- 极低成交主题小票、纯 meme 微盘（可控性差）
- 与铃铛执行器 UNIVERSE 检查不一致的 symbol（需与券商合约一致）

维护
----
- 版本号见 INTRADAY_UNIVERSE_VERSION；调整名单时递增并记录日期。
- 可选后续：`scripts/refresh_intraday_universe.py` 从动态池按 ADV/ATR% 筛选后覆写本列表（需人工确认）。
"""

INTRADAY_UNIVERSE_VERSION: str = "2026-04-02-layered-pool"

# 参与评分与相对强弱，但**禁止自动开仓**（宽基/行业 ETF + 超大盘、低脉冲空间标的）
INTRADAY_AUTO_ENTRY_DENY: frozenset[str] = frozenset({
    "SPY",
    "QQQ",
    "XLK",
    "XLV",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "JPM",
    "V",
    "MA",
    "UNH",
    "LLY",
    "XOM",
    "CVX",
    "GS",
    "BAC",
})

# 50 = 4 ETF + 46 股；顺序无关，intraday 内会 set() 使用
INTRADAY_UNIVERSE: list[str] = [
    # --- 基准与行业 ETF（流动性极好，作相对强弱与分散）---
    "SPY",
    "QQQ",
    "XLK",
    "XLV",
    # --- 大科技 / 半导体（高成交、高日内振幅）---
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "AMD",
    "AVGO",
    "NFLX",
    "ORCL",
    "ADBE",
    "CRM",
    "INTC",
    "QCOM",
    "MU",
    "AMAT",
    "LRCX",
    "KLAC",
    "MRVL",
    # --- 高 beta / 成长平台（波动显著高于典型蓝筹）---
    "PLTR",
    "SMCI",
    "CRWD",
    "COIN",
    "UBER",
    "DASH",
    "SOFI",
    "HOOD",
    "DKNG",
    "ARM",
    # --- 金融（高成交、事件驱动波动）---
    "JPM",
    "GS",
    "BAC",
    "V",
    "MA",
    # --- 能源（商品与周期波动）---
    "XOM",
    "CVX",
    # --- 工业 / 国防（流动性尚可，保留板块分散）---
    "BA",
    "CAT",
    "RTX",
    "GE",
    # --- 医疗大盘（流动性顶尖，波动中等但必选龙头）---
    "UNH",
    "LLY",
    # --- 零售 / 消费（成交大；保留 NKE 作高换手运动零售暴露）---
    "COST",
    "HD",
    "NKE",
]


def assert_universe_constraints(max_size: int = 50) -> None:
    """开发时校验：无重复、数量不超过上限。"""
    if len(INTRADAY_UNIVERSE) != len(set(INTRADAY_UNIVERSE)):
        dup = [t for t in INTRADAY_UNIVERSE if INTRADAY_UNIVERSE.count(t) > 1]
        raise ValueError(f"Duplicate tickers in INTRADAY_UNIVERSE: {set(dup)}")
    if len(INTRADAY_UNIVERSE) > max_size:
        raise ValueError(
            f"INTRADAY_UNIVERSE len={len(INTRADAY_UNIVERSE)} > max_size={max_size}"
        )


def is_auto_entry_denied(ticker: str) -> bool:
    """Tiger 返回可能带后缀，与 _canon_ticker 一致用大写、空格前截断。"""
    if not ticker:
        return False
    t = str(ticker).strip().upper()
    if " " in t:
        t = t.split()[0]
    return t in INTRADAY_AUTO_ENTRY_DENY


assert_universe_constraints()
