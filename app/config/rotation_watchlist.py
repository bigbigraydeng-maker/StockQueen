"""
StockQueen 破浪 - 宝典V4 参数配置
ETF + large-cap + mid-cap US stock candidate pools for momentum rotation strategy
"""


class RotationConfig:
    """Momentum rotation strategy parameters"""

    # === Scoring weights (dynamic by regime, these are bull defaults) ===
    WEIGHT_1W: float = 0.20
    WEIGHT_1M: float = 0.40
    WEIGHT_3M: float = 0.40
    VOL_PENALTY: float = 0.50       # annualized vol penalty multiplier
    TREND_BONUS: float = 2.0        # bonus if close > MA20
    HOLDING_BONUS: float = 0.0      # locked via WF v4 (was 0.5, 5/6 windows chose 0)

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
    BACKTEST_STOP_MULT: float = 1.5        # 回测止损倍数 (locked via WF)
    BACKTEST_TRAILING_MULT: float = 1.5    # 回测 trailing distance (0=disabled)
    BACKTEST_TRAILING_ACTIVATE: float = 0.5  # 回测 trailing 激活阈值 (locked via WF)
    BACKTEST_SLIPPAGE: float = 0.001       # 单边滑点 0.1% (买卖各扣一次)
    BACKTEST_MIN_AVG_VOL: int = 500_000    # 最低20日均成交量
    BACKTEST_NEXT_OPEN: bool = True        # 用次日开盘价入场(替代收盘价)

    # === Selection ===
    TOP_N: int = 3                  # locked via WF v5 expanding (3-way test: top_n=2 W4 OOS=0灾难, top_n=6 avg=2.33不稳, top_n=3 avg=3.10 5/5全正 ✅)
    MIN_SCORE_THRESHOLD: float = 0.0  # minimum score to qualify; prevents forced selection
                                      # of negative-score tickers when universe is small

    # === 动态 Regime 门控 (V5) ===
    # 牛市放宽入场阈值（让优质票更容易进入），熊市收紧（只留高置信度信号）
    # 实验验证：avg Sharpe 1.89 → 2.31 (+22%)
    MIN_SCORE_BY_REGIME: dict = {
        "strong_bull": -0.1,  # 强牛：放宽，捕捉更多上涨机会
        "bull":         0.0,  # 牛市：沿用 WF 锁定基准值
        "choppy":       0.2,  # 震荡：收紧，只买高置信度信号
        "bear":         0.5,  # 熊市：大幅收紧，空仓优先，强信号才入场
    }
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
    ATR_STOP_MULTIPLIER: float = 1.5    # stop = entry - 1.5*ATR (locked via WF, bull default)
    ATR_TARGET_MULTIPLIER: float = 3.0  # target = entry + 3*ATR (bull default)

    # Regime-aware ATR multipliers (override defaults based on market regime)
    # 熊市保守ETF/反向ETF 快打快撤，强牛市让利润奔跑
    ATR_TARGET_BY_REGIME: dict = {
        "strong_bull": 4.0,   # 强牛：放宽止盈，让利润奔跑
        "bull":        3.0,   # 正常牛：沿用 WF 锁定值
        "choppy":      2.5,   # 震荡：熊市反弹短暂，提前锁利
        "bear":        2.0,   # 熊市：防御/反向ETF快打快撤
    }
    ATR_STOP_BY_REGIME: dict = {
        "strong_bull": 1.5,   # 强牛：沿用 WF 锁定值
        "bull":        1.5,   # 正常牛：沿用 WF 锁定值
        "choppy":      1.2,   # 震荡：止损适度收紧
        "bear":        1.0,   # 熊市：更紧止损保护本金，R:R 仍维持 2:1
    }

    # === Trailing Stop ===
    TRAILING_STOP_ENABLED: bool = True
    TRAILING_STOP_ATR_MULT: float = 1.5   # trailing distance = ATR * N
    TRAILING_ACTIVATE_ATR: float = 0.5    # activate after profit >= N * ATR (locked via WF)

    # === Data periods ===
    LOOKBACK_DAYS: int = 90         # enough for 3-month return
    VOL_LOOKBACK: int = 21          # 21-day annualized vol

    # === Dynamic Universe (V5) ===
    UNIVERSE_MIN_MARKET_CAP: float = 500_000_000   # $500M minimum market cap
    UNIVERSE_MIN_AVG_VOLUME: int = 500_000          # 20-day avg volume >= 500K shares
    UNIVERSE_MIN_LISTED_DAYS: int = 365             # listed at least 1 year
    UNIVERSE_MIN_PRICE: float = 5.0                 # share price >= $5
    USE_DYNAMIC_UNIVERSE: bool = True               # True = use dynamic universe (1578 tickers)
    # Step 4: 基本面质量门控（IC验证结论：剔除低质量标的，提升因子信号）
    UNIVERSE_QUALITY_GATE: bool = True              # True = 启用质量门控
    UNIVERSE_QUALITY_EPS_MIN_POSITIVE: int = 2      # 最近4季中至少N季 EPS > 0
    UNIVERSE_QUALITY_CF_MIN_POSITIVE: int = 1       # 最近2季中至少N季 OperatingCF > 0

    # === ML Enhancement (V3A) ===
    USE_ML_ENHANCE: bool = True     # 启用 ML-V3A 非对称标签排序模型
    ML_RERANK_POOL: int = 10        # 规则层选出 Top-N，ML从中重排后取 TOP_N


# === ETF Pools ===

OFFENSIVE_ETFS = [
    {"ticker": "SPY",  "name": "S&P 500",           "sector": "index"},
    {"ticker": "QQQ",  "name": "Nasdaq 100",        "sector": "index"},
    {"ticker": "IWM",  "name": "Russell 2000",      "sector": "index"},
    {"ticker": "XLK",  "name": "Technology",        "sector": "mega_tech"},
    {"ticker": "XLF",  "name": "Financials",        "sector": "financials"},
    {"ticker": "XLE",  "name": "Energy",            "sector": "energy"},
    {"ticker": "XLV",  "name": "Healthcare",        "sector": "healthcare"},
    {"ticker": "XLI",  "name": "Industrials",       "sector": "industrials"},
    {"ticker": "XLC",  "name": "Communication",     "sector": "telecom"},
    {"ticker": "SOXX", "name": "Semiconductors",    "sector": "semi"},
    {"ticker": "IBB",  "name": "Biotech",           "sector": "bio"},
    {"ticker": "ARKK", "name": "ARK Innovation",    "sector": "mega_tech"},
    {"ticker": "VWO",  "name": "Emerging Markets",  "sector": "intl"},
    {"ticker": "EFA",  "name": "EAFE Developed",    "sector": "intl"},
]

DEFENSIVE_ETFS = [
    {"ticker": "TLT",  "name": "20+ Year Treasury", "sector": "bond"},
    {"ticker": "GLD",  "name": "Gold",              "sector": "commodity"},
    {"ticker": "SHY",  "name": "1-3 Year Treasury", "sector": "bond"},
]

# Inverse ETFs - used in bear regime for short exposure
INVERSE_ETFS = [
    {"ticker": "SH",   "name": "Short S&P500",      "asset_type": "inverse_etf", "sector": "inverse"},
    {"ticker": "PSQ",  "name": "Short QQQ",          "asset_type": "inverse_etf", "sector": "inverse"},
    {"ticker": "RWM",  "name": "Short Russell2000",  "asset_type": "inverse_etf", "sector": "inverse"},
    {"ticker": "DOG",  "name": "Short Dow30",        "asset_type": "inverse_etf", "sector": "inverse"},
]

# Mapping: inverse ETF → underlying index ticker (for bear regime scoring)
INVERSE_ETF_INDEX_MAP = {
    "SH":  "SPY",   # Short S&P 500
    "PSQ": "QQQ",   # Short Nasdaq 100
    "RWM": "IWM",   # Short Russell 2000
    "DOG": "DIA",   # Short Dow 30
}


# === Large-Cap Blue Chips (~100) ===
# All pre-2015 IPO, no survivorship bias risk

LARGECAP_STOCKS = [
    # Mega-Cap Tech (7)
    {"ticker": "AAPL", "name": "Apple",              "sector": "mega_tech"},
    {"ticker": "MSFT", "name": "Microsoft",          "sector": "mega_tech"},
    {"ticker": "NVDA", "name": "NVIDIA",             "sector": "mega_tech"},
    {"ticker": "AMZN", "name": "Amazon",             "sector": "mega_tech"},
    {"ticker": "META", "name": "Meta Platforms",     "sector": "mega_tech"},
    {"ticker": "GOOG", "name": "Alphabet",           "sector": "mega_tech"},
    {"ticker": "TSLA", "name": "Tesla",              "sector": "mega_tech"},

    # Financials (14)
    {"ticker": "JPM",  "name": "JPMorgan Chase",    "sector": "financials"},
    {"ticker": "GS",   "name": "Goldman Sachs",     "sector": "financials"},
    {"ticker": "V",    "name": "Visa",              "sector": "financials"},
    {"ticker": "MA",   "name": "Mastercard",        "sector": "financials"},
    {"ticker": "BLK",  "name": "BlackRock",         "sector": "financials"},
    {"ticker": "BAC",  "name": "Bank of America",   "sector": "financials"},
    {"ticker": "WFC",  "name": "Wells Fargo",       "sector": "financials"},
    {"ticker": "C",    "name": "Citigroup",         "sector": "financials"},
    {"ticker": "SCHW", "name": "Charles Schwab",    "sector": "financials"},
    {"ticker": "MS",   "name": "Morgan Stanley",    "sector": "financials"},
    {"ticker": "AIG",  "name": "AIG",               "sector": "financials"},
    {"ticker": "MET",  "name": "MetLife",           "sector": "financials"},
    {"ticker": "PRU",  "name": "Prudential",        "sector": "financials"},
    {"ticker": "TRV",  "name": "Travelers",         "sector": "financials"},

    # Healthcare (7)
    {"ticker": "UNH",  "name": "UnitedHealth",      "sector": "healthcare"},
    {"ticker": "LLY",  "name": "Eli Lilly",         "sector": "healthcare"},
    {"ticker": "ABBV", "name": "AbbVie",            "sector": "healthcare"},
    {"ticker": "TMO",  "name": "Thermo Fisher",     "sector": "healthcare"},
    {"ticker": "JNJ",  "name": "Johnson & Johnson", "sector": "healthcare"},
    {"ticker": "PFE",  "name": "Pfizer",            "sector": "healthcare"},
    {"ticker": "MRK",  "name": "Merck",             "sector": "healthcare"},

    # Industrials (9)
    {"ticker": "CAT",  "name": "Caterpillar",       "sector": "industrials"},
    {"ticker": "DE",   "name": "Deere & Co",        "sector": "industrials"},
    {"ticker": "GE",   "name": "GE Aerospace",      "sector": "industrials"},
    {"ticker": "HON",  "name": "Honeywell",         "sector": "industrials"},
    {"ticker": "UNP",  "name": "Union Pacific",     "sector": "industrials"},
    {"ticker": "EMR",  "name": "Emerson Electric",  "sector": "industrials"},
    {"ticker": "ITW",  "name": "Illinois Tool Works","sector": "industrials"},
    {"ticker": "WM",   "name": "Waste Management",  "sector": "industrials"},
    {"ticker": "MMM",  "name": "3M Company",        "sector": "industrials"},

    # Consumer Discretionary (10)
    {"ticker": "COST", "name": "Costco",            "sector": "consumer_lc"},
    {"ticker": "HD",   "name": "Home Depot",        "sector": "consumer_lc"},
    {"ticker": "NKE",  "name": "Nike",              "sector": "consumer_lc"},
    {"ticker": "MCD",  "name": "McDonald's",        "sector": "consumer_lc"},
    {"ticker": "SBUX", "name": "Starbucks",         "sector": "consumer_lc"},
    {"ticker": "TJX",  "name": "TJX Companies",     "sector": "consumer_lc"},
    {"ticker": "LOW",  "name": "Lowe's",            "sector": "consumer_lc"},
    {"ticker": "TGT",  "name": "Target",            "sector": "consumer_lc"},
    {"ticker": "LULU", "name": "Lululemon",         "sector": "consumer_lc"},
    {"ticker": "YUM",  "name": "Yum! Brands",       "sector": "consumer_lc"},

    # Energy (7)
    {"ticker": "XOM",  "name": "Exxon Mobil",       "sector": "energy"},
    {"ticker": "CVX",  "name": "Chevron",           "sector": "energy"},
    {"ticker": "COP",  "name": "ConocoPhillips",    "sector": "energy"},
    {"ticker": "SLB",  "name": "Schlumberger",      "sector": "energy"},
    {"ticker": "EOG",  "name": "EOG Resources",     "sector": "energy"},
    {"ticker": "OXY",  "name": "Occidental Petro",  "sector": "energy"},
    {"ticker": "PSX",  "name": "Phillips 66",       "sector": "energy"},

    # Semiconductors (5)
    {"ticker": "TXN",  "name": "Texas Instruments",  "sector": "semi"},
    {"ticker": "QCOM", "name": "Qualcomm",           "sector": "semi"},
    {"ticker": "INTC", "name": "Intel",              "sector": "semi"},
    {"ticker": "ADI",  "name": "Analog Devices",     "sector": "semi"},
    {"ticker": "NXPI", "name": "NXP Semi",           "sector": "semi"},

    # REIT (6)
    {"ticker": "O",    "name": "Realty Income",      "sector": "reit"},
    {"ticker": "PLD",  "name": "Prologis",           "sector": "reit"},
    {"ticker": "AMT",  "name": "American Tower",     "sector": "reit"},
    {"ticker": "EQIX", "name": "Equinix",            "sector": "reit"},
    {"ticker": "SPG",  "name": "Simon Property",     "sector": "reit"},
    {"ticker": "PSA",  "name": "Public Storage",     "sector": "reit"},

    # Utilities (4)
    {"ticker": "NEE",  "name": "NextEra Energy",     "sector": "utilities"},
    {"ticker": "DUK",  "name": "Duke Energy",        "sector": "utilities"},
    {"ticker": "SO",   "name": "Southern Company",   "sector": "utilities"},
    {"ticker": "AEP",  "name": "American Electric",  "sector": "utilities"},

    # Defense (5)
    {"ticker": "LMT",  "name": "Lockheed Martin",    "sector": "defense"},
    {"ticker": "RTX",  "name": "RTX Corp",           "sector": "defense"},
    {"ticker": "NOC",  "name": "Northrop Grumman",   "sector": "defense"},
    {"ticker": "GD",   "name": "General Dynamics",   "sector": "defense"},
    {"ticker": "LHX",  "name": "L3Harris Tech",      "sector": "defense"},

    # Materials (5)
    {"ticker": "LIN",  "name": "Linde",              "sector": "materials"},
    {"ticker": "APD",  "name": "Air Products",       "sector": "materials"},
    {"ticker": "SHW",  "name": "Sherwin-Williams",   "sector": "materials"},
    {"ticker": "FCX",  "name": "Freeport-McMoRan",   "sector": "materials"},
    {"ticker": "NEM",  "name": "Newmont",            "sector": "materials"},

    # Consumer Staples (5)
    {"ticker": "PG",   "name": "Procter & Gamble",   "sector": "staples"},
    {"ticker": "KO",   "name": "Coca-Cola",          "sector": "staples"},
    {"ticker": "PEP",  "name": "PepsiCo",            "sector": "staples"},
    {"ticker": "CL",   "name": "Colgate-Palmolive",  "sector": "staples"},
    {"ticker": "MDLZ", "name": "Mondelez",           "sector": "staples"},

    # Telecom (3)
    {"ticker": "T",    "name": "AT&T",               "sector": "telecom"},
    {"ticker": "VZ",   "name": "Verizon",            "sector": "telecom"},
    {"ticker": "TMUS", "name": "T-Mobile",           "sector": "telecom"},

    # Medical Devices (5)
    {"ticker": "ISRG", "name": "Intuitive Surgical",  "sector": "med_device"},
    {"ticker": "SYK",  "name": "Stryker",             "sector": "med_device"},
    {"ticker": "MDT",  "name": "Medtronic",           "sector": "med_device"},
    {"ticker": "BSX",  "name": "Boston Scientific",   "sector": "med_device"},
    {"ticker": "EW",   "name": "Edwards Lifesciences","sector": "med_device"},

    # Life Sciences (4)
    {"ticker": "ABT",  "name": "Abbott Labs",         "sector": "healthcare"},
    {"ticker": "DHR",  "name": "Danaher",             "sector": "healthcare"},
    {"ticker": "ZTS",  "name": "Zoetis",              "sector": "healthcare"},
    {"ticker": "A",    "name": "Agilent Tech",        "sector": "healthcare"},

    # Transport (4)
    {"ticker": "UAL",  "name": "United Airlines",    "sector": "transport"},
    {"ticker": "DAL",  "name": "Delta Airlines",     "sector": "transport"},
    {"ticker": "FDX",  "name": "FedEx",              "sector": "transport"},
    {"ticker": "UPS",  "name": "United Parcel",      "sector": "transport"},
]


# === Mid-Cap & Growth Stocks (~380) ===

MIDCAP_STOCKS = [
    # ── Tech / Cybersecurity (20) ──
    {"ticker": "CRWD", "name": "CrowdStrike",       "sector": "tech"},
    {"ticker": "NET",  "name": "Cloudflare",        "sector": "tech"},
    {"ticker": "DDOG", "name": "Datadog",            "sector": "tech"},
    {"ticker": "MDB",  "name": "MongoDB",            "sector": "tech"},
    {"ticker": "BILL", "name": "Bill.com",           "sector": "tech"},
    {"ticker": "ZS",   "name": "Zscaler",            "sector": "tech"},
    {"ticker": "CFLT", "name": "Confluent",          "sector": "tech"},
    {"ticker": "GTLB", "name": "GitLab",             "sector": "tech", "listed_since": "2021-10"},
    {"ticker": "S",    "name": "SentinelOne",        "sector": "tech", "listed_since": "2021-06"},
    {"ticker": "IOT",  "name": "Samsara",            "sector": "tech", "listed_since": "2021-12"},
    {"ticker": "CYBR", "name": "CyberArk",           "sector": "tech"},
    {"ticker": "PANW", "name": "Palo Alto Networks", "sector": "tech"},
    {"ticker": "FTNT", "name": "Fortinet",           "sector": "tech"},
    {"ticker": "OKTA", "name": "Okta",               "sector": "tech"},
    {"ticker": "VRNS", "name": "Varonis Systems",    "sector": "tech"},
    {"ticker": "RPD",  "name": "Rapid7",             "sector": "tech"},
    {"ticker": "TENB", "name": "Tenable",            "sector": "tech"},
    {"ticker": "CHKP", "name": "Check Point",        "sector": "tech"},
    {"ticker": "QLYS", "name": "Qualys",             "sector": "tech"},
    {"ticker": "RDWR", "name": "Radware",            "sector": "tech"},

    # ── Semiconductors (18) ──
    {"ticker": "MPWR", "name": "Monolithic Power",   "sector": "semi"},
    {"ticker": "RMBS", "name": "Rambus",             "sector": "semi"},
    {"ticker": "ACLS", "name": "Axcelis Tech",       "sector": "semi"},
    {"ticker": "WOLF", "name": "Wolfspeed",          "sector": "semi"},
    {"ticker": "ALGM", "name": "Allegro Micro",      "sector": "semi", "listed_since": "2020-10"},
    {"ticker": "LSCC", "name": "Lattice Semi",       "sector": "semi"},
    {"ticker": "SMCI", "name": "Super Micro",        "sector": "semi"},
    {"ticker": "ARM",  "name": "Arm Holdings",       "sector": "semi", "listed_since": "2023-09"},
    {"ticker": "AVGO", "name": "Broadcom",           "sector": "semi"},
    {"ticker": "MRVL", "name": "Marvell Tech",       "sector": "semi"},
    {"ticker": "KLAC", "name": "KLA Corp",           "sector": "semi"},
    {"ticker": "AMAT", "name": "Applied Materials",  "sector": "semi"},
    {"ticker": "MU",   "name": "Micron",             "sector": "semi"},
    {"ticker": "ON",   "name": "ON Semiconductor",   "sector": "semi"},
    {"ticker": "GFS",  "name": "GlobalFoundries",    "sector": "semi", "listed_since": "2021-10"},
    {"ticker": "SWKS", "name": "Skyworks",           "sector": "semi"},
    {"ticker": "QRVO", "name": "Qorvo",              "sector": "semi"},
    {"ticker": "CRUS", "name": "Cirrus Logic",       "sector": "semi"},

    # ── Biotech / Pharma (20) ──
    {"ticker": "EXAS", "name": "Exact Sciences",    "sector": "bio"},
    {"ticker": "HALO", "name": "Halozyme",          "sector": "bio"},
    {"ticker": "PCVX", "name": "Vaxcyte",           "sector": "bio", "listed_since": "2020-06"},
    {"ticker": "IONS", "name": "Ionis Pharma",      "sector": "bio"},
    {"ticker": "GERN", "name": "Geron",             "sector": "bio"},
    {"ticker": "CRNX", "name": "Crinetics",         "sector": "bio"},
    {"ticker": "NUVB", "name": "Nuvation Bio",      "sector": "bio", "listed_since": "2021-01"},
    {"ticker": "MRNA", "name": "Moderna",           "sector": "bio"},
    {"ticker": "REGN", "name": "Regeneron",         "sector": "bio"},
    {"ticker": "VRTX", "name": "Vertex Pharma",     "sector": "bio"},
    {"ticker": "AMGN", "name": "Amgen",             "sector": "bio"},
    {"ticker": "GILD", "name": "Gilead Sciences",   "sector": "bio"},
    {"ticker": "BMY",  "name": "Bristol-Myers",     "sector": "bio"},
    {"ticker": "BIIB", "name": "Biogen",            "sector": "bio"},
    {"ticker": "NBIX", "name": "Neurocrine Bio",    "sector": "bio"},
    {"ticker": "ALNY", "name": "Alnylam Pharma",    "sector": "bio"},
    {"ticker": "INCY", "name": "Incyte",            "sector": "bio"},
    {"ticker": "BMRN", "name": "BioMarin",          "sector": "bio"},
    {"ticker": "SRPT", "name": "Sarepta Therapeut",  "sector": "bio"},
    {"ticker": "UTHR", "name": "United Therapeut",   "sector": "bio"},

    # ── Consumer / Retail (20) ──
    {"ticker": "DUOL", "name": "Duolingo",          "sector": "consumer", "listed_since": "2021-07"},
    {"ticker": "BROS", "name": "Dutch Bros",        "sector": "consumer", "listed_since": "2021-09"},
    {"ticker": "CAVA", "name": "Cava Group",        "sector": "consumer", "listed_since": "2023-06"},
    {"ticker": "ELF",  "name": "e.l.f. Beauty",     "sector": "consumer"},
    {"ticker": "CELH", "name": "Celsius",           "sector": "consumer"},
    {"ticker": "BIRK", "name": "Birkenstock",       "sector": "consumer", "listed_since": "2023-10"},
    {"ticker": "ONON", "name": "On Holding",        "sector": "consumer", "listed_since": "2021-09"},
    {"ticker": "UBER", "name": "Uber",              "sector": "consumer", "listed_since": "2019-05"},
    {"ticker": "DASH", "name": "DoorDash",          "sector": "consumer", "listed_since": "2020-12"},
    {"ticker": "DECK", "name": "Deckers Outdoor",   "sector": "consumer"},
    {"ticker": "CROX", "name": "Crocs",             "sector": "consumer"},
    {"ticker": "SHAK", "name": "Shake Shack",       "sector": "consumer"},
    {"ticker": "WING", "name": "Wingstop",          "sector": "consumer"},
    {"ticker": "TXRH", "name": "Texas Roadhouse",   "sector": "consumer"},
    {"ticker": "DPZ",  "name": "Domino's Pizza",    "sector": "consumer"},
    {"ticker": "CMG",  "name": "Chipotle",          "sector": "consumer"},
    {"ticker": "WFRD", "name": "Weatherford Intl",  "sector": "consumer"},
    {"ticker": "TPR",  "name": "Tapestry",          "sector": "consumer"},
    {"ticker": "RL",   "name": "Ralph Lauren",      "sector": "consumer"},
    {"ticker": "FIVE", "name": "Five Below",        "sector": "consumer"},

    # ── Industrial / Infrastructure (20) ──
    {"ticker": "TDW",  "name": "Tidewater",         "sector": "industrial"},
    {"ticker": "PRIM", "name": "Primoris",          "sector": "industrial"},
    {"ticker": "POWL", "name": "Powell Industries", "sector": "industrial"},
    {"ticker": "EME",  "name": "EMCOR Group",       "sector": "industrial"},
    {"ticker": "GVA",  "name": "Granite Constr",    "sector": "industrial"},
    {"ticker": "FIX",  "name": "Comfort Systems",   "sector": "industrial"},
    {"ticker": "URI",  "name": "United Rentals",    "sector": "industrial"},
    {"ticker": "FAST", "name": "Fastenal",          "sector": "industrial"},
    {"ticker": "WSC",  "name": "WillScot Mobile",   "sector": "industrial", "listed_since": "2020-06"},
    {"ticker": "BLDR", "name": "Builders FirstSrc", "sector": "industrial"},
    {"ticker": "GNRC", "name": "Generac",           "sector": "industrial"},
    {"ticker": "AAON", "name": "AAON Inc",          "sector": "industrial"},
    {"ticker": "NDSN", "name": "Nordson",           "sector": "industrial"},
    {"ticker": "RBC",  "name": "RBC Bearings",      "sector": "industrial"},
    {"ticker": "HUBB", "name": "Hubbell",           "sector": "industrial"},
    {"ticker": "TTEK", "name": "Tetra Tech",        "sector": "industrial"},
    {"ticker": "VMC",  "name": "Vulcan Materials",  "sector": "industrial"},
    {"ticker": "MLM",  "name": "Martin Marietta",   "sector": "industrial"},
    {"ticker": "PWR",  "name": "Quanta Services",   "sector": "industrial"},
    {"ticker": "UFPI", "name": "UFP Industries",    "sector": "industrial"},

    # ── Fintech / Payments (12) ──
    {"ticker": "AFRM", "name": "Affirm",            "sector": "fintech", "listed_since": "2021-01"},
    {"ticker": "UPST", "name": "Upstart",           "sector": "fintech", "listed_since": "2020-12"},
    {"ticker": "SOFI", "name": "SoFi Tech",         "sector": "fintech", "listed_since": "2021-06"},
    {"ticker": "HOOD", "name": "Robinhood",         "sector": "fintech", "listed_since": "2021-07"},
    {"ticker": "TOST", "name": "Toast",             "sector": "fintech", "listed_since": "2021-09"},
    {"ticker": "PYPL", "name": "PayPal",            "sector": "fintech"},
    {"ticker": "COIN", "name": "Coinbase",          "sector": "fintech", "listed_since": "2021-04"},
    {"ticker": "SQ",   "name": "Block (Square)",    "sector": "fintech"},
    {"ticker": "FIS",  "name": "Fidelity NIS",      "sector": "fintech"},
    {"ticker": "FISV", "name": "Fiserv",            "sector": "fintech"},
    {"ticker": "GPN",  "name": "Global Payments",   "sector": "fintech"},
    {"ticker": "WEX",  "name": "WEX Inc",           "sector": "fintech"},

    # ── Financial Services (10) ──
    {"ticker": "LPLA", "name": "LPL Financial",     "sector": "financials"},
    {"ticker": "IBKR", "name": "Interactive Brkrs",  "sector": "financials"},
    {"ticker": "MKTX", "name": "MarketAxess",       "sector": "financials"},
    {"ticker": "CBOE", "name": "Cboe Global",       "sector": "financials"},
    {"ticker": "NDAQ", "name": "Nasdaq Inc",        "sector": "financials"},
    {"ticker": "ICE",  "name": "Intercon Exchange",  "sector": "financials"},
    {"ticker": "CME",  "name": "CME Group",         "sector": "financials"},
    {"ticker": "MSCI", "name": "MSCI Inc",          "sector": "financials"},
    {"ticker": "SPGI", "name": "S&P Global",        "sector": "financials"},
    {"ticker": "MCO",  "name": "Moody's",           "sector": "financials"},

    # ── SaaS / Cloud (20) ──
    {"ticker": "PCOR", "name": "Procore Tech",      "sector": "saas", "listed_since": "2021-05"},
    {"ticker": "BRZE", "name": "Braze",             "sector": "saas", "listed_since": "2021-11"},
    {"ticker": "MNDY", "name": "Monday.com",        "sector": "saas", "listed_since": "2021-06"},
    {"ticker": "ESTC", "name": "Elastic",           "sector": "saas"},
    {"ticker": "DOCN", "name": "DigitalOcean",      "sector": "saas", "listed_since": "2021-03"},
    {"ticker": "TWLO", "name": "Twilio",            "sector": "saas"},
    {"ticker": "TTD",  "name": "The Trade Desk",    "sector": "saas"},
    {"ticker": "SHOP", "name": "Shopify",           "sector": "saas"},
    {"ticker": "PINS", "name": "Pinterest",         "sector": "saas", "listed_since": "2019-04"},
    {"ticker": "WDAY", "name": "Workday",           "sector": "saas"},
    {"ticker": "ZM",   "name": "Zoom Video",        "sector": "saas", "listed_since": "2019-04"},
    {"ticker": "HUBS", "name": "HubSpot",           "sector": "saas"},
    {"ticker": "VEEV", "name": "Veeva Systems",     "sector": "saas"},
    {"ticker": "TEAM", "name": "Atlassian",         "sector": "saas"},
    {"ticker": "APP",  "name": "AppLovin",          "sector": "saas", "listed_since": "2021-04"},
    {"ticker": "GRAB", "name": "Grab Holdings",     "sector": "saas", "listed_since": "2021-12"},
    {"ticker": "ZI",   "name": "ZoomInfo",          "sector": "saas", "listed_since": "2020-06"},
    {"ticker": "DOMO", "name": "Domo Inc",          "sector": "saas"},
    {"ticker": "SEMR", "name": "SEMrush",           "sector": "saas", "listed_since": "2021-03"},
    {"ticker": "FRSH", "name": "Freshworks",        "sector": "saas", "listed_since": "2021-09"},

    # ── Enterprise AI / Data (12) ──
    {"ticker": "ORCL", "name": "Oracle",            "sector": "ai"},
    {"ticker": "CRM",  "name": "Salesforce",        "sector": "ai"},
    {"ticker": "NOW",  "name": "ServiceNow",        "sector": "ai"},
    {"ticker": "INTU", "name": "Intuit",            "sector": "ai"},
    {"ticker": "SOUN", "name": "SoundHound AI",     "sector": "ai", "listed_since": "2022-04"},
    {"ticker": "PLTR", "name": "Palantir",          "sector": "ai", "listed_since": "2020-09"},
    {"ticker": "AI",   "name": "C3.ai",             "sector": "ai", "listed_since": "2020-12"},
    {"ticker": "BBAI", "name": "BigBear.ai",        "sector": "ai", "listed_since": "2021-12"},
    {"ticker": "PATH", "name": "UiPath",            "sector": "ai", "listed_since": "2021-04"},
    {"ticker": "SNOW", "name": "Snowflake",         "sector": "ai", "listed_since": "2020-09"},
    {"ticker": "TYL",  "name": "Tyler Tech",        "sector": "ai"},
    {"ticker": "CDNS", "name": "Cadence Design",    "sector": "ai"},

    # ── EDA / Design Software (4) ──
    {"ticker": "SNPS", "name": "Synopsys",          "sector": "tech"},
    {"ticker": "ANSS", "name": "ANSYS",             "sector": "tech"},
    {"ticker": "ADSK", "name": "Autodesk",          "sector": "tech"},
    {"ticker": "PTC",  "name": "PTC Inc",           "sector": "tech"},

    # ── Space / Frontier (5) ──
    {"ticker": "RKLB", "name": "Rocket Lab",        "sector": "space", "listed_since": "2021-08"},
    {"ticker": "ASTS", "name": "AST SpaceMobile",   "sector": "space", "listed_since": "2021-04"},
    {"ticker": "JOBY", "name": "Joby Aviation",     "sector": "space", "listed_since": "2021-08"},
    {"ticker": "LUNR", "name": "Intuitive Mach",    "sector": "space", "listed_since": "2023-02"},
    {"ticker": "RDW",  "name": "Redwire",           "sector": "space", "listed_since": "2021-09"},

    # ── China ADR (15) ──
    {"ticker": "PDD",  "name": "PDD Holdings",      "sector": "china"},
    {"ticker": "BABA", "name": "Alibaba",           "sector": "china"},
    {"ticker": "JD",   "name": "JD.com",            "sector": "china"},
    {"ticker": "BIDU", "name": "Baidu",             "sector": "china"},
    {"ticker": "NIO",  "name": "NIO",               "sector": "china"},
    {"ticker": "XPEV", "name": "XPeng",             "sector": "china"},
    {"ticker": "LI",   "name": "Li Auto",           "sector": "china", "listed_since": "2020-07"},
    {"ticker": "BILI", "name": "Bilibili",          "sector": "china"},
    {"ticker": "TME",  "name": "Tencent Music",     "sector": "china"},
    {"ticker": "FUTU", "name": "Futu Holdings",     "sector": "china", "listed_since": "2019-03"},
    {"ticker": "NTES", "name": "NetEase",           "sector": "china"},
    {"ticker": "TCOM", "name": "Trip.com",          "sector": "china"},
    {"ticker": "VNET", "name": "VNET Group",        "sector": "china"},
    {"ticker": "ZTO",  "name": "ZTO Express",       "sector": "china"},
    {"ticker": "TAL",  "name": "TAL Education",     "sector": "china"},

    # ── Clean Energy / EV (15) ──
    {"ticker": "ENPH", "name": "Enphase Energy",    "sector": "clean_energy"},
    {"ticker": "SEDG", "name": "SolarEdge",         "sector": "clean_energy"},
    {"ticker": "FSLR", "name": "First Solar",       "sector": "clean_energy"},
    {"ticker": "RUN",  "name": "Sunrun",            "sector": "clean_energy"},
    {"ticker": "PLUG", "name": "Plug Power",        "sector": "clean_energy"},
    {"ticker": "BLDP", "name": "Ballard Power",     "sector": "clean_energy"},
    {"ticker": "BE",   "name": "Bloom Energy",      "sector": "clean_energy"},
    {"ticker": "CHPT", "name": "ChargePoint",       "sector": "clean_energy", "listed_since": "2020-09"},
    {"ticker": "RIVN", "name": "Rivian",            "sector": "clean_energy", "listed_since": "2021-11"},
    {"ticker": "LCID", "name": "Lucid Group",       "sector": "clean_energy", "listed_since": "2021-07"},
    {"ticker": "QS",   "name": "QuantumScape",      "sector": "clean_energy", "listed_since": "2020-11"},
    {"ticker": "ARRY", "name": "Array Tech",        "sector": "clean_energy", "listed_since": "2020-10"},
    {"ticker": "NOVA", "name": "Sunnova Energy",    "sector": "clean_energy", "listed_since": "2019-07"},
    {"ticker": "STEM", "name": "Stem Inc",          "sector": "clean_energy", "listed_since": "2021-04"},
    {"ticker": "MAXN", "name": "Maxeon Solar",      "sector": "clean_energy", "listed_since": "2020-08"},

    # ── Media / Entertainment (12) ──
    {"ticker": "ROKU", "name": "Roku",              "sector": "media"},
    {"ticker": "DKNG", "name": "DraftKings",        "sector": "media", "listed_since": "2020-04"},
    {"ticker": "NFLX", "name": "Netflix",           "sector": "media"},
    {"ticker": "DIS",  "name": "Walt Disney",       "sector": "media"},
    {"ticker": "WBD",  "name": "Warner Bros Disc",  "sector": "media"},
    {"ticker": "PARA", "name": "Paramount Global",  "sector": "media"},
    {"ticker": "LYV",  "name": "Live Nation",       "sector": "media"},
    {"ticker": "SPOT", "name": "Spotify",           "sector": "media"},
    {"ticker": "RBLX", "name": "Roblox",            "sector": "media", "listed_since": "2021-03"},
    {"ticker": "U",    "name": "Unity Software",    "sector": "media", "listed_since": "2020-09"},
    {"ticker": "IMAX", "name": "IMAX Corp",         "sector": "media"},
    {"ticker": "MTCH", "name": "Match Group",       "sector": "media"},

    # ── Medical Devices (12) ──
    {"ticker": "PODD", "name": "Insulet",           "sector": "med_device"},
    {"ticker": "DXCM", "name": "DexCom",            "sector": "med_device"},
    {"ticker": "ALGN", "name": "Align Technology",  "sector": "med_device"},
    {"ticker": "GKOS", "name": "Glaukos",           "sector": "med_device"},
    {"ticker": "IRTC", "name": "iRhythm Tech",     "sector": "med_device"},
    {"ticker": "SILK", "name": "Silk Road Medical", "sector": "med_device"},
    {"ticker": "INSP", "name": "Inspire Medical",   "sector": "med_device", "listed_since": "2018-05"},
    {"ticker": "NVST", "name": "Envista Holdings",  "sector": "med_device", "listed_since": "2019-09"},
    {"ticker": "TNDM", "name": "Tandem Diabetes",   "sector": "med_device"},
    {"ticker": "NVCR", "name": "NovoCure",          "sector": "med_device"},
    {"ticker": "AXNX", "name": "Axonics",           "sector": "med_device"},
    {"ticker": "SWAV", "name": "ShockWave Med",     "sector": "med_device"},

    # ── Travel / Leisure (8) ──
    {"ticker": "ABNB", "name": "Airbnb",            "sector": "travel", "listed_since": "2020-12"},
    {"ticker": "BKNG", "name": "Booking Holdings",  "sector": "travel"},
    {"ticker": "EXPE", "name": "Expedia",           "sector": "travel"},
    {"ticker": "MAR",  "name": "Marriott Intl",     "sector": "travel"},
    {"ticker": "HLT",  "name": "Hilton",            "sector": "travel"},
    {"ticker": "RCL",  "name": "Royal Caribbean",   "sector": "travel"},
    {"ticker": "CCL",  "name": "Carnival",          "sector": "travel"},
    {"ticker": "NCLH", "name": "Norwegian Cruise",  "sector": "travel"},

    # ── REITs Mid-Cap (8) ──
    {"ticker": "INVH", "name": "Invitation Homes",  "sector": "reit", "listed_since": "2017-02"},
    {"ticker": "REXR", "name": "Rexford Ind",       "sector": "reit"},
    {"ticker": "SUI",  "name": "Sun Communities",   "sector": "reit"},
    {"ticker": "ELS",  "name": "Equity Lifestyle",  "sector": "reit"},
    {"ticker": "CUBE", "name": "CubeSmart",         "sector": "reit"},
    {"ticker": "WELL", "name": "Welltower",         "sector": "reit"},
    {"ticker": "VTR",  "name": "Ventas",            "sector": "reit"},
    {"ticker": "DLR",  "name": "Digital Realty",    "sector": "reit"},

    # ── Transport / Logistics (9) ──
    {"ticker": "XPO",  "name": "XPO Inc",           "sector": "transport"},
    {"ticker": "SAIA", "name": "Saia Inc",          "sector": "transport"},
    {"ticker": "ODFL", "name": "Old Dominion Frgt", "sector": "transport"},
    {"ticker": "JBHT", "name": "J.B. Hunt",         "sector": "transport"},
    {"ticker": "CHRW", "name": "C.H. Robinson",     "sector": "transport"},
    {"ticker": "LYFT", "name": "Lyft",              "sector": "transport", "listed_since": "2019-03"},
    {"ticker": "KNX",  "name": "Knight-Swift",      "sector": "transport"},
    {"ticker": "WERN", "name": "Werner Enterprises","sector": "transport"},
    {"ticker": "SNDR", "name": "Schneider National","sector": "transport"},

    # ── Energy Services (10) ──
    {"ticker": "HAL",  "name": "Halliburton",       "sector": "energy"},
    {"ticker": "BKR",  "name": "Baker Hughes",      "sector": "energy"},
    {"ticker": "RIG",  "name": "Transocean",        "sector": "energy"},
    {"ticker": "NOV",  "name": "NOV Inc",           "sector": "energy"},
    {"ticker": "LBRT", "name": "Liberty Energy",    "sector": "energy"},
    {"ticker": "DVN",  "name": "Devon Energy",      "sector": "energy"},
    {"ticker": "FANG", "name": "Diamondback Energy","sector": "energy"},
    {"ticker": "MPC",  "name": "Marathon Petroleum","sector": "energy"},
    {"ticker": "VLO",  "name": "Valero Energy",     "sector": "energy"},
    {"ticker": "PXD",  "name": "Pioneer Natural",   "sector": "energy"},

    # ── Gaming / E-commerce (10) ──
    {"ticker": "EA",   "name": "Electronic Arts",   "sector": "media"},
    {"ticker": "TTWO", "name": "Take-Two Interactive","sector": "media"},
    {"ticker": "ATVI", "name": "Activision Blizz",  "sector": "media"},
    {"ticker": "SE",   "name": "Sea Limited",       "sector": "media"},
    {"ticker": "MELI", "name": "MercadoLibre",      "sector": "media"},
    {"ticker": "ETSY", "name": "Etsy",              "sector": "media"},
    {"ticker": "W",    "name": "Wayfair",           "sector": "media"},
    {"ticker": "CHWY", "name": "Chewy",             "sector": "media", "listed_since": "2019-06"},
    {"ticker": "MNST", "name": "Monster Beverage",  "sector": "consumer"},
    {"ticker": "STZ",  "name": "Constellation Brds","sector": "consumer"},

    # ── Insurance (6) ──
    {"ticker": "KNSL", "name": "Kinsale Capital",   "sector": "financials"},
    {"ticker": "RLI",  "name": "RLI Corp",          "sector": "financials"},
    {"ticker": "RYAN", "name": "Ryan Specialty",    "sector": "financials", "listed_since": "2021-07"},
    {"ticker": "HIG",  "name": "Hartford Financial","sector": "financials"},
    {"ticker": "ALL",  "name": "Allstate",          "sector": "financials"},
    {"ticker": "PGR",  "name": "Progressive",       "sector": "financials"},

    # ── Healthcare Services (7) ──
    {"ticker": "HCA",  "name": "HCA Healthcare",    "sector": "healthcare"},
    {"ticker": "EHC",  "name": "Encompass Health",  "sector": "healthcare"},
    {"ticker": "DVA",  "name": "DaVita",            "sector": "healthcare"},
    {"ticker": "CNC",  "name": "Centene",           "sector": "healthcare"},
    {"ticker": "MOH",  "name": "Molina Healthcare", "sector": "healthcare"},
    {"ticker": "CI",   "name": "Cigna Group",       "sector": "healthcare"},
    {"ticker": "ELV",  "name": "Elevance Health",   "sector": "healthcare"},

    # ── Crypto / Blockchain (5) ──
    {"ticker": "MARA", "name": "Marathon Digital",  "sector": "fintech"},
    {"ticker": "RIOT", "name": "Riot Platforms",    "sector": "fintech"},
    {"ticker": "CLSK", "name": "CleanSpark",        "sector": "fintech"},
    {"ticker": "HUT",  "name": "Hut 8 Mining",     "sector": "fintech", "listed_since": "2021-06"},
    {"ticker": "CIFR", "name": "Cipher Mining",     "sector": "fintech", "listed_since": "2022-01"},

    # ── Robotics / Automation (5) ──
    {"ticker": "TER",  "name": "Teradyne",          "sector": "industrials"},
    {"ticker": "ROK",  "name": "Rockwell Autom",    "sector": "industrials"},
    {"ticker": "ZBRA", "name": "Zebra Tech",        "sector": "industrials"},
    {"ticker": "AZTA", "name": "Azenta",            "sector": "industrials"},
    {"ticker": "CGNX", "name": "Cognex",            "sector": "industrials"},

    # ── Cannabis / Specialty (4) ──
    {"ticker": "CTVA", "name": "Corteva",           "sector": "materials"},
    {"ticker": "AVTR", "name": "Avantor",           "sector": "materials"},
    {"ticker": "IFF",  "name": "Intl Flavors",      "sector": "materials"},
    {"ticker": "FMC",  "name": "FMC Corp",          "sector": "materials"},

    # ── Food & Beverage (8) ──
    {"ticker": "GIS",  "name": "General Mills",     "sector": "staples"},
    {"ticker": "K",    "name": "Kellanova",         "sector": "staples"},
    {"ticker": "HSY",  "name": "Hershey",           "sector": "staples"},
    {"ticker": "SJM",  "name": "J.M. Smucker",      "sector": "staples"},
    {"ticker": "CAG",  "name": "Conagra Brands",    "sector": "staples"},
    {"ticker": "KHC",  "name": "Kraft Heinz",       "sector": "staples"},
    {"ticker": "PM",   "name": "Philip Morris",     "sector": "staples"},
    {"ticker": "MO",   "name": "Altria Group",      "sector": "staples"},

    # ── Networking / Infra (6) ──
    {"ticker": "CSCO", "name": "Cisco Systems",     "sector": "tech"},
    {"ticker": "ANET", "name": "Arista Networks",   "sector": "tech"},
    {"ticker": "JNPR", "name": "Juniper Networks",  "sector": "tech"},
    {"ticker": "AKAM", "name": "Akamai Tech",       "sector": "tech"},
    {"ticker": "FFIV", "name": "F5 Inc",            "sector": "tech"},
    {"ticker": "HPE",  "name": "HP Enterprise",     "sector": "tech"},

    # ── Real Estate Services (4) ──
    {"ticker": "CBRE", "name": "CBRE Group",        "sector": "reit"},
    {"ticker": "JLL",  "name": "Jones Lang",        "sector": "reit"},
    {"ticker": "Z",    "name": "Zillow Group",      "sector": "reit"},
    {"ticker": "RDFN", "name": "Redfin",            "sector": "reit"},

    # ── Defense / Aerospace Mid (5) ──
    {"ticker": "HWM",  "name": "Howmet Aerospace",  "sector": "defense"},
    {"ticker": "TDG",  "name": "TransDigm",         "sector": "defense"},
    {"ticker": "HEI",  "name": "HEICO Corp",        "sector": "defense"},
    {"ticker": "AXON", "name": "Axon Enterprise",   "sector": "defense"},
    {"ticker": "LDOS", "name": "Leidos Holdings",   "sector": "defense"},

    # ── Software / IT Services (7) ──
    {"ticker": "SPLK", "name": "Splunk",            "sector": "tech"},
    {"ticker": "PAYC", "name": "Paycom Software",   "sector": "tech"},
    {"ticker": "PCTY", "name": "Paylocity",         "sector": "tech"},
    {"ticker": "WK",   "name": "Workiva",           "sector": "tech"},
    {"ticker": "MANH", "name": "Manhattan Assoc",   "sector": "tech"},
    {"ticker": "GWRE", "name": "Guidewire",         "sector": "tech"},
    {"ticker": "JAMF", "name": "Jamf Holding",      "sector": "tech", "listed_since": "2020-07"},

    # ── Additional Large-Cap Coverage (15) ──
    {"ticker": "WMT",  "name": "Walmart",           "sector": "consumer_lc"},
    {"ticker": "BRK-B","name": "Berkshire Hath B",  "sector": "financials"},
    {"ticker": "ADP",  "name": "ADP",               "sector": "tech"},
    {"ticker": "AMD",  "name": "AMD",               "sector": "semi"},
    {"ticker": "LRCX", "name": "Lam Research",      "sector": "semi"},
    {"ticker": "ASML", "name": "ASML Holdings",     "sector": "semi"},
    {"ticker": "ADBE", "name": "Adobe",             "sector": "tech"},
    {"ticker": "IBM",  "name": "IBM",               "sector": "tech"},
    {"ticker": "ACN",  "name": "Accenture",         "sector": "tech"},
    {"ticker": "FICO", "name": "Fair Isaac",        "sector": "tech"},
    {"ticker": "WYNN", "name": "Wynn Resorts",       "sector": "travel"},
    {"ticker": "CCI",  "name": "Crown Castle",      "sector": "reit"},
    {"ticker": "VICI", "name": "VICI Properties",   "sector": "reit"},
    {"ticker": "ARE",  "name": "Alexandria RE",     "sector": "reit"},
    {"ticker": "HST",  "name": "Host Hotels",       "sector": "reit"},

    # ── Additional Mid-Cap Growth (22) ──
    {"ticker": "TMDX", "name": "TransMedics",       "sector": "med_device", "listed_since": "2019-05"},
    {"ticker": "XRAY", "name": "Dentsply Sirona",   "sector": "med_device"},
    {"ticker": "HOLX", "name": "Hologic",           "sector": "med_device"},
    {"ticker": "TECH", "name": "Bio-Techne",        "sector": "bio"},
    {"ticker": "ILMN", "name": "Illumina",          "sector": "bio"},
    {"ticker": "DOCS", "name": "Doximity",          "sector": "healthcare", "listed_since": "2021-06"},
    {"ticker": "OSCR", "name": "Oscar Health",      "sector": "healthcare", "listed_since": "2021-03"},
    {"ticker": "GLBE", "name": "Global-E Online",   "sector": "saas", "listed_since": "2021-05"},
    {"ticker": "MTTR", "name": "Matterport",        "sector": "tech", "listed_since": "2021-07"},
    {"ticker": "IONQ", "name": "IonQ",              "sector": "tech", "listed_since": "2021-10"},
    {"ticker": "RGTI", "name": "Rigetti Computing", "sector": "tech", "listed_since": "2022-03"},
    {"ticker": "VRT",  "name": "Vertiv Holdings",   "sector": "industrial", "listed_since": "2020-02"},
    {"ticker": "TNET", "name": "TriNet Group",      "sector": "tech"},
    {"ticker": "RELY", "name": "Remitly Global",    "sector": "fintech", "listed_since": "2021-09"},
    {"ticker": "FOUR", "name": "Shift4 Payments",   "sector": "fintech", "listed_since": "2020-06"},
    {"ticker": "TBBK", "name": "Bancorp",           "sector": "financials"},
    {"ticker": "VIRT", "name": "Virtu Financial",   "sector": "financials"},
    {"ticker": "PAYO", "name": "Payoneer",          "sector": "fintech", "listed_since": "2021-06"},
    {"ticker": "LNTH", "name": "Lantheus",          "sector": "bio"},
    {"ticker": "MEDP", "name": "Medpace Holdings",  "sector": "healthcare"},
    {"ticker": "ICLR", "name": "ICON Plc",          "sector": "healthcare"},
    {"ticker": "CRL",  "name": "Charles River Lab", "sector": "healthcare"},

    # ── Additional Sectors Deepening (25) ──
    {"ticker": "GRMN", "name": "Garmin",            "sector": "tech"},
    {"ticker": "KEYS", "name": "Keysight Tech",     "sector": "tech"},
    {"ticker": "TRMB", "name": "Trimble",           "sector": "tech"},
    {"ticker": "BR",   "name": "Broadridge Fin",    "sector": "fintech"},
    {"ticker": "FLT",  "name": "Corpay",            "sector": "fintech"},
    {"ticker": "CLH",  "name": "Clean Harbors",     "sector": "industrial"},
    {"ticker": "CSWI", "name": "CSW Industrials",   "sector": "industrial"},
    {"ticker": "AIT",  "name": "Applied Indust",    "sector": "industrial"},
    {"ticker": "SPSC", "name": "SPS Commerce",      "sector": "saas"},
    {"ticker": "AZEK", "name": "AZEK Company",      "sector": "industrial", "listed_since": "2020-06"},
    {"ticker": "TREX", "name": "Trex Company",      "sector": "industrial"},
    {"ticker": "POOL", "name": "Pool Corp",         "sector": "consumer"},
    {"ticker": "WSO",  "name": "Watsco",            "sector": "industrial"},
    {"ticker": "FLEX", "name": "Flex Ltd",           "sector": "tech"},
    {"ticker": "SANM", "name": "Sanmina",           "sector": "tech"},
    {"ticker": "CIEN", "name": "Ciena Corp",        "sector": "tech"},
    {"ticker": "CALX", "name": "Calix",             "sector": "tech"},
    {"ticker": "LITE", "name": "Lumentum",          "sector": "tech"},
    {"ticker": "PI",   "name": "Impinj",            "sector": "tech"},
    {"ticker": "OLED", "name": "Universal Display", "sector": "tech"},
    {"ticker": "DV",   "name": "DoubleVerify",      "sector": "saas", "listed_since": "2021-04"},
    {"ticker": "CWAN", "name": "Clearwater Analyt",  "sector": "fintech", "listed_since": "2021-09"},
    {"ticker": "SMTC", "name": "Semtech",           "sector": "semi"},
    {"ticker": "PSTG", "name": "Pure Storage",      "sector": "tech"},
    {"ticker": "NTAP", "name": "NetApp",            "sector": "tech"},
]


def get_all_tickers() -> list[str]:
    """Get all tickers from all pools"""
    tickers = []
    for item in OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + INVERSE_ETFS:
        tickers.append(item["ticker"])
    return tickers


def get_offensive_tickers() -> list[str]:
    """Get offensive ETF + large-cap + midcap stock tickers (for scoring in bull regime)"""
    tickers = []
    for item in OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS:
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
    for item in OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + INVERSE_ETFS:
        if item["ticker"] == ticker:
            return item
    return None
