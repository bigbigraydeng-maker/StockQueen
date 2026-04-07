"""
StockQueen - Intraday Scoring Configuration
盘中 30 分钟评分策略参数配置。
"""


class IntradayConfig:
    """盘中评分策略参数（独立于日频宝典 V5）"""

    # ----- 扫描参数 -----
    SCAN_INTERVAL_MIN: int = 30          # 评分间隔（分钟）
    TIMESPAN: str = "minute"             # Massive API timespan
    MULTIPLIER: int = 30                 # 30 分钟 bars
    LOOKBACK_BARS: int = 26              # 回看 26 根 30min bar ≈ 2 个交易日
    LOOKBACK_DAYS: int = 3               # API 请求回看天数（含非交易日）

    # ----- 选股池 -----
    TOP_N: int = 5                       # 每轮评分取前 5 名
    MIN_SCORE_THRESHOLD: float = 0.3     # 最低评分阈值（盘中信噪比低，阈值提高）

    # 盘中交易池：高流动性大盘股 + 主流 ETF（避免小盘股 spread 问题）
    UNIVERSE: list = [
        # 科技大盘
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "AVGO", "CRM",
        "ORCL", "ADBE", "NFLX", "INTC", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "MRVL",
        # 金融/医疗/消费
        "JPM", "V", "MA", "BAC", "GS", "UNH", "JNJ", "PFE", "ABBV", "LLY",
        "WMT", "COST", "HD", "MCD", "KO", "PEP", "NKE", "SBUX",
        # 能源/工业
        "XOM", "CVX", "COP", "BA", "CAT", "GE", "RTX", "LMT",
        # 主流 ETF
        "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV",
    ]

    # ----- 因子权重（纯量价 + 微观结构） -----
    FACTOR_WEIGHTS: dict = {
        "intraday_momentum": 0.25,   # 短期动量（1-2-4 bar 加权收益）
        "vwap_deviation":    0.20,   # 价格相对 VWAP 偏离度
        "volume_profile":    0.20,   # 成交量异常（相对日内均值）
        "micro_rsi":         0.15,   # RSI(6) 超买超卖
        "spread_quality":    0.10,   # 价格效率 (close-open)/(high-low)
        "relative_flow":     0.10,   # 相对 SPY 超额收益
    }

    # ----- 风控（杠杆账户） -----
    MAX_POSITION_SIZE: float = 0.15      # 单只最大仓位 15%
    MAX_TOTAL_EXPOSURE: float = 1.50     # 杠杆账户最大总敞口 150%
    STOP_LOSS_ATR_MULT: float = 1.5      # 止损 = 1.5x 盘中 ATR
    TAKE_PROFIT_ATR_MULT: float = 3.0    # 止盈 = 3.0x 盘中 ATR
    MAX_HOLD_BARS: int = 13              # 最长持有 13 根 30min bar（1 个交易日）

    # ----- 执行 -----
    AUTO_EXECUTE: bool = False           # 默认信号模式，不自动下单
    ACCOUNT_LABEL: str = "leverage"      # Tiger 杠杆账户标签

    # ----- 交易时段（美东） -----
    MARKET_OPEN_ET: str = "09:30"
    MARKET_CLOSE_ET: str = "16:00"
    # 首轮评分在 10:00 ET（开盘 30min 后首根 bar 完成）
    FIRST_ROUND_ET: str = "10:00"
