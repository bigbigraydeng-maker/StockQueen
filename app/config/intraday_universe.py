"""
铃铛策略股票池 — 设计说明（INTRADAY_UNIVERSE）

目标
----
在 MAX_UNIVERSE_SIZE=50 约束下，偏向「日内可交易、成交活跃、波动足够」的标的，
使 30 分钟动能与 ATR/百分比止盈在统计上更可触发，而非偏防御蓝筹。

入选原则（人工清单，按季度复盘）
--------------------------------
1. **流动性**：美股主板，日均成交额通常处于全市场前列。
2. **波动**：优先历史 beta / 已实现波动高于大盘；日内振幅通常 ≥1.5%。
3. **可执行性**：避免过窄 spread 的小盘仙股；本清单不含 OTC-only。
4. **结构**：约 7% 为宽基/行业 ETF（SPY/QQQ/XLK），其余为个股。
5. **分层**：`INTRADAY_AUTO_ENTRY_DENY` 内标的仍参与打分与 SPY 对标，
   但执行层不会自动买入。

版本历史
--------
v2026-04-02-layered-pool  初版，50 只含大量低波蓝筹
v2026-04-11-high-pulse    精简：砍低波蓝筹，META 开放自动建仓，加 APP/MSTR/RDDT/TSM
"""

INTRADAY_UNIVERSE_VERSION: str = "2026-04-11-high-pulse"

# 参与评分与相对强弱，但**禁止自动开仓**
# 原则：ETF 基准 + 真正脉冲空间极低的超大盘（AAPL/MSFT/GOOGL/AMZN 日内振幅通常 <1%）
INTRADAY_AUTO_ENTRY_DENY: frozenset[str] = frozenset({
    # 宽基 / 行业 ETF — 做相对强弱基准
    "SPY",
    "QQQ",
    "XLK",
    # 超大盘低脉冲 — 日内振幅通常不足，30min 信号滞后
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
})

# 44 只 = 3 ETF + 41 股；顺序无关，intraday 内会 set() 使用
INTRADAY_UNIVERSE: list[str] = [
    # --- 基准 ETF（流动性极好，作相对强弱基准）---
    "SPY",
    "QQQ",
    "XLK",

    # --- 超大盘（DENY，作 flow 参照）---
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",

    # --- 高脉冲大科技 / AI（日内振幅 2%+，开放自动建仓）---
    "META",
    "NVDA",
    "TSLA",
    "NFLX",
    "AMD",
    "AVGO",

    # --- 半导体产业链（成交量大、事件驱动波动强）---
    "INTC",
    "QCOM",
    "MU",
    "AMAT",
    "LRCX",
    "KLAC",
    "MRVL",
    "SMCI",
    "ARM",
    "TSM",       # 台积电：ADR 成交活跃，地缘事件驱动

    # --- 高 beta 成长平台（波动显著高于大盘）---
    "PLTR",
    "CRWD",
    "COIN",
    "UBER",
    "DASH",
    "SOFI",
    "HOOD",
    "DKNG",
    "APP",       # AppLovin：近期最强 AI 广告概念，日内振幅大
    "RDDT",      # Reddit：高波动中小盘成长

    # --- 加密 / 另类（高 beta，与 BTC 联动）---
    "MSTR",      # MicroStrategy：BTC 敞口最大的上市公司，振幅极高

    # --- 金融（高成交、事件驱动波动）---
    "JPM",
    "GS",
    "BAC",

    # --- 能源（商品周期波动）---
    "XOM",
    "CVX",

    # --- 工业 / 消费（保留流动性顶尖、有日内脉冲的）---
    "CAT",
    "HD",
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
