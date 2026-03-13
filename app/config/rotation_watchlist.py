"""
StockQueen V2 - Rotation Watchlist Configuration
ETF + mid-cap US stock candidate pools for momentum rotation strategy
"""


class RotationConfig:
    """Momentum rotation strategy parameters"""

    # === Scoring weights ===
    WEIGHT_1W: float = 0.20
    WEIGHT_1M: float = 0.40
    WEIGHT_3M: float = 0.40
    VOL_PENALTY: float = 0.50       # annualized vol penalty multiplier
    TREND_BONUS: float = 2.0        # bonus if close > MA20
    HOLDING_BONUS: float = 1.5      # bonus for already-held tickers (reduces turnover)

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
    # Tech Growth
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

    # Semiconductors
    {"ticker": "MPWR", "name": "Monolithic Power", "sector": "semi"},
    {"ticker": "RMBS", "name": "Rambus",           "sector": "semi"},
    {"ticker": "ACLS", "name": "Axcelis Tech",     "sector": "semi"},
    {"ticker": "WOLF", "name": "Wolfspeed",        "sector": "semi"},
    {"ticker": "ALGM", "name": "Allegro Micro",    "sector": "semi"},
    {"ticker": "LSCC", "name": "Lattice Semi",     "sector": "semi"},

    # Biotech/Pharma
    {"ticker": "EXAS", "name": "Exact Sciences",  "sector": "bio"},
    {"ticker": "HALO", "name": "Halozyme",        "sector": "bio"},
    {"ticker": "PCVX", "name": "Vaxcyte",         "sector": "bio"},
    {"ticker": "IONS", "name": "Ionis Pharma",    "sector": "bio"},
    {"ticker": "GERN", "name": "Geron",           "sector": "bio"},
    {"ticker": "CRNX", "name": "Crinetics",       "sector": "bio"},
    {"ticker": "NUVB", "name": "Nuvation Bio",    "sector": "bio"},

    # Consumer/Retail
    {"ticker": "DUOL", "name": "Duolingo",        "sector": "consumer"},
    {"ticker": "BROS", "name": "Dutch Bros",      "sector": "consumer"},
    {"ticker": "CAVA", "name": "Cava Group",      "sector": "consumer"},
    {"ticker": "ELF",  "name": "e.l.f. Beauty",   "sector": "consumer"},
    {"ticker": "CELH", "name": "Celsius",         "sector": "consumer"},
    {"ticker": "BIRK", "name": "Birkenstock",     "sector": "consumer"},

    # Industrial/Energy
    {"ticker": "TDW",  "name": "Tidewater",       "sector": "industrial"},
    {"ticker": "PRIM", "name": "Primoris",        "sector": "industrial"},
    {"ticker": "POWL", "name": "Powell Industries","sector": "industrial"},
    {"ticker": "EME",  "name": "EMCOR Group",     "sector": "industrial"},
    {"ticker": "GVA",  "name": "Granite Constr",  "sector": "industrial"},
    {"ticker": "FIX",  "name": "Comfort Systems", "sector": "industrial"},

    # Fintech
    {"ticker": "AFRM", "name": "Affirm",          "sector": "fintech"},
    {"ticker": "UPST", "name": "Upstart",         "sector": "fintech"},
    {"ticker": "SOFI", "name": "SoFi Tech",       "sector": "fintech"},
    {"ticker": "HOOD", "name": "Robinhood",       "sector": "fintech"},
    {"ticker": "TOST", "name": "Toast",           "sector": "fintech"},

    # SaaS/Cloud
    {"ticker": "PCOR", "name": "Procore Tech",    "sector": "saas"},
    {"ticker": "BRZE", "name": "Braze",           "sector": "saas"},
    {"ticker": "MNDY", "name": "Monday.com",      "sector": "saas"},
    {"ticker": "ESTC", "name": "Elastic",         "sector": "saas"},
    {"ticker": "DOCN", "name": "DigitalOcean",    "sector": "saas"},

    # Space/Frontier
    {"ticker": "RKLB", "name": "Rocket Lab",      "sector": "space"},
    {"ticker": "ASTS", "name": "AST SpaceMobile", "sector": "space"},
    {"ticker": "JOBY", "name": "Joby Aviation",   "sector": "space"},
    {"ticker": "LUNR", "name": "Intuitive Mach",  "sector": "space"},
    {"ticker": "RDW",  "name": "Redwire",         "sector": "space"},
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
