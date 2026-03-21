"""
StockQueen Newsletter - 数据获取模块
从 FastAPI 后端 API 获取实时数据，静态 JSON 作为后备
"""

import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("newsletter.data_fetcher")

# 默认 API 基础 URL
DEFAULT_API_BASE = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")

# 静态数据后备路径
SITE_DATA_DIR = Path(__file__).parent.parent.parent / "site" / "data"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


class DataFetcher:
    """从 API 和本地文件获取 Newsletter 所需数据"""

    def __init__(self, api_base: Optional[str] = None, timeout: float = 30.0):
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API 数据
    # ------------------------------------------------------------------

    async def fetch_current_signals(self) -> dict:
        """
        获取当前活跃持仓（含 entry_price, stop_loss, take_profit）
        GET /api/public/signals
        返回: {date, market_regime, positions: [{ticker, entry_price, current_price, return_pct, stop_loss, take_profit, signal_date}]}
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.api_base}/api/public/signals")
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"[API] 获取当前持仓: {len(data.get('positions', []))} 个, 市场状态: {data.get('market_regime')}")
                return data
        except Exception as e:
            logger.warning(f"[API] 获取当前持仓失败: {e}, 使用本地后备数据")
            return self._fallback_signals()

    async def fetch_signal_history(self) -> dict:
        """
        获取历史已平仓交易
        GET /api/public/signal-history
        返回: {summary: {total_trades, wins, losses, win_rate, avg_return, avg_hold_days}, trades: [...]}
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.api_base}/api/public/signal-history")
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"[API] 获取历史交易: {data.get('summary', {}).get('total_trades', 0)} 笔")
                return data
        except Exception as e:
            logger.warning(f"[API] 获取历史交易失败: {e}, 返回空数据")
            return {"summary": {}, "trades": []}

    # ------------------------------------------------------------------
    # 静态 JSON 数据（回测/年度表现）
    # ------------------------------------------------------------------

    def load_backtest_summary(self) -> dict:
        """加载回测汇总数据 (backtest-summary.json)"""
        path = SITE_DATA_DIR / "backtest-summary.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[FILE] 加载 backtest-summary.json 失败: {e}")
            return {}

    def load_yearly_performance(self) -> dict:
        """加载年度表现数据 (yearly-performance.json)"""
        path = SITE_DATA_DIR / "yearly-performance.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[FILE] 加载 yearly-performance.json 失败: {e}")
            return {}

    def load_latest_blogs(self) -> list:
        """加载最新博客文章列表 (blog-posts.json)，供 newsletter 引用"""
        path = SITE_DATA_DIR / "blog-posts.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            posts = data if isinstance(data, list) else data.get("posts", [])
            # 只取最新2篇
            return posts[:2]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 快照对比：检测新买入/卖出信号
    # ------------------------------------------------------------------

    def load_last_snapshot(self) -> dict:
        """加载上周快照（用于对比生成新信号）"""
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_file = SNAPSHOT_DIR / "last_snapshot.json"
        if snapshot_file.exists():
            try:
                with open(snapshot_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[SNAPSHOT] 加载快照失败: {e}")
        return {"positions": [], "date": None}

    def save_snapshot(self, current_data: dict):
        """保存当前数据为快照，供下周对比"""
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_file = SNAPSHOT_DIR / "last_snapshot.json"
        snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "positions": current_data.get("positions", []),
            "market_regime": current_data.get("market_regime", "UNKNOWN"),
        }
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        logger.info(f"[SNAPSHOT] 快照已保存: {snapshot_file}")

    def detect_signal_changes(self, current_positions: list, last_snapshot: dict) -> dict:
        """
        对比当前持仓与上周快照，检测新买入/卖出信号
        返回:
        {
            "new_entries": [{"ticker": "NVDA", "entry_price": 125.50, ...}],
            "new_exits": [{"ticker": "AAPL", ...}],
            "held": [{"ticker": "MSFT", ...}]
        }
        """
        current_tickers = {p["ticker"] for p in current_positions}
        last_positions = last_snapshot.get("positions", [])
        last_tickers = {p["ticker"] for p in last_positions}

        # 新买入 = 当前有、上周没有
        new_entries = [p for p in current_positions if p["ticker"] not in last_tickers]

        # 新卖出 = 上周有、当前没有
        new_exits = [p for p in last_positions if p["ticker"] not in current_tickers]

        # 继续持有 = 两周都有
        held = [p for p in current_positions if p["ticker"] in last_tickers]

        logger.info(f"[SIGNAL] 新买入: {len(new_entries)}, 新卖出: {len(new_exits)}, 继续持有: {len(held)}")
        return {
            "new_entries": new_entries,
            "new_exits": new_exits,
            "held": held,
        }

    # ------------------------------------------------------------------
    # 从历史交易中提取本周平仓记录
    # ------------------------------------------------------------------

    def extract_recent_exits(self, trades: list, days: int = 7) -> list:
        """从历史交易列表中提取最近N天内平仓的交易"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [t for t in trades if t.get("exit_date", "") >= cutoff]
        logger.info(f"[HISTORY] 最近{days}天平仓: {len(recent)} 笔")
        return recent

    # ------------------------------------------------------------------
    # 组装完整的 Newsletter 数据包
    # ------------------------------------------------------------------

    async def fetch_all(self) -> dict:
        """
        一次性获取所有 Newsletter 所需数据
        返回完整数据包供模板渲染
        """
        # 并行获取 API 数据
        signals = await self.fetch_current_signals()
        history = await self.fetch_signal_history()

        # 本地数据
        backtest = self.load_backtest_summary()
        yearly = self.load_yearly_performance()
        blogs = self.load_latest_blogs()

        # 优先：从 Supabase rotation_snapshots 对比买卖变动（最权威来源）
        db_changes = await self.fetch_rotation_changes_from_db()

        current_positions = signals.get("positions", [])
        regime = signals.get("market_regime", "UNKNOWN")

        if db_changes:
            # 从 DB 对比结果中构建 new_entries / new_exits
            new_entries_tickers = set(db_changes["new_entries_tickers"])
            new_exits_tickers = set(db_changes["new_exits_tickers"])
            held_tickers = set(db_changes["held_tickers"])

            new_entries = [p for p in current_positions if p["ticker"] in new_entries_tickers]
            new_exits_raw = [p for p in current_positions if p["ticker"] in new_exits_tickers]
            # new_exits 已不在当前持仓中，仅保留 ticker + 进仓价（无当前价）
            last_snap = self.load_last_snapshot()
            last_positions = last_snap.get("positions", [])
            new_exits = [p for p in last_positions if p["ticker"] in new_exits_tickers]
            if not new_exits:
                new_exits = [{"ticker": t, "entry_price": None, "return_pct": None} for t in new_exits_tickers]
            held = [p for p in current_positions if p["ticker"] in held_tickers]
            # 若 DB 有明确 regime，且 API 返回 UNKNOWN，则用 DB 的
            if regime == "UNKNOWN" and db_changes.get("regime"):
                regime = db_changes["regime"].upper()
        else:
            # 降级：用本地快照对比
            last_snapshot = self.load_last_snapshot()
            changes = self.detect_signal_changes(current_positions, last_snapshot)
            new_entries = changes["new_entries"]
            new_exits = changes["new_exits"]
            held = changes["held"]

        # 最近平仓交易
        recent_exits = self.extract_recent_exits(history.get("trades", []))

        # 组装数据包
        data = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "week_number": datetime.now().isocalendar()[1],
            "year": datetime.now().year,

            # 市场状态
            "market_regime": regime,

            # 当前持仓（完整，含价格）
            "positions": current_positions,

            # 信号变化
            "new_entries": new_entries,
            "new_exits": new_exits,
            "held_positions": held,

            # 最近平仓交易（含收益）
            "recent_exits": recent_exits,

            # 历史汇总统计
            "trade_summary": history.get("summary", {}),

            # 回测/年度表现
            "backtest": backtest,
            "yearly": yearly,

            # 最新博客（供 newsletter 引用，每周2篇）
            "latest_blogs": blogs,
        }

        # 保存本次快照（含 regime）
        signals_with_regime = {**signals, "market_regime": regime}
        self.save_snapshot(signals_with_regime)

        return data

    # ------------------------------------------------------------------
    # 后备数据
    # ------------------------------------------------------------------

    def _fallback_signals(self) -> dict:
        """从本地快照加载后备数据（优先读取 regime）"""
        # 1. 先尝试从上周快照恢复 regime 和 positions
        snap = self.load_last_snapshot()
        if snap.get("positions"):
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "market_regime": snap.get("market_regime", "UNKNOWN"),
                "positions": snap["positions"],
            }
        # 2. 降级：读 latest-signals.json
        path = SITE_DATA_DIR / "latest-signals.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            positions = []
            for item in raw if isinstance(raw, list) else raw.get("positions", []):
                positions.append({
                    "ticker": item.get("ticker", ""),
                    "entry_price": item.get("entry_price", 0),
                    "current_price": item.get("current_price", item.get("latest_price", 0)),
                    "return_pct": item.get("return_pct", 0),
                    "stop_loss": item.get("stop_loss"),
                    "take_profit": item.get("take_profit"),
                    "signal_date": item.get("signal_date", item.get("entry_date", "")),
                })
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "market_regime": raw.get("market_regime", "UNKNOWN") if isinstance(raw, dict) else "UNKNOWN",
                "positions": positions,
            }
        except Exception as e:
            logger.error(f"[FALLBACK] 后备数据也加载失败: {e}")
            return {"date": datetime.now().strftime("%Y-%m-%d"), "market_regime": "UNKNOWN", "positions": []}

    async def fetch_rotation_changes_from_db(self) -> Optional[dict]:
        """
        直接从 Supabase rotation_snapshots 读取最近两次快照对比买卖变动。
        比 last_snapshot.json 更可靠，避免本地文件状态不一致问题。
        返回 {"new_entries_tickers", "new_exits_tickers", "held_tickers", "regime"} 或 None
        """
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from app.services.supabase_client import get_supabase
            supabase = get_supabase()
            resp = supabase.table("rotation_snapshots") \
                .select("selected_tickers,snapshot_date,regime,created_at") \
                .order("created_at", desc=True) \
                .limit(2) \
                .execute()
            rows = resp.data or []
            if len(rows) < 2:
                logger.warning("[DB] rotation_snapshots 少于2条记录，无法对比")
                return None
            current_tickers = set(rows[0].get("selected_tickers") or [])
            previous_tickers = set(rows[1].get("selected_tickers") or [])
            logger.info(f"[DB] 当前仓位: {current_tickers}, 上周仓位: {previous_tickers}")
            return {
                "new_entries_tickers": list(current_tickers - previous_tickers),
                "new_exits_tickers": list(previous_tickers - current_tickers),
                "held_tickers": list(current_tickers & previous_tickers),
                "regime": rows[0].get("regime", "UNKNOWN"),
                "snapshot_date": rows[0].get("snapshot_date", ""),
            }
        except Exception as e:
            logger.warning(f"[DB] 无法读取 rotation_snapshots 对比: {e}")
            return None
