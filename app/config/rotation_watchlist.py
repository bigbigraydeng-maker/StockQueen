"""
StockQueen V2 - Rotation Watchlist Configuration
ETF + mid-cap US stock candidate pools for momentum rotation strategy
"""


class RotationConfig:
    """Momentum rotation strategy parameters"""

    # === Scoring weights (dynamic by regime, these are bull defaults) ===
    WEIGHT_1W: float = 0.20
    WEIGHT_1M: float = 0.40
    WEIGHT_3M: float = 0.40
    VOL_PENALTY: float = 0.50       # annualized vol penalty multiplier
    TREND_BONUS: float = 2.0        # bonus if close > MA20
    HOLDING_BONUS: float = 1.0      # bonus for already-held tickers (reduces turnover)

    # Dynamic momentum weights by regime (1W, 1M, 3M)
    MOMENTUM_WEIGHTS = {
        "strong_bull": (0.15, 0.35, 0.50),  # 强牛：偏重长期趋势
        "bull":        (0.20, 0.40, 0.40),  # 正常牛：均衡
        "choppy":      (0.35, 0.40, 0.25),  # 震荡：偏重短期反转
        "bear":        (0.40, 0.40, 0.20),  # 熊市：快速反应，减少长期拖累
    }

    # === Alpha Enhancement ===
    RELATIVE_STRENGTH_FILTER: bool = True   # 过滤掉相对强度<0的标的
    SCORE_WEIGHTED_ALLOC: bool = True       # 按评分加权分配仓位（vs等权）
    MAX_SECTOR_CONCENTRATION: int = 2       # 同板块最多持有N个标的
    GRADUATED_TREND_BONUS: bool = True      # 渐进式趋势奖励（vs二元MA20）
    BACKTEST_STOP_LOSS: bool = True         # 回测中模拟ATR止损
    BACKTEST_STOP_MULT: float = 2.0        # 回测止损倍数

    # === Selection ===
    TOP_N: int = 3                  # hold top N tickers
    REBALANCE_DAY: str = "mon"      # weekly rebalance day

    # === Market Regime ===
    REGIME_TICKER: str = "SPY"
    REGIME_MA_PERIOD: int = 50      # SPY vs MA50
    REGIME_CONFIRM_DAYS: int = 3    # 3 consecutive days to confirm

    # === Daily Entry ===
    ENTRY_MA_PERIOD: int = 5        # close > MA5
    ENTRY_VOL_PERIOD: int = 20      # volume > 20-day avg
    ENTRY_MAX_WAIT_DAYS: int = 5    # skip if no entry by Friday

    # === ATR Stop/Target ===
    ATR_PERIOD: int = 14
    ATR_STOP_MULTIPLIER: float = 2.0    # stop = entry - 2*ATR
    ATR_TARGET_MULTIPLIER: float = 3.0  # target = entry + 3*ATR

    # === Data periods ===
    LOOKBACK_DAYS: int = 90         # enough for 3-month return
    VOL_LOOKBACK: int = 21          # 21-day annualized vol


# === ETF Pools ===

OFFENSIVE_ETFS = [
    {"ticker": "SPY",  "name": "S&P 500"},
    {"ticker": "QQQ",  "name": "Nasdaq 100"},
    {"ticker": "IWM",  "name": "Russell 2000"},
    {"ticker": "XLK",  "name": "Technology"},
    {"ticker": "XLF",  "name": "Financials"},
    {"ticker": "XLE",  "name": "Energy"},
    {"ticker": "XLV",  "name": "Healthcare"},
    {"ticker": "XLI",  "name": "Industrials"},
    {"ticker": "XLC",  "name": "Communication"},
    {"ticker": "SOXX", "name": "Semiconductors"},
    {"ticker": "IBB",  "name": "Biotech"},
    {"ticker": "ARKK", "name": "ARK Innovation"},
    {"ticker": "VWO",  "name": "Emerging Markets"},
    {"ticker": "EFA",  "name": "EAFE Developed"},
]

DEFENSIVE_ETFS = [
    {"ticker": "TLT",  "name": "20+ Year Treasury"},
    {"ticker": "GLD",  "name": "Gold"},
    {"ticker": "SHY",  "name": "1-3 Year Treasury"},
]

# Inverse ETFs — used in bear regime for short exposure
INVERSE_ETFS = [
    {"ticker": "SH",   "name": "Short S&P500",      "asset_type": "inverse_etf"},
    {"ticker": "PSQ",  "name": "Short QQQ",          "asset_type": "inverse_etf"},
    {"ticker": "RWM",  "name": "Short Russell2000",  "asset_type": "inverse_etf"},
    {"ticker": "DOG",  "name": "Short Dow30",        "asset_type": "inverse_etf"},
]

# === Mid-Cap US Stocks ($500M - $20B) ===

MIDCAP_STOCKS = [
    # ── Tech Growth (12) ──
    {"ticker": "CRWD", "name": "CrowdStrike",    "sector": "tech"},
    {"ticker": "NET",  "name": "Cloudflare",     "sector": "tech"},
    {"ticker": "DDOG", "name": "Datadog",         "sector": "tech"},
    {"ticker": "MDB",  "name": "MongoDB",         "sector": "tech"},
    {"ticker": "BILL", "name": "Bill.com",        "sector": "tech"},
    {"ticker": "ZS",   "name": "Zscaler",         "sector": "tech"},
    {"ticker": "CFLT", "name": "Confluent",       "sector": "tech"},
    {"ticker": "GTLB", "name": "GitLab",          "sector": "tech"},
    {"ticker": "S",    "name": "SentinelOne",     "sector": "tech"},
    {"ticker": "IOT",  "name": "Samsara",         "sector": "tech"},
    {"ticker": "CYBR", "name": "CyberArk",        "sector": "tech"},
    {"ticker": "PANW", "name": "Palo Alto Networks","sector": "tech"},

    # ── Semiconductors (8) ──
    {"ticker": "MPWR", "name": "Monolithic Power", "sector": "semi"},
    {"ticker": "RMBS", "name": "Rambus",           "sector": "semi"},
    {"ticker": "ACLS", "name": "Axcelis Tech",     "sector": "semi"},
    {"ticker": "WOLF", "name": "Wolfspeed",        "sector": "semi"},
    {"ticker": "ALGM", "name": "Allegro Micro",    "sector": "semi"},
    {"ticker": "LSCC", "name": "Lattice Semi",     "sector": "semi"},
    {"ticker": "SMCI", "name": "Super Micro",      "sector": "semi"},
    {"ticker": "ARM",  "name": "Arm Holdings",     "sector": "semi"},

    # ── Biotech/Pharma (7) ──
    {"ticker": "EXAS", "name": "Exact Sciences",  "sector": "bio"},
    {"ticker": "HALO", "name": "Halozyme",        "sector": "bio"},
    {"ticker": "PCVX", "name": "Vaxcyte",         "sector": "bio"},
    {"ticker": "IONS", "name": "Ionis Pharma",    "sector": "bio"},
    {"ticker": "GERN", "name": "Geron",           "sector": "bio"},
    {"ticker": "CRNX", "name": "Crinetics",       "sector": "bio"},
    {"ticker": "NUVB", "name": "Nuvation Bio",    "sector": "bio"},

    # ── Consumer/Retail (7) ──
    {"ticker": "DUOL", "name": "Duolingo",        "sector": "consumer"},
    {"ticker": "BROS", "name": "Dutch Bros",      "sector": "consumer"},
    {"ticker": "CAVA", "name": "Cava Group",      "sector": "consumer"},
    {"ticker": "ELF",  "name": "e.l.f. Beauty",   "sector": "consumer"},
    {"ticker": "CELH", "name": "Celsius",         "sector": "consumer"},
    {"ticker": "BIRK", "name": "Birkenstock",     "sector": "consumer"},
    {"ticker": "ONON", "name": "On Holding",      "sector": "consumer"},

    # ── Industrial/Energy (6) ──
    {"ticker": "TDW",  "name": "Tidewater",       "sector": "industrial"},
    {"ticker": "PRIM", "name": "Primoris",        "sector": "industrial"},
    {"ticker": "POWL", "name": "Powell Industries","sector": "industrial"},
    {"ticker": "EME",  "name": "EMCOR Group",     "sector": "industrial"},
    {"ticker": "GVA",  "name": "Granite Constr",  "sector": "industrial"},
    {"ticker": "FIX",  "name": "Comfort Systems", "sector": "industrial"},

    # ── Fintech (5) ──
    {"ticker": "AFRM", "name": "Affirm",          "sector": "fintech"},
    {"ticker": "UPST", "name": "Upstart",         "sector": "fintech"},
    {"ticker": "SOFI", "name": "SoFi Tech",       "sector": "fintech"},
    {"ticker": "HOOD", "name": "Robinhood",       "sector": "fintech"},
    {"ticker": "TOST", "name": "Toast",           "sector": "fintech"},

    # ── SaaS/Cloud (5) ──
    {"ticker": "PCOR", "name": "Procore Tech",    "sector": "saas"},
    {"ticker": "BRZE", "name": "Braze",           "sector": "saas"},
    {"ticker": "MNDY", "name": "Monday.com",      "sector": "saas"},
    {"ticker": "ESTC", "name": "Elastic",         "sector": "saas"},
    {"ticker": "DOCN", "name": "DigitalOcean",    "sector": "saas"},

    # ── Space/Frontier (5) ──
    {"ticker": "RKLB", "name": "Rocket Lab",      "sector": "space"},
    {"ticker": "ASTS", "name": "AST SpaceMobile", "sector": "space"},
    {"ticker": "JOBY", "name": "Joby Aviation",   "sector": "space"},
    {"ticker": "LUNR", "name": "Intuitive Mach",  "sector": "space"},
    {"ticker": "RDW",  "name": "Redwire",         "sector": "space"},

    # ── 中概股 China ADR (10) ──
    {"ticker": "PDD",  "name": "拼多多 PDD Holdings", "sector": "china"},
    {"ticker": "BABA", "name": "阿里巴巴 Alibaba",    "sector": "china"},
    {"ticker": "JD",   "name": "京东 JD.com",         "sector": "china"},
    {"ticker": "BIDU", "name": "百度 Baidu",           "sector": "china"},
    {"ticker": "NIO",  "name": "蔚来 NIO",             "sector": "china"},
    {"ticker": "XPEV", "name": "小鹏 XPeng",           "sector": "china"},
    {"ticker": "LI",   "name": "理想 Li Auto",         "sector": "china"},
    {"ticker": "BILI", "name": "哔哩哔哩 Bilibili",    "sector": "china"},
    {"ticker": "TME",  "name": "腾讯音乐 Tencent Music","sector": "china"},
    {"ticker": "FUTU", "name": "富途 Futu Holdings",   "sector": "china"},

    # ── AI/数据 (5) ──
    {"ticker": "PLTR", "name": "Palantir",        "sector": "ai"},
    {"ticker": "AI",   "name": "C3.ai",           "sector": "ai"},
    {"ticker": "BBAI", "name": "BigBear.ai",      "sector": "ai"},
    {"ticker": "PATH", "name": "UiPath",          "sector": "ai"},
    {"ticker": "SNOW", "name": "Snowflake",       "sector": "ai"},
]


def get_all_tickers() -> list[str]:
    """Get all tickers from all pools (offensive + defensive + midcap + inverse)"""
    tickers = []
    for item in OFFENSIVE_ETFS + DEFENSIVE_ETFS + MIDCAP_STOCKS + INVERSE_ETFS:
        tickers.append(item["ticker"])
    return tickers


def get_offensive_tickers() -> list[str]:
    """Get offensive ETF + midcap stock tickers (for scoring in bull regime)"""
    tickers = []
    for item in OFFENSIVE_ETFS + MIDCAP_STOCKS:
        tickers.append(item["ticker"])
    return tickers


def get_defensive_tickers() -> list[str]:
    """Get defensive ETF tickers (for bear regime)"""
    return [item["ticker"] for item in DEFENSIVE_ETFS]


def get_inverse_tickers() -> list[str]:
    """Get inverse ETF tickers (for bear regime short exposure)"""
    return [item["ticker"] for item in INVERSE_ETFS]


def get_ticker_info(ticker: str) -> dict | None:
    """Get name/sector info for a ticker"""
    for item in OFFENSIVE_ETFS + DEFENSIVE_ETFS + MIDCAP_STOCKS + INVERSE_ETFS:
        if item["ticker"] == ticker:
            return item
    return None
