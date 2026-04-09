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
    TOP_N: int = 20                      # 兼容旧名：与 WATCHLIST_SIZE 一致（每轮展示/切片用）
    WATCHLIST_SIZE: int = 20             # 开盘首轮保存动能评分前 N 名
    MAX_CONCURRENT_POSITIONS: int = 10   # 同时最多持有股票数
    MIN_SCORE_THRESHOLD: float = 0.3     # 最低评分阈值（盘中信噪比低，阈值提高）

    # ----- 止盈止损（铃铛执行层 2026-04）-----
    FULL_STOP_LOSS_PCT: float = -0.005           # 亏损 ≥0.5% 全平
    PARTIAL_PROFIT_TRIGGER_PCT: float = 0.01    # 盈利 ≥1% 考察减半仓
    PARTIAL_EXIT_FRACTION: float = 0.5           # 减半比例
    MOMENTUM_BETTER_MAX_RANK: int = 10           # 「动能更好」：本轮全市场排名仍 ≤ 此名次
    MOMENTUM_BETTER_SCORE_RATIO: float = 0.99   # 且当前总分 ≥ 建仓时评分 * 此比例（无建仓记录时仅看排名）
    ENTRY_RETRY_MINUTES: int = 30                # watchlist 首次建仓失败后重试窗口（分钟）

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
    # 更新于 2026-04-10：RSI 转为过滤器，因子权重重新分配以降低共线性
    # - Momentum 提升至 30%（主要趋势信号）
    # - VWAP 降至 15%（与动量共线性高）
    # - Volume 维持 20%（方向无关）
    # - Quality 升至 15%（K 线效率）
    # - Flow 升至 20%（市场对标）
    # - RSI 转为前置过滤（替代评分）
    FACTOR_WEIGHTS: dict = {
        "intraday_momentum": 0.30,   # 短期动量（1-2-4 bar 加权收益）
        "vwap_deviation":    0.15,   # 价格相对 VWAP 偏离度（降低共线性）
        "volume_profile":    0.20,   # 成交量异常（相对日内均值）
        "micro_rsi":         0.00,   # RSI(6) 转为前置过滤，不参与评分
        "spread_quality":    0.15,   # 价格效率 (close-open)/(high-low)
        "relative_flow":     0.20,   # 相对 SPY 超额收益（提升权重）
    }

    # RSI 过滤参数（前置过滤，不参与评分）
    # 避免在极端超买/超卖状态下进场
    RSI_FILTER_LOW: float = 20.0     # RSI < 20 过度超卖，信号不稳
    RSI_FILTER_HIGH: float = 80.0    # RSI > 80 过度超买，反转风险

    # ----- 风控（杠杆账户） -----
    MAX_POSITION_SIZE: float = 0.15      # 单只最大仓位 15%
    MAX_TOTAL_EXPOSURE: float = 2.0      # 杠杆账户最大总敞口 200%（名义市值/权益）
    # TOP5 篮子目标：按评分分配时，5 只「合计」最多使用的权益倍数（在单票 MAX、总敞口约束下）
    # 旧版硬编码 0.60 会导致长期只用到约 60% 权益，远低于 200% 上限；提高可提升资金效率（风险同步上升）
    TOP5_BASKET_EQUITY_FRACTION: float = 1.0
    STOP_LOSS_ATR_MULT: float = 1.5      # 止损 = 1.5x 盘中 ATR
    TAKE_PROFIT_ATR_MULT: float = 3.0    # 减半仓后剩余仓位：价格 ≥ 参考价 + ATR*倍数 全平（参考价见执行逻辑）
    MAX_HOLD_BARS: int = 13              # 最长持有 13 根 30min bar（1 个交易日）

    # ----- 执行 -----
    AUTO_EXECUTE: bool = True            # 启用自动下单（模拟盘测试）
    ACCOUNT_LABEL: str = "leverage"      # Tiger 杠杆账户标签

    # ----- 交易时段（美东） -----
    MARKET_OPEN_ET: str = "09:30"
    MARKET_CLOSE_ET: str = "16:00"
    # 首轮评分在 10:00 ET（开盘 30min 后首根 bar 完成）
    FIRST_ROUND_ET: str = "10:00"
