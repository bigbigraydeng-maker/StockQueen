"""
StockQueen - S&P 100 Watchlist
均值回归策略 & 事件驱动策略的候选股票池。
标普100成分股：高流动性、机构持仓充足、均值修复动力强。
"""

# ============================================================
# 标普100成分股池（按板块分组）
# ============================================================

SP100_TECH = [
    {"ticker": "AAPL",  "name": "Apple",              "sector": "tech"},
    {"ticker": "MSFT",  "name": "Microsoft",           "sector": "tech"},
    {"ticker": "NVDA",  "name": "NVIDIA",              "sector": "tech"},
    {"ticker": "GOOGL", "name": "Alphabet A",          "sector": "tech"},
    {"ticker": "META",  "name": "Meta",                "sector": "tech"},
    {"ticker": "AVGO",  "name": "Broadcom",            "sector": "tech"},
    {"ticker": "INTC",  "name": "Intel",               "sector": "tech"},
    {"ticker": "CSCO",  "name": "Cisco",               "sector": "tech"},
    {"ticker": "QCOM",  "name": "Qualcomm",            "sector": "tech"},
    {"ticker": "TXN",   "name": "Texas Instruments",   "sector": "tech"},
    {"ticker": "ACN",   "name": "Accenture",           "sector": "tech"},
    {"ticker": "IBM",   "name": "IBM",                 "sector": "tech"},
    {"ticker": "ORCL",  "name": "Oracle",              "sector": "tech"},
    {"ticker": "ADI",   "name": "Analog Devices",      "sector": "tech"},
    {"ticker": "AMAT",  "name": "Applied Materials",   "sector": "tech"},
]

SP100_CONSUMER = [
    {"ticker": "AMZN",  "name": "Amazon",              "sector": "consumer"},
    {"ticker": "TSLA",  "name": "Tesla",               "sector": "consumer"},
    {"ticker": "HD",    "name": "Home Depot",          "sector": "consumer"},
    {"ticker": "MCD",   "name": "McDonald's",          "sector": "consumer"},
    {"ticker": "SBUX",  "name": "Starbucks",           "sector": "consumer"},
    {"ticker": "TGT",   "name": "Target",              "sector": "consumer"},
    {"ticker": "LOW",   "name": "Lowe's",              "sector": "consumer"},
    {"ticker": "NKE",   "name": "Nike",                "sector": "consumer"},
    {"ticker": "TJX",   "name": "TJX Companies",       "sector": "consumer"},
    {"ticker": "COST",  "name": "Costco",              "sector": "consumer"},
    {"ticker": "WMT",   "name": "Walmart",             "sector": "consumer"},
    {"ticker": "PG",    "name": "Procter & Gamble",    "sector": "consumer"},
    {"ticker": "KO",    "name": "Coca-Cola",           "sector": "consumer"},
    {"ticker": "PEP",   "name": "PepsiCo",             "sector": "consumer"},
    {"ticker": "MDLZ",  "name": "Mondelez",            "sector": "consumer"},
]

SP100_HEALTHCARE = [
    {"ticker": "UNH",   "name": "UnitedHealth",        "sector": "healthcare"},
    {"ticker": "JNJ",   "name": "Johnson & Johnson",   "sector": "healthcare"},
    {"ticker": "ABBV",  "name": "AbbVie",              "sector": "healthcare"},
    {"ticker": "MRK",   "name": "Merck",               "sector": "healthcare"},
    {"ticker": "TMO",   "name": "Thermo Fisher",       "sector": "healthcare"},
    {"ticker": "ABT",   "name": "Abbott",              "sector": "healthcare"},
    {"ticker": "DHR",   "name": "Danaher",             "sector": "healthcare"},
    {"ticker": "BMY",   "name": "Bristol-Myers",       "sector": "healthcare"},
    {"ticker": "AMGN",  "name": "Amgen",               "sector": "healthcare"},
    {"ticker": "GILD",  "name": "Gilead Sciences",     "sector": "healthcare"},
    {"ticker": "REGN",  "name": "Regeneron",           "sector": "healthcare"},
    {"ticker": "ISRG",  "name": "Intuitive Surgical",  "sector": "healthcare"},
    {"ticker": "MDT",   "name": "Medtronic",           "sector": "healthcare"},
    {"ticker": "ELV",   "name": "Elevance Health",     "sector": "healthcare"},
    {"ticker": "CI",    "name": "Cigna",               "sector": "healthcare"},
]

SP100_FINANCIALS = [
    {"ticker": "JPM",   "name": "JPMorgan Chase",      "sector": "financials"},
    {"ticker": "BAC",   "name": "Bank of America",     "sector": "financials"},
    {"ticker": "WFC",   "name": "Wells Fargo",         "sector": "financials"},
    {"ticker": "GS",    "name": "Goldman Sachs",       "sector": "financials"},
    {"ticker": "MS",    "name": "Morgan Stanley",      "sector": "financials"},
    {"ticker": "BLK",   "name": "BlackRock",           "sector": "financials"},
    {"ticker": "C",     "name": "Citigroup",           "sector": "financials"},
    {"ticker": "SPGI",  "name": "S&P Global",          "sector": "financials"},
    {"ticker": "AXP",   "name": "American Express",    "sector": "financials"},
    {"ticker": "USB",   "name": "US Bancorp",          "sector": "financials"},
    {"ticker": "CME",   "name": "CME Group",           "sector": "financials"},
    {"ticker": "MMC",   "name": "Marsh McLennan",      "sector": "financials"},
    {"ticker": "AON",   "name": "Aon",                 "sector": "financials"},
    {"ticker": "AFL",   "name": "Aflac",               "sector": "financials"},
    {"ticker": "AIG",   "name": "AIG",                 "sector": "financials"},
]

SP100_ENERGY_INDUSTRIAL = [
    {"ticker": "XOM",   "name": "ExxonMobil",          "sector": "energy"},
    {"ticker": "CVX",   "name": "Chevron",             "sector": "energy"},
    {"ticker": "SLB",   "name": "SLB",                 "sector": "energy"},
    {"ticker": "EOG",   "name": "EOG Resources",       "sector": "energy"},
    {"ticker": "RTX",   "name": "Raytheon",            "sector": "industrials"},
    {"ticker": "HON",   "name": "Honeywell",           "sector": "industrials"},
    {"ticker": "CAT",   "name": "Caterpillar",         "sector": "industrials"},
    {"ticker": "GE",    "name": "GE Aerospace",        "sector": "industrials"},
    {"ticker": "UNP",   "name": "Union Pacific",       "sector": "industrials"},
    {"ticker": "DE",    "name": "Deere & Co",          "sector": "industrials"},
    {"ticker": "EMR",   "name": "Emerson Electric",    "sector": "industrials"},
    {"ticker": "ITW",   "name": "Illinois Tool Works", "sector": "industrials"},
    {"ticker": "NSC",   "name": "Norfolk Southern",    "sector": "industrials"},
    {"ticker": "NOC",   "name": "Northrop Grumman",    "sector": "industrials"},
    {"ticker": "MMM",   "name": "3M",                  "sector": "industrials"},
]

SP100_OTHER = [
    {"ticker": "V",     "name": "Visa",                "sector": "payments"},
    {"ticker": "MA",    "name": "Mastercard",          "sector": "payments"},
    {"ticker": "NFLX",  "name": "Netflix",             "sector": "media"},
    {"ticker": "DIS",   "name": "Disney",              "sector": "media"},
    {"ticker": "NEE",   "name": "NextEra Energy",      "sector": "utilities"},
    {"ticker": "DUK",   "name": "Duke Energy",         "sector": "utilities"},
    {"ticker": "SO",    "name": "Southern Company",    "sector": "utilities"},
    {"ticker": "LIN",   "name": "Linde",               "sector": "materials"},
    {"ticker": "SHW",   "name": "Sherwin-Williams",    "sector": "materials"},
    {"ticker": "CL",    "name": "Colgate-Palmolive",   "sector": "staples"},
    {"ticker": "MO",    "name": "Altria",              "sector": "staples"},
    {"ticker": "PM",    "name": "Philip Morris",       "sector": "staples"},
    {"ticker": "ZTS",   "name": "Zoetis",              "sector": "healthcare"},
    {"ticker": "BSX",   "name": "Boston Scientific",   "sector": "healthcare"},
    {"ticker": "HCA",   "name": "HCA Healthcare",      "sector": "healthcare"},
]

# ============================================================
# 合并完整的标普100候选池
# ============================================================

SP100_POOL = (
    SP100_TECH +
    SP100_CONSUMER +
    SP100_HEALTHCARE +
    SP100_FINANCIALS +
    SP100_ENERGY_INDUSTRIAL +
    SP100_OTHER
)

SP100_TICKERS = [item["ticker"] for item in SP100_POOL]


def get_sp100_ticker_info(ticker: str) -> dict:
    """根据ticker获取股票元数据。"""
    for item in SP100_POOL:
        if item["ticker"] == ticker:
            return item
    return {"ticker": ticker, "name": ticker, "sector": "unknown"}


def get_sp100_by_sector(sector: str) -> list:
    """按板块筛选候选股。"""
    return [item for item in SP100_POOL if item["sector"] == sector]
