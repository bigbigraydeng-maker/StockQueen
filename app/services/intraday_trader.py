"""
StockQueen - Intraday Auto-Trader
铃铛策略自动化交易执行模块

功能：
  1. 监听评分信号 (TOP_5)
  2. 自动建仓 (加权分配)
  3. 实时止盈止损
  4. 动态头寸管理
  5. 杠杆账户风险控制
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import numpy as np
import pytz

from app.config.intraday_config import IntradayConfig
from app.services.order_service import TigerTradeClient
from app.services.massive_client import get_massive_client
from app.services import intraday_state as intraday_state_store
from app.database import get_db

logger = logging.getLogger(__name__)
ET = pytz.timezone('US/Eastern')


def _rank_of_ticker(ticker: str, all_scores: List[dict]) -> int:
    for s in all_scores:
        if s.get("ticker") == ticker:
            return int(s.get("rank", 999))
    return 999


def _momentum_better(
    cfg,
    ticker: str,
    all_scores: List[dict],
    entry_scores: Dict[str, float],
) -> bool:
    """盈利>1% 时减半仓：动能更好 = 本轮排名仍靠前且分数不低于建仓时一定比例。"""
    rank = _rank_of_ticker(ticker, all_scores)
    if rank > cfg.MOMENTUM_BETTER_MAX_RANK:
        return False
    cur = next((float(s["total_score"]) for s in all_scores if s.get("ticker") == ticker), None)
    prev = entry_scores.get(ticker)
    if cur is None:
        return False
    if prev is not None:
        return cur >= float(prev) * cfg.MOMENTUM_BETTER_SCORE_RATIO
    return True


async def _atr_take_profit_hit(massive, ticker: str, ref_entry: float, cfg) -> Tuple[bool, float]:
    """剩余仓位：现价 >= 参考成本价 + ATR * TAKE_PROFIT_ATR_MULT"""
    try:
        bars = await massive.get_intraday_arrays(ticker, "minute", 30, 1)
        if not bars or len(bars.get("close", [])) == 0:
            return False, 0.0
        current_price = float(bars["close"][-1])
        highs = np.array(bars["high"][-26:])
        lows = np.array(bars["low"][-26:])
        if len(highs) < 2:
            return False, current_price
        atr = float(np.mean(np.abs(highs - lows)))
        tp = ref_entry + atr * cfg.TAKE_PROFIT_ATR_MULT
        return current_price >= tp, current_price
    except Exception as e:
        logger.warning(f"[TRADER] ATR TP check failed {ticker}: {e}")
        return False, 0.0


class IntradayTrader:
    """铃铛策略自动交易执行器"""

    def __init__(self, account_label: str = "leverage"):
        """
        初始化交易执行器

        Args:
            account_label: Tiger 账户标签 ("leverage" 或 "standard")
        """
        self.account_label = account_label
        self.tiger = TigerTradeClient(account_label=account_label)
        self.massive = get_massive_client()
        self.cfg = IntradayConfig
        self.db = get_db()

        # 交易状态追踪
        self.active_positions: Dict[str, Dict] = {}  # {ticker: {qty, entry_price, ...}}
        self.pending_orders: Dict[str, Dict] = {}    # {order_id: {ticker, qty, ...}}

        # 风控追踪
        self.daily_realized_pnl = 0.0    # 日内已实现 P&L
        self.day_trade_count = 0         # 本日 day trades 计数
        self.last_trading_date = None    # 最后交易日期

    async def get_account_info(self) -> Dict:
        """获取账户信息（余额、杠杆、敞口）"""
        try:
            assets = await self.tiger.get_account_assets()
            equity = assets.get("net_liquidation", 0) if assets else 0
            return {
                'status': 'ok',
                'equity': equity,
                'cash': assets.get("cash", 0) if assets else 0,
                'buying_power': assets.get("buying_power", 0) if assets else 0,
                'timestamp': datetime.now(ET).isoformat(),
            }
        except Exception as e:
            logger.error(f"[TRADER] Account fetch failed: {e}")
            return {'status': 'error', 'reason': str(e)}

    # ============================================================
    # P0 风控方法
    # ============================================================

    async def check_maintenance_ratio(self, account_equity: float) -> Dict:
        """
        检查维持率，触发自动减仓

        维持率 = 现金 / 总敞口
        - > 50%: 安全
        - 30-50%: 警告
        - < 30%: Tiger 强制平仓

        Returns:
            {status, ratio, action, reason}
        """
        try:
            # 计算总敞口
            total_exposure = 0
            for ticker, pos in self.active_positions.items():
                total_exposure += pos['qty'] * pos.get('current_price', 0)

            # 计算维持率
            current_cash = account_equity - total_exposure
            if total_exposure <= 0:
                return {'status': 'ok', 'ratio': 1.0, 'action': None}

            ratio = current_cash / total_exposure

            if ratio > 0.5:
                logger.info(f"[RISK] Maintenance ratio: {ratio*100:.1f}% (SAFE)")
                return {'status': 'ok', 'ratio': ratio, 'action': None}

            elif ratio > 0.3:
                logger.warning(f"[RISK] Maintenance ratio: {ratio*100:.1f}% (WARNING)")
                return {'status': 'warning', 'ratio': ratio, 'action': 'monitor'}

            else:
                # 自动减仓 50%
                logger.critical(f"[RISK] Maintenance ratio: {ratio*100:.1f}% (CRITICAL - AUTO REDUCE)")
                await self._reduce_positions_by_pct(0.5)
                return {'status': 'critical', 'ratio': ratio, 'action': 'auto_reduced_50pct'}

        except Exception as e:
            logger.error(f"[RISK] Maintenance check failed: {e}")
            return {'status': 'error', 'reason': str(e)}

    async def check_daily_loss_limit(self, daily_loss_limit_pct: float = 0.02) -> Dict:
        """
        检查日内亏损限制

        Args:
            daily_loss_limit_pct: 日亏限制（默认 2%）

        Returns:
            {status, daily_pnl, daily_pnl_pct, action}
        """
        # 重置日计数（如果日期变了）
        today = datetime.now(ET).date()
        if self.last_trading_date != today:
            self.daily_realized_pnl = 0.0
            self.day_trade_count = 0
            self.last_trading_date = today

        # 计算日内亏损百分比
        assets = await self.tiger.get_account_assets()
        account_equity = assets.get("net_liquidation", 0) if assets else 0
        daily_loss_pct = abs(self.daily_realized_pnl) / account_equity if (self.daily_realized_pnl < 0 and account_equity > 0) else 0

        if daily_loss_pct >= daily_loss_limit_pct:
            logger.critical(
                f"[RISK] Daily loss limit exceeded: {daily_loss_pct*100:.2f}% >= {daily_loss_limit_pct*100:.1f}%"
            )
            return {
                'status': 'critical',
                'daily_pnl': self.daily_realized_pnl,
                'daily_pnl_pct': daily_loss_pct * 100,
                'action': 'STOP_TRADING'
            }

        return {
            'status': 'ok',
            'daily_pnl': self.daily_realized_pnl,
            'daily_pnl_pct': daily_loss_pct * 100,
            'action': None
        }

    def check_day_trade_limit(self) -> Dict:
        """
        检查 PDT (Pattern Day Trader) 规则

        规则: 5 个交易日内最多 3 次 day trades
        day trade = 同一天内 buy + sell 同一只票

        Returns:
            {status, count, allowed, action}
        """
        # 简化：假设每个 exit 就是一次 day trade
        # 实际应该追踪 5 日滚动窗口和具体的 buy+sell 对

        today = datetime.now(ET).date()
        if self.last_trading_date != today:
            self.day_trade_count = 0

        if self.day_trade_count >= 3:
            logger.warning(f"[RISK] PDT limit reached: {self.day_trade_count} day trades in 5 days")
            return {
                'status': 'warning',
                'count': self.day_trade_count,
                'allowed': 3,
                'action': 'avoid_same_day_buy_sell'
            }

        return {
            'status': 'ok',
            'count': self.day_trade_count,
            'allowed': 3,
            'action': None
        }

    async def _reduce_positions_by_pct(self, pct: float = 0.5):
        """
        强制减仓指定百分比

        Args:
            pct: 减仓比例 (0.5 = 减 50%)
        """
        reduce_count = 0
        for ticker, position in list(self.active_positions.items()):
            qty_to_sell = int(position['qty'] * pct)
            if qty_to_sell > 0:
                try:
                    await self.tiger.place_sell_order(ticker, qty_to_sell)
                    logger.warning(f"[RISK] Force reduced {ticker}: -{qty_to_sell} shares ({pct*100:.0f}%)")
                    reduce_count += 1
                except Exception as e:
                    logger.error(f"[RISK] Reduce failed {ticker}: {e}")

        logger.info(f"[RISK] Force reduction complete: {reduce_count} positions reduced")

    async def _calculate_position_size(
        self,
        score: float,
        total_score: float,
        account_equity: float,
        current_price: float = 100.0,
        planned_entries: int = 5,
    ) -> int:
        """
        根据评分和风险管理计算头寸大小

        Args:
            score: 个股总分 [-10, +10]
            total_score: 本轮所有 TOP_5 的总分 (和)
            account_equity: 账户权益
            current_price: 当前价格（用于计算股数）

        Returns:
            建议下单股数
        """
        # 1. 根据相对评分分配资金
        # TOP_5 中，高评分股票获得更多资金
        score_weight = max(0, score) / max(0.1, total_score)  # 避免除零

        # 2. 整体敞口控制：按评分在 TOP5 内分配，合计不超过 TOP5_BASKET_EQUITY_FRACTION * equity
        max_allocation_for_top5 = self.cfg.TOP5_BASKET_EQUITY_FRACTION
        allocation_pct = score_weight * max_allocation_for_top5

        # 3. 单只头寸上限
        max_single_exposure = self.cfg.MAX_POSITION_SIZE  # 15%
        allocation_pct = min(allocation_pct, max_single_exposure)

        # 4. 总敞口上限 - 从 Tiger 获取实际持仓（不依赖本地 active_positions）
        try:
            actual_positions = await self.tiger.get_positions()
            current_exposure = sum(
                (p.get('market_value', 0) / account_equity)
                for p in actual_positions
            )
            logger.debug(f"[TRADER] Current exposure from Tiger: {current_exposure*100:.1f}%")
        except Exception as e:
            logger.warning(f"[TRADER] Failed to get actual positions: {e}, falling back to local positions")
            current_exposure = sum(
                (p['qty'] * p.get('current_price', 100) / account_equity)
                for p in self.active_positions.values()
            )

        max_remaining = self.cfg.MAX_TOTAL_EXPOSURE - current_exposure

        # 如果剩余敞口不足，减少分配
        if max_remaining <= 0:
            logger.warning(f"[TRADER] Max exposure {self.cfg.MAX_TOTAL_EXPOSURE*100:.0f}% already reached, rejecting position")
            return 0

        denom = max(1, min(planned_entries, self.cfg.MAX_CONCURRENT_POSITIONS))
        allocation_pct = min(allocation_pct, max_remaining / denom)

        # 5. 计算股数
        capital = account_equity * allocation_pct
        position_size = capital / max(current_price, 0.01)  # 避免除零

        return max(1, int(position_size))

    async def execute_entry(
        self,
        ticker: str,
        current_price: float,
        score: float,
        total_score: float,
        account_equity: float,
        planned_entries: int = 5,
        existing_tickers: Optional[set] = None,
    ) -> Dict:
        """
        执行建仓（含风控检查）

        Args:
            ticker: 股票代码
            current_price: 当前价格
            score: 评分
            total_score: TOP_5 总分
            account_equity: 账户权益

        Returns:
            建仓结果 {order_id, qty, price, ...}
        """
        # 防守：确保 ticker 是字符串
        if not isinstance(ticker, str):
            logger.error(f"[TRADER] Invalid ticker type: {type(ticker)}, value: {ticker}")
            return {
                'status': 'error',
                'ticker': str(ticker),
                'reason': 'invalid_ticker_type'
            }

        ticker = str(ticker).upper().strip()
        existing_tickers = existing_tickers or set()

        try:
            # ===== P0 风控检查 =====

            # 1. 日亏损检查
            loss_check = await self.check_daily_loss_limit(daily_loss_limit_pct=0.02)
            if loss_check['status'] == 'critical':
                logger.critical("[TRADER] Daily loss limit hit, no new positions")
                return {'status': 'skip', 'reason': 'daily_loss_limit_exceeded'}

            # 2. 维持率检查
            ratio_check = await self.check_maintenance_ratio(account_equity)
            if ratio_check['status'] == 'critical':
                logger.critical("[TRADER] Maintenance ratio critical, no new positions")
                return {'status': 'skip', 'reason': 'maintenance_ratio_critical'}

            # 3. 日冲检查
            pdt_check = self.check_day_trade_limit()
            if pdt_check['status'] == 'warning' and pdt_check['count'] >= 3:
                logger.warning("[TRADER] PDT limit approaching, consider holding overnight")
                # 不阻止，但标记警告

            # ===== 业务逻辑 =====

            if ticker in existing_tickers:
                logger.info(f"[TRADER] {ticker} already held (Tiger), skipping entry")
                return {'status': 'skip', 'reason': 'already_in_position'}

            if ticker in self.active_positions:
                logger.info(f"[TRADER] {ticker} already in position, skipping entry")
                return {'status': 'skip', 'reason': 'already_in_position'}

            # 计算建仓数量
            qty = await self._calculate_position_size(
                score, total_score, account_equity, current_price, planned_entries=planned_entries
            )
            if qty == 0:
                return {'status': 'skip', 'reason': 'position_size_too_small'}

            # 下单：限价单，略低于市价 (增加成交概率)
            limit_price = round(current_price * 0.99, 2)

            order_result = await self.tiger.place_buy_order(
                ticker=ticker,
                quantity=qty,
                limit_price=limit_price,
            )

            # Tiger API 返回字典，从中提取 order_id
            if not order_result or not isinstance(order_result, dict):
                logger.error(f"[TRADER] Invalid order result: {order_result}")
                return {
                    'status': 'error',
                    'ticker': ticker,
                    'reason': 'invalid_order_result'
                }

            order_id = order_result.get('order_id')
            if not order_id:
                logger.error(f"[TRADER] No order_id in result: {order_result}")
                return {
                    'status': 'error',
                    'ticker': ticker,
                    'reason': 'missing_order_id'
                }

            logger.info(
                f"[TRADER] Entry {ticker}: {qty} @ ${limit_price} "
                f"(score={score:.2f}, alloc={qty*limit_price/account_equity*100:.1f}%)"
            )

            # 记录待成交订单
            self.pending_orders[order_id] = {
                'ticker': ticker,
                'qty': qty,
                'entry_price': limit_price,
                'entry_score': score,
                'entry_time': datetime.now(ET),
            }

            return {
                'status': 'ok',
                'order_id': order_id,
                'ticker': ticker,
                'qty': qty,
                'price': limit_price,
            }

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"[TRADER] Entry failed {ticker}: {error_msg}")
            logger.error(f"[TRADER] Traceback: {traceback.format_exc()}")
            return {
                'status': 'error',
                'ticker': ticker,
                'reason': error_msg
            }

    async def check_exits(self) -> List[Dict]:
        """
        检查现有头寸是否触发止盈/止损

        Returns:
            平仓订单列表
        """
        exit_orders = []

        for ticker, position in list(self.active_positions.items()):
            try:
                # 获取当前价格
                bars = await self.massive.get_intraday_arrays(
                    ticker, "minute", 30, 1
                )
                if not bars or len(bars['close']) == 0:
                    continue

                current_price = float(bars['close'][-1])
                entry_price = position['entry_price']
                qty = position['qty']

                # 计算 ATR 止盈止损点位
                highs = np.array(bars['high'][-26:])
                lows = np.array(bars['low'][-26:])
                atr = np.mean(np.abs(highs - lows))

                take_profit = entry_price + atr * self.cfg.TAKE_PROFIT_ATR_MULT
                stop_loss = entry_price - atr * self.cfg.STOP_LOSS_ATR_MULT

                # 触发条件
                should_exit = False
                exit_reason = None

                if current_price >= take_profit:
                    should_exit = True
                    exit_reason = 'take_profit'
                elif current_price <= stop_loss:
                    should_exit = True
                    exit_reason = 'stop_loss'
                elif position['hold_bars'] >= self.cfg.MAX_HOLD_BARS:
                    should_exit = True
                    exit_reason = 'max_hold_time'

                # 执行平仓
                if should_exit:
                    order_id = await self.tiger.place_sell_order(
                        ticker=ticker,
                        quantity=qty,
                    )

                    pnl = (current_price - entry_price) * qty
                    pnl_pct = (current_price - entry_price) / entry_price * 100

                    logger.info(
                        f"[TRADER] Exit {ticker}: {qty} @ ${current_price:.2f} "
                        f"(reason={exit_reason}, pnl=${pnl:.0f}, pnl%={pnl_pct:.2f}%)"
                    )

                    exit_orders.append({
                        'order_id': order_id,
                        'ticker': ticker,
                        'qty': qty,
                        'exit_price': current_price,
                        'exit_reason': exit_reason,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                    })

                    # 更新日内 P&L
                    self.daily_realized_pnl += pnl

                    # 更新日冲计数（平仓 = day trade）
                    self.day_trade_count += 1

                    # 移除已平仓头寸
                    del self.active_positions[ticker]

                else:
                    # 更新头寸信息
                    position['current_price'] = current_price
                    position['hold_bars'] = position.get('hold_bars', 0) + 1
                    position['unrealized_pnl'] = (current_price - entry_price) * qty

            except Exception as e:
                logger.warning(f"[TRADER] Exit check failed {ticker}: {e}")

        return exit_orders

    async def reconcile_positions(self) -> Dict:
        """
        对账：同步实际持仓和本地追踪状态

        Returns:
            对账结果
        """
        try:
            actual_positions = await self.tiger.get_positions()

            if not actual_positions:
                return {
                    'status': 'ok',
                    'reconciled': 0,
                    'tracked': len(self.active_positions),
                }

            # 过滤到仅有我们的 intraday 头寸（可以按 tag 或 symbol 过滤）
            intraday_tickers = set(self.cfg.UNIVERSE)
            for pos in actual_positions:
                ticker = pos.get('ticker') or pos.get('symbol')
                if ticker in intraday_tickers and ticker not in self.active_positions:
                    # 发现本地未追踪的持仓（意外订单或手动下单）
                    logger.warning(
                        f"[TRADER] Untracked position found: {ticker} {pos.get('quantity')} shares"
                    )

            return {
                'status': 'ok',
                'reconciled': len(actual_positions),
                'tracked': len(self.active_positions),
            }

        except Exception as e:
            logger.error(f"[TRADER] Reconciliation failed: {e}")
            return {'status': 'error', 'reason': str(e)}


# ============================================================
# Top-level Execute Function
# ============================================================

async def execute_intraday_trades(
    scores_result: Dict,
    auto_execute: bool = False,
) -> Dict:
    """
    盘中自动交易（铃铛）— 止盈止损 / 持仓上限 / watchlist+重试 / 平仓后优先补最强动能
    """
    if not auto_execute or not IntradayConfig.AUTO_EXECUTE:
        logger.info("[INTRADAY-EXEC] Auto-execute disabled, signal-only mode")
        return {'status': 'signal_only', 'scores': scores_result}

    cfg = IntradayConfig
    trader = IntradayTrader(account_label=cfg.ACCOUNT_LABEL)
    massive = get_massive_client()

    acct = await trader.get_account_info()
    if acct.get('status') != 'ok':
        logger.error("[TRADER] Cannot execute trades without account info")
        return {'status': 'error', 'reason': 'account_unavailable'}
    equity = acct['equity']

    all_scores: List[dict] = list(scores_result.get('all_scores') or scores_result.get('top') or [])
    round_num = int(scores_result.get('round') or 0)

    state = intraday_state_store.ensure_fresh_trading_day(intraday_state_store.load_state())
    entry_scores: Dict[str, float] = {k: float(v) for k, v in (state.get("entry_scores") or {}).items()}
    partial_done: Dict[str, bool] = dict(state.get("partial_tickers") or {})
    retry_list: List[Dict] = list(state.get("retry") or [])

    watchlist = state.get("watchlist") or []
    watch_tickers = {w.get("ticker") for w in watchlist if w.get("ticker")}

    # 开盘首轮：保存当日动能 Top20
    if all_scores and (round_num == 1 or not state.get("watchlist")):
        wl = []
        for i, s in enumerate(all_scores[: cfg.WATCHLIST_SIZE]):
            wl.append({
                "ticker": s.get("ticker"),
                "score": float(s.get("total_score", 0)),
                "rank": int(s.get("rank", i + 1)),
            })
        state["watchlist"] = wl
        watchlist = wl
        watch_tickers = {w.get("ticker") for w in watchlist if w.get("ticker")}
        logger.info(
            f"[INTRADAY] Saved daily watchlist Top{cfg.WATCHLIST_SIZE} "
            f"(round={round_num}): {list(watch_tickers)[:8]}..."
        )

    # 30 分钟重试窗口：过期剔除
    now_et = datetime.now(ET)
    retry_kept = []
    for r in retry_list:
        tkr = r.get("ticker")
        fa = r.get("failed_at_et")
        if not tkr or not fa:
            continue
        try:
            failed_dt = datetime.fromisoformat(fa)
            if now_et - failed_dt <= timedelta(minutes=cfg.ENTRY_RETRY_MINUTES):
                retry_kept.append(r)
            else:
                logger.info(f"[INTRADAY] Retry expired for {tkr} (>{cfg.ENTRY_RETRY_MINUTES}m)")
        except Exception:
            retry_kept.append(r)
    retry_list = retry_kept
    state["retry"] = retry_list
    retry_tickers = {r.get("ticker") for r in retry_list if r.get("ticker")}

    exits_log: List[Dict] = []
    had_full_exit = False
    universe = set(cfg.UNIVERSE)

    async def _pos_list():
        return await trader.tiger.get_positions() or []

    # ---------- 持仓管理（分三轮，避免数量与成交不同步）----------
    try:
        # Pass A: 亏损 ≥0.5% 全平
        for pos in await _pos_list():
            pos_ticker = pos.get("ticker") or pos.get("symbol")
            if not pos_ticker or pos_ticker not in universe:
                continue
            pos_ticker = str(pos_ticker).upper().strip()
            qty = int(pos.get("quantity", 0) or 0)
            avg = float(pos.get("average_cost", 0) or 0)
            last = float(pos.get("latest_price", 0) or 0)
            if qty <= 0 or avg <= 0:
                continue
            if last <= 0:
                last = avg
            pnl_pct = (last - avg) / avg
            if pnl_pct <= cfg.FULL_STOP_LOSS_PCT:
                sr = await trader.tiger.place_sell_order(pos_ticker, qty)
                exits_log.append({
                    "ticker": pos_ticker, "qty": qty, "reason": "stop_loss_pct",
                    "pnl_pct": round(pnl_pct * 100, 3), "order": sr,
                })
                entry_scores.pop(pos_ticker, None)
                partial_done.pop(pos_ticker, None)
                had_full_exit = True
                logger.warning(f"[EXIT] {pos_ticker} stop_loss_pct pnl={pnl_pct*100:.2f}%")

        # Pass B: 盈利≥1% + 动能 → 减半（每票仅一次）
        for pos in await _pos_list():
            pos_ticker = str(pos.get("ticker") or pos.get("symbol") or "").upper().strip()
            if not pos_ticker or pos_ticker not in universe:
                continue
            qty = int(pos.get("quantity", 0) or 0)
            avg = float(pos.get("average_cost", 0) or 0)
            last = float(pos.get("latest_price", 0) or 0)
            if qty <= 0 or avg <= 0:
                continue
            if last <= 0:
                last = avg
            pnl_pct = (last - avg) / avg
            if (
                pnl_pct >= cfg.PARTIAL_PROFIT_TRIGGER_PCT
                and not partial_done.get(pos_ticker)
                and _momentum_better(cfg, pos_ticker, all_scores, entry_scores)
            ):
                half = max(1, int(qty * cfg.PARTIAL_EXIT_FRACTION))
                if half >= qty:
                    half = max(1, qty // 2)
                sr = await trader.tiger.place_sell_order(pos_ticker, half)
                partial_done[pos_ticker] = True
                had_full_exit = True
                exits_log.append({
                    "ticker": pos_ticker, "qty": half, "reason": "partial_profit_momentum",
                    "pnl_pct": round(pnl_pct * 100, 3), "order": sr,
                })
                logger.info(f"[EXIT] {pos_ticker} partial 50% ({half}) pnl={pnl_pct*100:.2f}%")

        # Pass C: 剩余仓位 ATR 止盈（参考当前持仓成本价）
        for pos in await _pos_list():
            pos_ticker = str(pos.get("ticker") or pos.get("symbol") or "").upper().strip()
            if not pos_ticker or pos_ticker not in universe:
                continue
            qty = int(pos.get("quantity", 0) or 0)
            avg = float(pos.get("average_cost", 0) or 0)
            if qty <= 0 or avg <= 0:
                continue
            hit, px = await _atr_take_profit_hit(massive, pos_ticker, avg, cfg)
            if hit:
                sr = await trader.tiger.place_sell_order(pos_ticker, qty)
                exits_log.append({
                    "ticker": pos_ticker, "qty": qty, "reason": "take_profit_atr",
                    "price": px, "order": sr,
                })
                entry_scores.pop(pos_ticker, None)
                partial_done.pop(pos_ticker, None)
                had_full_exit = True
                logger.info(f"[EXIT] {pos_ticker} take_profit_atr @ ~{px:.2f}")

    except Exception as e:
        logger.error(f"[INTRADAY] exit phase error: {e}", exc_info=True)

    # 刷新持仓集合
    positions = await trader.tiger.get_positions() or []
    held_tickers = {
        str(p.get("ticker") or p.get("symbol")).upper().strip()
        for p in positions
        if int(p.get("quantity", 0) or 0) > 0
    }
    n_held = len(held_tickers)
    slots = max(0, cfg.MAX_CONCURRENT_POSITIONS - n_held)

    # 若本轮发生过平仓（含减半），优先为「当前评分第一且未持有」补一仓
    priority_ticker: Optional[str] = None
    if had_full_exit:
        for s in all_scores:
            tk = s.get("ticker")
            if not tk:
                continue
            tk = str(tk).upper().strip()
            if tk not in held_tickers and float(s.get("total_score", 0)) >= cfg.MIN_SCORE_THRESHOLD:
                priority_ticker = tk
                break

    # ---------- 建仓候选：priority → retry → watchlist 顺序 ----------
    ordered = [s for s in all_scores if float(s.get("total_score", 0)) >= cfg.MIN_SCORE_THRESHOLD]

    def _allowed_entry(ticker: str, force_priority: bool) -> bool:
        if ticker in held_tickers:
            return False
        if force_priority and priority_ticker and ticker == priority_ticker:
            return True
        if ticker in retry_tickers:
            return True
        if ticker in watch_tickers:
            return True
        return False

    candidates: List[dict] = []
    seen = set()
    if priority_ticker:
        for s in ordered:
            if s.get("ticker") and str(s["ticker"]).upper().strip() == priority_ticker:
                candidates.append(s)
                seen.add(priority_ticker)
                break
    for s in ordered:
        t = str(s.get("ticker", "")).upper().strip()
        if not t or t in seen:
            continue
        if _allowed_entry(t, False):
            candidates.append(s)
            seen.add(t)

    planned = min(len(candidates), slots, cfg.MAX_CONCURRENT_POSITIONS)
    if planned <= 0:
        batch = []
        total_score_sum = 1.0
    else:
        batch = candidates[:planned]
        total_score_sum = sum(max(0.001, float(s.get("total_score", 0))) for s in batch)
        if total_score_sum <= 0:
            total_score_sum = 1.0

    entries: List[Dict] = []
    for item in batch:
        ticker = str(item.get("ticker")).upper().strip()
        try:
            latest_price = float(item.get("latest_price", 0))
            total_score_val = float(item.get("total_score", 0))
        except (TypeError, ValueError):
            entries.append({"status": "error", "ticker": ticker, "reason": "conversion_error"})
            continue

        pr = priority_ticker and ticker == priority_ticker
        if not _allowed_entry(ticker, pr):
            continue

        er = await trader.execute_entry(
            ticker=ticker,
            current_price=latest_price,
            score=total_score_val,
            total_score=total_score_sum,
            account_equity=equity,
            planned_entries=planned,
            existing_tickers=held_tickers,
        )
        entries.append(er)
        if er.get("status") == "ok":
            entry_scores[ticker] = total_score_val
            held_tickers.add(ticker)
            n_held += 1
            slots = max(0, cfg.MAX_CONCURRENT_POSITIONS - n_held)
            retry_list = [x for x in retry_list if x.get("ticker") != ticker]
        elif (
            ticker in watch_tickers
            and er.get("status") in ("skip", "error")
            and er.get("reason") != "already_in_position"
        ):
            if not any(x.get("ticker") == ticker for x in retry_list):
                retry_list.append({
                    "ticker": ticker,
                    "failed_at_et": now_et.isoformat(),
                })
                logger.info(
                    f"[INTRADAY] Watchlist entry failed → retry queue {ticker} reason={er.get('reason')}"
                )

    state["entry_scores"] = entry_scores
    state["partial_tickers"] = partial_done
    state["retry"] = retry_list
    intraday_state_store.save_state(state)

    reconcile = await trader.reconcile_positions()
    loss_check = await trader.check_daily_loss_limit()
    ratio_check = await trader.check_maintenance_ratio(equity)
    pdt_check = trader.check_day_trade_limit()

    return {
        "status": "ok",
        "round": scores_result.get("round"),
        "timestamp": datetime.now(ET).isoformat(),
        "entries": entries,
        "exits": exits_log,
        "watchlist_size": len(watch_tickers),
        "retry_queue": [r.get("ticker") for r in retry_list],
        "priority_after_exit": priority_ticker,
        "active_positions": trader.active_positions,
        "reconcile": reconcile,
        "risk_summary": {
            "daily_pnl": round(loss_check["daily_pnl"], 2),
            "daily_pnl_pct": round(loss_check["daily_pnl_pct"], 2),
            "daily_loss_limit_pct": 2.0,
            "loss_status": loss_check["status"],
            "maintenance_ratio": round(ratio_check["ratio"], 3),
            "maintenance_status": ratio_check["status"],
            "day_trades": pdt_check["count"],
            "day_trade_limit": pdt_check["allowed"],
            "trading_allowed": (
                loss_check["status"] != "critical" and ratio_check["status"] != "critical"
            ),
        },
    }
