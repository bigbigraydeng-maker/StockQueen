"""
StockQueen V1 - Geopolitical Crisis Watchlist
霍尔木兹海峡危机受益/受损标的监控列表

Sectors:
- OIL_GAS: 油气开采（做多方向）
- OIL_TANKER: 油轮/航运（做多方向）
- GOLD: 黄金/贵金属（做多方向）
- DEFENSE: 军工/国防（做多方向）
- COAL_ALT_ENERGY: 煤炭/替代能源（做多方向）
- REFINERY: 炼油/下游（做多方向，受益于crack spread扩大）
- AIRLINE_SHORT: 航空（做空/规避方向）
- CRUISE_SHORT: 邮轮（做空/规避方向）
"""

# ============================================================
# 做多方向标的
# ============================================================

OIL_GAS_WATCHLIST = {
    # 美国石油巨头（Permian Basin产能不受海峡影响，直接受益油价上涨）
    "XOM": "ExxonMobil",
    "CVX": "Chevron",
    "COP": "ConocoPhillips",
    "OXY": "Occidental Petroleum",
    "EOG": "EOG Resources",
    "PXD": "Pioneer Natural Resources",
    "DVN": "Devon Energy",
    "FANG": "Diamondback Energy",
    "MRO": "Marathon Oil",
    "APA": "APA Corporation",
    # 油服
    "SLB": "Schlumberger",
    "HAL": "Halliburton",
    "BKR": "Baker Hughes",
    # 天然气（LNG供应中断受益）
    "LNG": "Cheniere Energy",
    "AR": "Antero Resources",
    "EQT": "EQT Corporation",
    "SWN": "Southwestern Energy",
    # 港股/中概 油气
    "0883.HK": "中国海洋石油",
    "0386.HK": "中国石化",
    "0857.HK": "中国石油",
    "PTR": "PetroChina ADR",
    "SNP": "Sinopec ADR",
    "CEO": "CNOOC ADR",
}

OIL_TANKER_WATCHLIST = {
    # VLCC油轮（运距拉长+运价飙升直接受益）
    "FRO": "Frontline",
    "STNG": "Scorpio Tankers",
    "TNK": "Teekay Tankers",
    "INSW": "International Seaways",
    "DHT": "DHT Holdings",
    "NAT": "Nordic American Tankers",
    "EURN": "Euronav",
    "ASC": "Ardmore Shipping",
    "TEN": "Tsakos Energy Navigation",
    # 集装箱/散货（间接受益于绕行）
    "ZIM": "ZIM Integrated Shipping",
    "GOGL": "Golden Ocean Group",
    "SBLK": "Star Bulk Carriers",
    # 港股航运
    "1919.HK": "中远海运能源",
    "1138.HK": "中远海运港口",
    "0316.HK": "东方海外国际",
}

GOLD_WATCHLIST = {
    # 黄金ETF
    "GLD": "SPDR Gold Trust ETF",
    "GDX": "VanEck Gold Miners ETF",
    "GDXJ": "VanEck Junior Gold Miners ETF",
    "IAU": "iShares Gold Trust",
    # 黄金矿业公司
    "NEM": "Newmont Corporation",
    "GOLD": "Barrick Gold",
    "AEM": "Agnico Eagle Mines",
    "FNV": "Franco-Nevada",
    "WPM": "Wheaton Precious Metals",
    "KGC": "Kinross Gold",
    "AU": "AngloGold Ashanti",
    "HMY": "Harmony Gold",
    # 白银（避险联动）
    "SLV": "iShares Silver Trust",
    "PAAS": "Pan American Silver",
    # 港股/A股黄金
    "2899.HK": "紫金矿业",
    "1818.HK": "招金矿业",
}

DEFENSE_WATCHLIST = {
    # 美国军工巨头
    "LMT": "Lockheed Martin",
    "RTX": "RTX Corporation",
    "NOC": "Northrop Grumman",
    "GD": "General Dynamics",
    "BA": "Boeing",
    "LHX": "L3Harris Technologies",
    "HII": "Huntington Ingalls Industries",
    # 欧洲军工
    "BAESY": "BAE Systems ADR",
    # 军工ETF
    "ITA": "iShares US Aerospace & Defense ETF",
    "PPA": "Invesco Aerospace & Defense ETF",
}

COAL_ALT_ENERGY_WATCHLIST = {
    # 煤炭（油价飙升时替代能源受益）
    "BTU": "Peabody Energy",
    "ARCH": "Arch Resources",
    "CTRA": "Coterra Energy",
    "CNX": "CNX Resources",
    # 核能（长期能源安全受益）
    "CCJ": "Cameco Corporation",
    "URA": "Global X Uranium ETF",
    "LEU": "Centrus Energy",
    # 新能源（能源危机推动转型加速）
    "ENPH": "Enphase Energy",
    "FSLR": "First Solar",
    "SEDG": "SolarEdge Technologies",
}

REFINERY_WATCHLIST = {
    # 炼油（crack spread扩大受益，但原料成本也上升）
    "VLO": "Valero Energy",
    "MPC": "Marathon Petroleum",
    "PSX": "Phillips 66",
    "DINO": "HF Sinclair",
    "PBF": "PBF Energy",
}

# ============================================================
# 做空/规避方向标的
# ============================================================

AIRLINE_SHORT_WATCHLIST = {
    # 航空公司（燃油成本暴增，盈利受严重压缩）
    "UAL": "United Airlines",
    "DAL": "Delta Air Lines",
    "AAL": "American Airlines",
    "LUV": "Southwest Airlines",
    "JBLU": "JetBlue Airways",
    "ALK": "Alaska Air Group",
    "SAVE": "Spirit Airlines",
    # 国际航空（受影响更大）
    "RYAAY": "Ryanair",
    # 中国航空
    "ZNH": "南方航空 ADR",
    "CEA": "东方航空 ADR",
}

CRUISE_SHORT_WATCHLIST = {
    # 邮轮（燃油+航线改道+消费信心）
    "CCL": "Carnival Corporation",
    "RCL": "Royal Caribbean",
    "NCLH": "Norwegian Cruise Line",
}

# ============================================================
# 汇总
# ============================================================

# 所有做多标的合并
GEOPOLITICAL_LONG_WATCHLIST = {}
GEOPOLITICAL_LONG_WATCHLIST.update(OIL_GAS_WATCHLIST)
GEOPOLITICAL_LONG_WATCHLIST.update(OIL_TANKER_WATCHLIST)
GEOPOLITICAL_LONG_WATCHLIST.update(GOLD_WATCHLIST)
GEOPOLITICAL_LONG_WATCHLIST.update(DEFENSE_WATCHLIST)
GEOPOLITICAL_LONG_WATCHLIST.update(COAL_ALT_ENERGY_WATCHLIST)
GEOPOLITICAL_LONG_WATCHLIST.update(REFINERY_WATCHLIST)

# 所有做空标的合并
GEOPOLITICAL_SHORT_WATCHLIST = {}
GEOPOLITICAL_SHORT_WATCHLIST.update(AIRLINE_SHORT_WATCHLIST)
GEOPOLITICAL_SHORT_WATCHLIST.update(CRUISE_SHORT_WATCHLIST)

# 全部标的
GEOPOLITICAL_ALL_WATCHLIST = {}
GEOPOLITICAL_ALL_WATCHLIST.update(GEOPOLITICAL_LONG_WATCHLIST)
GEOPOLITICAL_ALL_WATCHLIST.update(GEOPOLITICAL_SHORT_WATCHLIST)

# Sector标签映射（ticker -> sector）
GEOPOLITICAL_SECTOR_MAP = {}
for t in OIL_GAS_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "OIL_GAS"
for t in OIL_TANKER_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "OIL_TANKER"
for t in GOLD_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "GOLD"
for t in DEFENSE_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "DEFENSE"
for t in COAL_ALT_ENERGY_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "COAL_ALT_ENERGY"
for t in REFINERY_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "REFINERY"
for t in AIRLINE_SHORT_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "AIRLINE_SHORT"
for t in CRUISE_SHORT_WATCHLIST:
    GEOPOLITICAL_SECTOR_MAP[t] = "CRUISE_SHORT"

# 关键词映射（公司名 -> ticker）
GEOPOLITICAL_KEYWORDS = {
    "Exxon": "XOM",
    "ExxonMobil": "XOM",
    "Chevron": "CVX",
    "ConocoPhillips": "COP",
    "Occidental": "OXY",
    "Schlumberger": "SLB",
    "Halliburton": "HAL",
    "Cheniere": "LNG",
    "Frontline": "FRO",
    "Scorpio Tankers": "STNG",
    "Newmont": "NEM",
    "Barrick": "GOLD",
    "Lockheed": "LMT",
    "Northrop": "NOC",
    "Raytheon": "RTX",
    "RTX": "RTX",
    "BAE Systems": "BAESY",
    "Carnival": "CCL",
    "Delta Air": "DAL",
    "United Airlines": "UAL",
    "American Airlines": "AAL",
    "Strait of Hormuz": "_GEOPOLITICAL_EVENT",
    "霍尔木兹": "_GEOPOLITICAL_EVENT",
    "Iran sanctions": "_GEOPOLITICAL_EVENT",
    "oil embargo": "_GEOPOLITICAL_EVENT",
    "OPEC": "_GEOPOLITICAL_EVENT",
    "oil supply": "_GEOPOLITICAL_EVENT",
    "crude oil": "_GEOPOLITICAL_EVENT",
    "Brent crude": "_GEOPOLITICAL_EVENT",
    "WTI crude": "_GEOPOLITICAL_EVENT",
    "中东局势": "_GEOPOLITICAL_EVENT",
    "oil tanker attack": "_GEOPOLITICAL_EVENT",
    "shipping disruption": "_GEOPOLITICAL_EVENT",
}
