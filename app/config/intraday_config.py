"""
StockQueen - Intraday Scoring Configuration
盘中 30 分钟评分策略参数配置。
"""

from app.config.intraday_universe import INTRADAY_UNIVERSE


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
    MAX_UNIVERSE_SIZE: int = 50          # 可交易标的数量上限（成分股/名单扩缩时不得超过）
    MIN_SCORE_THRESHOLD: float = 0.3     # 最低评分阈值（盘中信噪比低，阈值提高）

    # ----- 止盈止损（铃铛执行层 2026-04）-----
    FULL_STOP_LOSS_PCT: float = -0.003           # 亏损 ≥0.3% 软件全平，腾出空位后可立即重扫市场补票
    # 建仓时在 Tiger 下括号单：限价止盈 = 参考价 × (1+ENTRY_BRACKET_TAKE_PROFIT_PCT)，通常为 +0.5%
    # 为 True 时不再跑 Pass B（软件减半）与 Pass C（ATR 全平），避免与券商括号单竞态
    USE_ENTRY_BRACKET_TAKE_PROFIT: bool = False  # 改用软件 Pass B/C 止盈，避免括号单被取消后失效
    ENTRY_BRACKET_TAKE_PROFIT_PCT: float = 0.005
    # 关闭括号止盈时仍可用：盈利 ≥0.5% 先减半；剩余由 Pass C / 止损管理
    PARTIAL_PROFIT_TRIGGER_PCT: float = 0.003
    PARTIAL_EXIT_FRACTION: float = 0.5           # 减半比例
    ENTRY_RETRY_MINUTES: int = 30                # watchlist 首次建仓失败后重试窗口（分钟）
    # 有空槽时按「当前轮」动能排名补位，不限于早盘保存的 Top20 watchlist（解决空位不补）
    ALLOW_RANK_FILL_EMPTY_SLOTS: bool = True
    # 平仓腾出持股空位后，立即跑一轮全市场评分（Massive），再按策略建仓；避免等下一根 30min
    IMMEDIATE_RESCAN_ON_SLOT_FREE: bool = True

    # ----- 建仓确认（减轻 30min 滞后 + 追高）-----
    # 见 app/services/intraday_entry_confirm.py；仅对自动开仓生效
    ENTRY_CONFIRM_ENABLED: bool = True
    ENTRY_CONFIRM_LOOKBACK_BARS: int = 5          # 最近 5 根 30min bar
    ENTRY_CONFIRM_MIN_GREEN_RATIO: float = 0.3  # 至少 30% 收阳（如 2/5）
    ENTRY_CONFIRM_MAX_DIST_FROM_HIGH_PCT: float = 0.02  # 收盘距近 N 根最高价 ≤2.0%

    # 盘中交易池：见 app/config/intraday_universe.py（高成交 + 高波动倾向，50 只上限）
    UNIVERSE: list = list(INTRADAY_UNIVERSE)

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
    MAX_POSITION_SIZE: float = 0.40      # 单只最大仓位 40%（3x 均分 8 只 = 37.5%）
    # 默认 3.0；运行中上限以 app/config/intraday_runtime.json + get_max_total_exposure() 为准（Lab/后台可调）
    MAX_TOTAL_EXPOSURE: float = 3.0
    # TOP5 篮子目标：按评分分配时，5 只「合计」最多使用的权益倍数（在单票 MAX、总敞口约束下）
    # 旧版硬编码 0.60 会导致长期只用到约 60% 权益，远低于 200% 上限；提高可提升资金效率（风险同步上升）
    TOP5_BASKET_EQUITY_FRACTION: float = 1.0
    STOP_LOSS_ATR_MULT: float = 1.5      # 止损 = 1.5x 盘中 ATR（Pass C 开启时）
    # 括号止盈关闭时 Pass C 用；略降低倍数以提高触发率（大盘股脉冲短）
    TAKE_PROFIT_ATR_MULT: float = 1.8
    MAX_HOLD_BARS: int = 13              # 最长持有 13 根 30min bar（1 个交易日）

    # ----- 执行 -----
    AUTO_EXECUTE: bool = True            # 启用自动下单（模拟盘测试）
    ACCOUNT_LABEL: str = "leverage"      # Tiger 杠杆账户标签

    # ----- 交易时段（美东） -----
    MARKET_OPEN_ET: str = "09:30"
    MARKET_CLOSE_ET: str = "16:00"
    # 首轮评分在 10:00 ET（开盘 30min 后首根 bar 完成）
    FIRST_ROUND_ET: str = "10:00"
