"""
StockQueen V2 - Rotation Watchlist Configuration
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
    TOP_N: int = 6                  # locked via WF v4 (was 4, 4/6 windows chose 6)
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
    ATR_STOP_MULTIPLIER: float = 1.5    # stop = entry - 1.5*ATR (locked via WF)
    ATR_TARGET_MULTIPLIER: float = 3.0  # target = entry + 3*ATR

    # === Trailing Stop ===
    TRAILING_STOP_ENABLED: bool = True
    TRAILING_STOP_ATR_MULT: float = 1.5   # trailing distance = ATR * N
    TRAILING_ACTIVATE_ATR: float = 0.5    # activate after profit >= N * ATR (locked via WF)

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

# Inverse ETFs - used in bear regime for short exposure
INVERSE_ETFS = [
    {"ticker": "SH",   "name": "Short S&P500",      "asset_type": "inverse_etf"},
    {"ticker": "PSQ",  "name": "Short QQQ",          "asset_type": "inverse_etf"},
    {"ticker": "RWM",  "name": "Short Russell2000",  "asset_type": "inverse_etf"},
    {"ticker": "DOG",  "name": "Short Dow30",        "asset_type": "inverse_etf"},
]

# Mapping: inverse ETF → underlying index ticker (for bear regime scoring)
INVERSE_ETF_INDEX_MAP = {
    "SH":  "SPY",   # Short S&P 500
    "PSQ": "QQQ",   # Short Nasdaq 100
    "RWM": "IWM",   # Short Russell 2000
    "DOG": "DIA",   # Short Dow 30
}


# === Large-Cap Blue Chips (25) ===
# All pre-2015 IPO, no survivorship bias risk

LARGECAP_STOCKS = [
    # Mega-Cap Tech
    {"ticker": "AAPL", "name": "Apple",              "sector": "mega_tech"},
    {"ticker": "MSFT", "name": "Microsoft",          "sector": "mega_tech"},
    {"ticker": "NVDA", "name": "NVIDIA",             "sector": "mega_tech"},
    {"ticker": "AMZN", "name": "Amazon",             "sector": "mega_tech"},
    {"ticker": "META", "name": "Meta Platforms",     "sector": "mega_tech"},
    {"ticker": "GOOG", "name": "Alphabet",           "sector": "mega_tech"},
    {"ticker": "TSLA", "name": "Tesla",              "sector": "mega_tech"},

    # Financials
    {"ticker": "JPM",  "name": "JPMorgan Chase",    "sector": "financials"},
    {"ticker": "GS",   "name": "Goldman Sachs",     "sector": "financials"},
    {"ticker": "V",    "name": "Visa",              "sector": "financials"},
    {"ticker": "MA",   "name": "Mastercard",        "sector": "financials"},
    {"ticker": "BLK",  "name": "BlackRock",         "sector": "financials"},

    # Healthcare
    {"ticker": "UNH",  "name": "UnitedHealth",      "sector": "healthcare"},
    {"ticker": "LLY",  "name": "Eli Lilly",         "sector": "healthcare"},
    {"ticker": "ABBV", "name": "AbbVie",            "sector": "healthcare"},
    {"ticker": "TMO",  "name": "Thermo Fisher",     "sector": "healthcare"},

    # Industrials
    {"ticker": "CAT",  "name": "Caterpillar",       "sector": "industrials"},
    {"ticker": "DE",   "name": "Deere & Co",        "sector": "industrials"},
    {"ticker": "GE",   "name": "GE Aerospace",      "sector": "industrials"},
    {"ticker": "HON",  "name": "Honeywell",         "sector": "industrials"},

    # Consumer
    {"ticker": "COST", "name": "Costco",            "sector": "consumer_lc"},
    {"ticker": "HD",   "name": "Home Depot",        "sector": "consumer_lc"},
    {"ticker": "NKE",  "name": "Nike",              "sector": "consumer_lc"},

    # Energy
    {"ticker": "XOM",  "name": "Exxon Mobil",       "sector": "energy"},
    {"ticker": "CVX",  "name": "Chevron",           "sector": "energy"},

    # REIT
    {"ticker": "O",    "name": "Realty Income",      "sector": "reit"},
    {"ticker": "PLD",  "name": "Prologis",           "sector": "reit"},
    {"ticker": "AMT",  "name": "American Tower",     "sector": "reit"},
    {"ticker": "EQIX", "name": "Equinix",            "sector": "reit"},
    {"ticker": "SPG",  "name": "Simon Property",     "sector": "reit"},
    {"ticker": "PSA",  "name": "Public Storage",     "sector": "reit"},

    # Utilities
    {"ticker": "NEE",  "name": "NextEra Energy",     "sector": "utilities"},
    {"ticker": "DUK",  "name": "Duke Energy",        "sector": "utilities"},
    {"ticker": "SO",   "name": "Southern Company",   "sector": "utilities"},
    {"ticker": "AEP",  "name": "American Electric",  "sector": "utilities"},

    # Defense
    {"ticker": "LMT",  "name": "Lockheed Martin",    "sector": "defense"},
    {"ticker": "RTX",  "name": "RTX Corp",           "sector": "defense"},
    {"ticker": "NOC",  "name": "Northrop Grumman",   "sector": "defense"},
    {"ticker": "GD",   "name": "General Dynamics",   "sector": "defense"},
    {"ticker": "LHX",  "name": "L3Harris Tech",      "sector": "defense"},

    # Materials
    {"ticker": "LIN",  "name": "Linde",              "sector": "materials"},
    {"ticker": "APD",  "name": "Air Products",       "sector": "materials"},
    {"ticker": "SHW",  "name": "Sherwin-Williams",   "sector": "materials"},
    {"ticker": "FCX",  "name": "Freeport-McMoRan",   "sector": "materials"},
    {"ticker": "NEM",  "name": "Newmont",            "sector": "materials"},

    # Consumer Staples
    {"ticker": "PG",   "name": "Procter & Gamble",   "sector": "staples"},
    {"ticker": "KO",   "name": "Coca-Cola",          "sector": "staples"},
    {"ticker": "PEP",  "name": "PepsiCo",            "sector": "staples"},
    {"ticker": "CL",   "name": "Colgate-Palmolive",  "sector": "staples"},
    {"ticker": "MDLZ", "name": "Mondelez",           "sector": "staples"},

    # Telecom
    {"ticker": "T",    "name": "AT&T",               "sector": "telecom"},
    {"ticker": "VZ",   "name": "Verizon",            "sector": "telecom"},
    {"ticker": "TMUS", "name": "T-Mobile",           "sector": "telecom"},

    # Medical Devices
    {"ticker": "ISRG", "name": "Intuitive Surgical",  "sector": "med_device"},
    {"ticker": "SYK",  "name": "Stryker",             "sector": "med_device"},
    {"ticker": "MDT",  "name": "Medtronic",           "sector": "med_device"},
    {"ticker": "BSX",  "name": "Boston Scientific",   "sector": "med_device"},
    {"ticker": "EW",   "name": "Edwards Lifesciences","sector": "med_device"},

    # Transport
    {"ticker": "UAL",  "name": "United Airlines",    "sector": "transport"},
    {"ticker": "DAL",  "name": "Delta Airlines",     "sector": "transport"},
    {"ticker": "FDX",  "name": "FedEx",              "sector": "transport"},
    {"ticker": "UPS",  "name": "United Parcel",      "sector": "transport"},
]


# === Mid-Cap US Stocks ($500M - $20B) ===

MIDCAP_STOCKS = [
    # -- Tech Growth (14) --
    {"ticker": "CRWD", "name": "CrowdStrike",    "sector": "tech"},
    {"ticker": "NET",  "name": "Cloudflare",     "sector": "tech"},
    {"ticker": "DDOG", "name": "Datadog",         "sector": "tech"},
    {"ticker": "MDB",  "name": "MongoDB",         "sector": "tech"},
    {"ticker": "BILL", "name": "Bill.com",        "sector": "tech"},
    {"ticker": "ZS",   "name": "Zscaler",         "sector": "tech"},
    {"ticker": "CFLT", "name": "Confluent",       "sector": "tech"},
    {"ticker": "GTLB", "name": "GitLab",          "sector": "tech", "listed_since": "2021-10"},
    {"ticker": "S",    "name": "SentinelOne",     "sector": "tech", "listed_since": "2021-06"},
    {"ticker": "IOT",  "name": "Samsara",         "sector": "tech", "listed_since": "2021-12"},
    {"ticker": "CYBR", "name": "CyberArk",        "sector": "tech"},
    {"ticker": "PANW", "name": "Palo Alto Networks","sector": "tech"},
    {"ticker": "FTNT", "name": "Fortinet",        "sector": "tech"},
    {"ticker": "OKTA", "name": "Okta",            "sector": "tech"},

    # -- Semiconductors (8) --
    {"ticker": "MPWR", "name": "Monolithic Power", "sector": "semi"},
    {"ticker": "RMBS", "name": "Rambus",           "sector": "semi"},
    {"ticker": "ACLS", "name": "Axcelis Tech",     "sector": "semi"},
    {"ticker": "WOLF", "name": "Wolfspeed",        "sector": "semi"},
    {"ticker": "ALGM", "name": "Allegro Micro",    "sector": "semi", "listed_since": "2020-10"},
    {"ticker": "LSCC", "name": "Lattice Semi",     "sector": "semi"},
    {"ticker": "SMCI", "name": "Super Micro",      "sector": "semi"},
    {"ticker": "ARM",  "name": "Arm Holdings",     "sector": "semi", "listed_since": "2023-09"},

    # -- Biotech/Pharma (10) --
    {"ticker": "EXAS", "name": "Exact Sciences",  "sector": "bio"},
    {"ticker": "HALO", "name": "Halozyme",        "sector": "bio"},
    {"ticker": "PCVX", "name": "Vaxcyte",         "sector": "bio", "listed_since": "2020-06"},
    {"ticker": "IONS", "name": "Ionis Pharma",    "sector": "bio"},
    {"ticker": "GERN", "name": "Geron",           "sector": "bio"},
    {"ticker": "CRNX", "name": "Crinetics",       "sector": "bio"},
    {"ticker": "NUVB", "name": "Nuvation Bio",    "sector": "bio", "listed_since": "2021-01"},
    {"ticker": "MRNA", "name": "Moderna",         "sector": "bio"},
    {"ticker": "REGN", "name": "Regeneron",       "sector": "bio"},
    {"ticker": "VRTX", "name": "Vertex Pharma",   "sector": "bio"},

    # -- Consumer/Retail (9) --
    {"ticker": "DUOL", "name": "Duolingo",        "sector": "consumer", "listed_since": "2021-07"},
    {"ticker": "BROS", "name": "Dutch Bros",      "sector": "consumer", "listed_since": "2021-09"},
    {"ticker": "CAVA", "name": "Cava Group",      "sector": "consumer", "listed_since": "2023-06"},
    {"ticker": "ELF",  "name": "e.l.f. Beauty",   "sector": "consumer"},
    {"ticker": "CELH", "name": "Celsius",         "sector": "consumer"},
    {"ticker": "BIRK", "name": "Birkenstock",     "sector": "consumer", "listed_since": "2023-10"},
    {"ticker": "ONON", "name": "On Holding",      "sector": "consumer", "listed_since": "2021-09"},
    {"ticker": "UBER", "name": "Uber",            "sector": "consumer", "listed_since": "2019-05"},
    {"ticker": "DASH", "name": "DoorDash",        "sector": "consumer", "listed_since": "2020-12"},

    # -- Industrial/Energy (6) --
    {"ticker": "TDW",  "name": "Tidewater",       "sector": "industrial"},
    {"ticker": "PRIM", "name": "Primoris",        "sector": "industrial"},
    {"ticker": "POWL", "name": "Powell Industries","sector": "industrial"},
    {"ticker": "EME",  "name": "EMCOR Group",     "sector": "industrial"},
    {"ticker": "GVA",  "name": "Granite Constr",  "sector": "industrial"},
    {"ticker": "FIX",  "name": "Comfort Systems", "sector": "industrial"},

    # -- Fintech (7) --
    {"ticker": "AFRM", "name": "Affirm",          "sector": "fintech", "listed_since": "2021-01"},
    {"ticker": "UPST", "name": "Upstart",         "sector": "fintech", "listed_since": "2020-12"},
    {"ticker": "SOFI", "name": "SoFi Tech",       "sector": "fintech", "listed_since": "2021-06"},
    {"ticker": "HOOD", "name": "Robinhood",       "sector": "fintech", "listed_since": "2021-07"},
    {"ticker": "TOST", "name": "Toast",           "sector": "fintech", "listed_since": "2021-09"},
    {"ticker": "PYPL", "name": "PayPal",          "sector": "fintech"},
    {"ticker": "COIN", "name": "Coinbase",        "sector": "fintech", "listed_since": "2021-04"},

    # -- SaaS/Cloud (9) --
    {"ticker": "PCOR", "name": "Procore Tech",    "sector": "saas", "listed_since": "2021-05"},
    {"ticker": "BRZE", "name": "Braze",           "sector": "saas", "listed_since": "2021-11"},
    {"ticker": "MNDY", "name": "Monday.com",      "sector": "saas", "listed_since": "2021-06"},
    {"ticker": "ESTC", "name": "Elastic",         "sector": "saas"},
    {"ticker": "DOCN", "name": "DigitalOcean",    "sector": "saas", "listed_since": "2021-03"},
    {"ticker": "TWLO", "name": "Twilio",          "sector": "saas"},
    {"ticker": "TTD",  "name": "The Trade Desk",  "sector": "saas"},
    {"ticker": "SHOP", "name": "Shopify",         "sector": "saas"},
    {"ticker": "PINS", "name": "Pinterest",       "sector": "saas", "listed_since": "2019-04"},

    # -- Space/Frontier (5) --
    {"ticker": "RKLB", "name": "Rocket Lab",      "sector": "space", "listed_since": "2021-08"},
    {"ticker": "ASTS", "name": "AST SpaceMobile", "sector": "space", "listed_since": "2021-04"},
    {"ticker": "JOBY", "name": "Joby Aviation",   "sector": "space", "listed_since": "2021-08"},
    {"ticker": "LUNR", "name": "Intuitive Mach",  "sector": "space", "listed_since": "2023-02"},
    {"ticker": "RDW",  "name": "Redwire",         "sector": "space", "listed_since": "2021-09"},

    # -- China ADR (10) --
    {"ticker": "PDD",  "name": "PDD Holdings",    "sector": "china"},
    {"ticker": "BABA", "name": "Alibaba",         "sector": "china"},
    {"ticker": "JD",   "name": "JD.com",          "sector": "china"},
    {"ticker": "BIDU", "name": "Baidu",           "sector": "china"},
    {"ticker": "NIO",  "name": "NIO",             "sector": "china"},
    {"ticker": "XPEV", "name": "XPeng",           "sector": "china"},
    {"ticker": "LI",   "name": "Li Auto",         "sector": "china", "listed_since": "2020-07"},
    {"ticker": "BILI", "name": "Bilibili",        "sector": "china"},
    {"ticker": "TME",  "name": "Tencent Music",   "sector": "china"},
    {"ticker": "FUTU", "name": "Futu Holdings",   "sector": "china", "listed_since": "2019-03"},

    # -- AI/Data (5) --
    {"ticker": "PLTR", "name": "Palantir",        "sector": "ai", "listed_since": "2020-09"},
    {"ticker": "AI",   "name": "C3.ai",           "sector": "ai", "listed_since": "2020-12"},
    {"ticker": "BBAI", "name": "BigBear.ai",      "sector": "ai", "listed_since": "2021-12"},
    {"ticker": "PATH", "name": "UiPath",          "sector": "ai", "listed_since": "2021-04"},
    {"ticker": "SNOW", "name": "Snowflake",       "sector": "ai", "listed_since": "2020-09"},

    # -- Clean Energy (4) --
    {"ticker": "ENPH", "name": "Enphase Energy",  "sector": "clean_energy"},
    {"ticker": "SEDG", "name": "SolarEdge",       "sector": "clean_energy"},
    {"ticker": "FSLR", "name": "First Solar",     "sector": "clean_energy"},
    {"ticker": "RUN",  "name": "Sunrun",          "sector": "clean_energy"},

    # -- Media/Entertainment (2) --
    {"ticker": "ROKU", "name": "Roku",            "sector": "media"},
    {"ticker": "DKNG", "name": "DraftKings",      "sector": "media", "listed_since": "2020-04"},

    # -- Travel (1) --
    {"ticker": "ABNB", "name": "Airbnb",          "sector": "travel", "listed_since": "2020-12"},

    # -- Fintech extra (1) --
    {"ticker": "SQ",   "name": "Block (Square)",  "sector": "fintech"},

    # -- Semi deepening (5) --
    {"ticker": "AVGO", "name": "Broadcom",        "sector": "semi"},
    {"ticker": "MRVL", "name": "Marvell Tech",    "sector": "semi"},
    {"ticker": "KLAC", "name": "KLA Corp",        "sector": "semi"},
    {"ticker": "AMAT", "name": "Applied Materials","sector": "semi"},
    {"ticker": "MU",   "name": "Micron",           "sector": "semi"},

    # -- Cybersec deepening (3) --
    {"ticker": "VRNS", "name": "Varonis Systems",  "sector": "tech"},
    {"ticker": "RPD",  "name": "Rapid7",           "sector": "tech"},
    {"ticker": "TENB", "name": "Tenable",          "sector": "tech"},

    # -- Enterprise AI / SaaS (5) --
    {"ticker": "ORCL", "name": "Oracle",           "sector": "ai"},
    {"ticker": "CRM",  "name": "Salesforce",       "sector": "ai"},
    {"ticker": "NOW",  "name": "ServiceNow",       "sector": "ai"},
    {"ticker": "INTU", "name": "Intuit",           "sector": "ai"},
    {"ticker": "SOUN", "name": "SoundHound AI",    "sector": "ai", "listed_since": "2022-04"},

    # -- Large Biotech (4) --
    {"ticker": "AMGN", "name": "Amgen",            "sector": "bio"},
    {"ticker": "GILD", "name": "Gilead Sciences",  "sector": "bio"},
    {"ticker": "BMY",  "name": "Bristol-Myers",    "sector": "bio"},
    {"ticker": "BIIB", "name": "Biogen",           "sector": "bio"},

    # -- Clean Energy deepening (4) --
    {"ticker": "PLUG", "name": "Plug Power",       "sector": "clean_energy"},
    {"ticker": "BLDP", "name": "Ballard Power",    "sector": "clean_energy"},
    {"ticker": "BE",   "name": "Bloom Energy",     "sector": "clean_energy"},
    {"ticker": "CHPT", "name": "ChargePoint",      "sector": "clean_energy", "listed_since": "2020-09"},
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
