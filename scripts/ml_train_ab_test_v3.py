"""
StockQueen ML Enhancement — V3 Walk-Forward A/B Test
=====================================================
ML-V3A: Asymmetric labels — amplifies upside signals to reward explosive winners

Changes from ML-V2:
  - Label: asymmetric z-score  (z * 1.5 if positive, z * 0.5 if negative)
  - Objective: rank:pairwise (same as V2)
  - Features: base_17 + offensive_5 (same as V2)
  - Goal: fix bull-market underperformance while keeping bear protection

Walk-Forward Windows (expanding):
  W1: Train 2018-2019  →  Test 2020 (COVID crash — V2 already good here)
  W2: Train 2018-2020  →  Test 2021 (strong bull — V2 -25pp gap)
  W3: Train 2018-2021  →  Test 2022 (bear/choppy)
  W4: Train 2018-2022  →  Test 2023 (recovery bull — V2 -13pp gap)
  W5: Train 2018-2023  →  Test 2024 (bull — V2 -15pp gap)

Pass criteria (V3 launch gate):
  - OOS avg return >= baseline avg return (no drag)
  - OOS avg Sharpe >= baseline - 0.10

Usage:
    cd StockQueen
    python scripts/ml_train_ab_test_v3.py
"""

import asyncio
import json
import os
import sys
import time
import numpy as np
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 指向主仓库磁盘缓存（worktree 默认路径不对）──
# 路径: worktree/ → worktrees/ → .claude/ → StockQueen/ → .cache/av
_main_cache = PROJECT_ROOT.parent.parent.parent / ".cache" / "av"
if _main_cache.exists() and "AV_CACHE_DIR" not in os.environ:
    os.environ["AV_CACHE_DIR"] = str(_main_cache)
    print(f"[cache] 使用主仓库 AV 磁盘缓存: {_main_cache} ({len(list(_main_cache.iterdir()))} 文件)")

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    stream=sys.stdout,
)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.ml_scorer").setLevel(logging.INFO)

logger = logging.getLogger("ml_train_v3")

RESULTS_DIR = PROJECT_ROOT / "scripts" / "stress_test_results"
RESULTS_DIR.mkdir(exist_ok=True)

WINDOWS = [
    {
        "name": "W1",
        "train_start": "2018-01-01", "train_end": "2019-12-31",
        "test_start": "2020-01-01", "test_end": "2020-12-31",
    },
    {
        "name": "W2",
        "train_start": "2018-01-01", "train_end": "2020-12-31",
        "test_start": "2021-01-01", "test_end": "2021-12-31",
    },
    {
        "name": "W3",
        "train_start": "2018-01-01", "train_end": "2021-12-31",
        "test_start": "2022-01-01", "test_end": "2022-12-31",
    },
    {
        "name": "W4",
        "train_start": "2018-01-01", "train_end": "2022-12-31",
        "test_start": "2023-01-01", "test_end": "2023-12-31",
    },
    {
        "name": "W5",
        "train_start": "2018-01-01", "train_end": "2023-12-31",
        "test_start": "2024-01-01", "test_end": "2024-12-31",
    },
]

TOP_N = 6
HOLDING_BONUS = 0.0
ML_RERANK_POOL = 10

# ML-V2 baseline for comparison (from ml_ab_test_results_ml-v2.json)
V2_WINDOW_RETURNS = {
    "W1": {"baseline": 0.0837, "ml": 0.2908},
    "W2": {"baseline": 0.7719, "ml": 0.5186},
    "W3": {"baseline": 0.1595, "ml": 0.1353},
    "W4": {"baseline": 0.4391, "ml": 0.3083},
    "W5": {"baseline": 0.3221, "ml": 0.1753},
}


def _fmt_pct(v):
    return f"{v:+.1%}" if v is not None else "N/A"

def _fmt_f(v, d=2):
    return f"{v:.{d}f}" if v is not None else "N/A"


async def run_single_backtest(start, end, prefetched, ml_enhance=False,
                              ml_ranker=None, collect_snapshots=None):
    from app.services.rotation_service import run_rotation_backtest
    return await run_rotation_backtest(
        start_date=start,
        end_date=end,
        top_n=TOP_N,
        holding_bonus=HOLDING_BONUS,
        _prefetched=prefetched,
        ml_enhance=ml_enhance,
        ml_ranker=ml_ranker,
        ml_rerank_pool=ML_RERANK_POOL,
        _collect_snapshots=collect_snapshots,
    )


async def fetch_data_once():
    from app.services.rotation_service import _fetch_backtest_data
    logger.info("拉取回测数据（一次性）...")
    t0 = time.time()
    data = await _fetch_backtest_data("2018-01-01", "2026-03-01")
    elapsed = time.time() - t0
    if "error" in data:
        logger.error(f"数据拉取失败: {data['error']}")
        return None
    n = len(data.get("histories", {}))
    logger.info(f"数据就绪: {n} 只标的, 耗时 {elapsed:.0f}s")
    return data


def extract_metrics(result: dict) -> dict:
    if "error" in result:
        return {"error": result["error"]}
    return {
        "cumulative_return": result.get("cumulative_return", 0),
        "annualized_return": result.get("annualized_return", 0),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "max_drawdown": result.get("max_drawdown", 0),
        "total_trades": result.get("total_trades", 0),
        "win_rate": result.get("win_rate", 0),
    }


async def main():
    logger.info("=" * 70)
    logger.info("StockQueen ML-V3A — 非对称标签攻击型排序模型 Walk-Forward A/B 测试")
    logger.info("改进：y = z*1.5 (上行) / z*0.5 (下行)  → 模型更贪婪追爆发票")
    logger.info("=" * 70)

    prefetched = await fetch_data_once()
    if prefetched is None:
        return

    histories = prefetched["histories"]
    all_results = []

    for window in WINDOWS:
        wname = window["name"]
        v2_ref = V2_WINDOW_RETURNS.get(wname, {})

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"窗口 {wname}: 训练 {window['train_start']}~{window['train_end']}")
        logger.info(f"           测试 {window['test_start']}~{window['test_end']}")
        if v2_ref:
            v2_gap = v2_ref['ml'] - v2_ref['baseline']
            logger.info(f"           V2 对比: ML={_fmt_pct(v2_ref['ml'])} vs Base={_fmt_pct(v2_ref['baseline'])} (差{_fmt_pct(v2_gap)})")
        logger.info("=" * 60)

        # ── Phase 1: 收集训练快照 ──
        logger.info(f"[{wname}] Phase 1: 收集训练数据快照...")
        train_snapshots = []
        t0 = time.time()

        train_result = await run_single_backtest(
            window["train_start"], window["train_end"],
            prefetched, ml_enhance=False,
            collect_snapshots=train_snapshots,
        )
        train_time = time.time() - t0
        logger.info(
            f"[{wname}] 训练期 baseline: "
            f"Sharpe={_fmt_f(train_result.get('sharpe_ratio'))}, "
            f"收益={_fmt_pct(train_result.get('cumulative_return'))}, "
            f"快照={len(train_snapshots)}周 ({train_time:.0f}s)"
        )

        # ── Phase 2: 训练 V3A 非对称排序模型 ──
        logger.info(f"[{wname}] Phase 2: 训练 V3A 非对称标签模型...")
        from app.services.ml_scorer import MLRanker, build_training_data

        X_train, y_train, groups_train = build_training_data(
            train_snapshots, histories, lookahead_days=5,
            asymmetric=True,  # V3A: 非对称放大
        )
        logger.info(
            f"[{wname}] 训练数据: {len(X_train)} 样本, {len(groups_train)} 周"
            + (f", label范围 [{y_train.min():.2f}, {y_train.max():.2f}]"
               f" (非对称后上行最大={y_train[y_train>0].max():.2f} 下行最小={y_train[y_train<0].min():.2f})"
               if len(y_train) > 0 else "")
        )

        ranker = MLRanker()
        train_metrics = {"error": "insufficient_data"}
        if len(X_train) >= 50:
            train_metrics = ranker.train(X_train, y_train, groups_train)
            logger.info(
                f"[{wname}] 模型训练完成: "
                f"corr={_fmt_f(train_metrics.get('correlation'), 3)}, "
                f"rank_spread={_fmt_f(train_metrics.get('rank_spread_train'), 3)}"
            )

            importance = train_metrics.get("feature_importance", {})
            top_feats = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.info(
                f"[{wname}] Top特征: "
                + ", ".join(f"{k}={v:.3f}" for k, v in top_feats)
            )
        else:
            logger.warning(f"[{wname}] 训练数据不足，跳过ML")

        # ── Phase 3: A/B 对比测试 ──
        logger.info(f"[{wname}] Phase 3: 运行A/B测试...")

        t0 = time.time()
        baseline_result = await run_single_backtest(
            window["test_start"], window["test_end"],
            prefetched, ml_enhance=False,
        )
        baseline_time = time.time() - t0
        baseline_metrics = extract_metrics(baseline_result)

        ml_metrics = {"error": "no_model"}
        ml_time = 0
        if ranker.model is not None:
            t0 = time.time()
            ml_result = await run_single_backtest(
                window["test_start"], window["test_end"],
                prefetched, ml_enhance=True, ml_ranker=ranker,
            )
            ml_time = time.time() - t0
            ml_metrics = extract_metrics(ml_result)

        # ── Phase 4: 对比输出（含 V2 参照）──
        logger.info("")
        logger.info(f"[{wname}] ── A/B 对比（测试期） ──")
        logger.info(f"{'指标':<25} {'Baseline':>12} {'V3A-ML':>12} {'差值':>12} {'V2差值':>12}")
        logger.info("-" * 75)

        has_ml = isinstance(ml_metrics, dict) and "error" not in ml_metrics

        for metric_key, label in [
            ("cumulative_return", "累计收益"),
            ("annualized_return", "年化收益"),
            ("sharpe_ratio", "Sharpe比率"),
            ("max_drawdown", "最大回撤"),
        ]:
            bv = baseline_metrics.get(metric_key, 0)

            if not has_ml:
                mv_str = delta_str = v2_delta_str = "N/A"
            else:
                mv = ml_metrics.get(metric_key, 0)
                if metric_key in ("cumulative_return", "annualized_return", "max_drawdown"):
                    mv_str = f"{mv:+.1%}"
                    delta_str = f"{mv - bv:+.1%}"
                    # V2 comparison for cumulative return
                    if metric_key == "cumulative_return" and v2_ref:
                        v2_delta_str = f"{mv - v2_ref['ml']:+.1%}"
                    else:
                        v2_delta_str = ""
                else:
                    mv_str = f"{mv:.2f}"
                    delta_str = f"{mv - bv:+.2f}"
                    v2_delta_str = ""

            if metric_key in ("cumulative_return", "annualized_return", "max_drawdown"):
                bv_str = f"{bv:+.1%}"
            else:
                bv_str = f"{bv:.2f}"

            logger.info(f"{label:<25} {bv_str:>12} {mv_str:>12} {delta_str:>12} {v2_delta_str:>12}")

        if has_ml and v2_ref:
            ret_v3 = ml_metrics.get("cumulative_return", 0)
            ret_v2 = v2_ref["ml"]
            logger.info(f"  → V3A vs V2: {_fmt_pct(ret_v3 - ret_v2)} （{'✓ 改善' if ret_v3 > ret_v2 else '✗ 退步'}）")

        window_result = {
            "window": wname,
            "train_period": f"{window['train_start']}~{window['train_end']}",
            "test_period": f"{window['test_start']}~{window['test_end']}",
            "train_samples": int(len(X_train)),
            "train_groups": int(len(groups_train)),
            "train_model_metrics": {
                k: v for k, v in (train_metrics or {}).items()
                if k != "feature_importance"
            },
            "feature_importance": train_metrics.get("feature_importance", {}),
            "baseline": baseline_metrics,
            "ml_enhanced": ml_metrics,
            "v2_ml_return": v2_ref.get("ml") if v2_ref else None,
            "baseline_time": round(baseline_time, 1),
            "ml_time": round(ml_time, 1),
        }
        all_results.append(window_result)

    # ── Overall Summary ──
    logger.info("")
    logger.info("=" * 70)
    logger.info("总体结果 (ML-V3A 非对称标签)")
    logger.info("=" * 70)

    b_sharpes, m_sharpes = [], []
    b_returns, m_returns = [], []
    b_drawdowns, m_drawdowns = [], []

    for r in all_results:
        b = r.get("baseline", {})
        m = r.get("ml_enhanced", {})
        if "error" not in b:
            b_sharpes.append(b.get("sharpe_ratio", 0))
            b_returns.append(b.get("cumulative_return", 0))
            b_drawdowns.append(b.get("max_drawdown", 0))
        if isinstance(m, dict) and "error" not in m:
            m_sharpes.append(m.get("sharpe_ratio", 0))
            m_returns.append(m.get("cumulative_return", 0))
            m_drawdowns.append(m.get("max_drawdown", 0))

    v2_avg_return = np.mean(list(v["ml"] for v in V2_WINDOW_RETURNS.values()))

    if b_sharpes:
        logger.info(f"Baseline    — 平均Sharpe: {np.mean(b_sharpes):.2f}, "
                     f"平均收益: {np.mean(b_returns):+.1%}, "
                     f"平均回撤: {np.mean(b_drawdowns):+.1%}")
    if m_sharpes:
        logger.info(f"V3A ML      — 平均Sharpe: {np.mean(m_sharpes):.2f}, "
                     f"平均收益: {np.mean(m_returns):+.1%}, "
                     f"平均回撤: {np.mean(m_drawdowns):+.1%}")
    logger.info(f"V2 ML (参照) — 平均收益: {v2_avg_return:+.1%}")

    if b_sharpes and m_sharpes:
        s_delta = np.mean(m_sharpes) - np.mean(b_sharpes)
        r_delta = np.mean(m_returns) - np.mean(b_returns)
        v3_vs_v2 = np.mean(m_returns) - v2_avg_return
        logger.info("")
        logger.info(f"Sharpe 变化 vs Baseline: {s_delta:+.2f}")
        logger.info(f"收益 变化 vs Baseline:   {r_delta:+.1%}")
        logger.info(f"收益 变化 vs V2:         {v3_vs_v2:+.1%}")
        logger.info("")

        # Pass criteria check
        passes_return = np.mean(m_returns) >= np.mean(b_returns)
        passes_sharpe = np.mean(m_sharpes) >= np.mean(b_sharpes) - 0.10
        logger.info("── 上线标准检查 ──")
        logger.info(f"  OOS收益 >= Baseline: {'✓ PASS' if passes_return else '✗ FAIL'} "
                     f"({np.mean(m_returns):+.1%} vs {np.mean(b_returns):+.1%})")
        logger.info(f"  OOS Sharpe >= Baseline-0.10: {'✓ PASS' if passes_sharpe else '✗ FAIL'} "
                     f"({np.mean(m_sharpes):.2f} vs {np.mean(b_sharpes):.2f})")
        if passes_return and passes_sharpe:
            logger.info("✓✓ V3A 通过上线标准！可进入 Phase 4 部署")
        else:
            logger.info("✗ V3A 未通过，考虑叠加方案 B（Regime-aware）或方案 C（特征裁剪）")

    # Feature importance (last window)
    if all_results:
        last_fi = all_results[-1].get("feature_importance", {})
        if last_fi:
            logger.info("")
            logger.info("最后窗口特征重要性排名（V3A）:")
            sorted_fi = sorted(last_fi.items(), key=lambda x: x[1], reverse=True)
            for rank, (feat, imp) in enumerate(sorted_fi[:10], 1):
                bar = "█" * int(imp * 50)
                logger.info(f"  {rank:2d}. {feat:<22s} {imp:.3f} {bar}")

    # Save results
    output_path = RESULTS_DIR / "ml_ab_test_results_ml-v3a.json"
    with open(output_path, "w") as f:
        json.dump({
            "version": "ml-v3a_asymmetric_ranker",
            "timestamp": datetime.now().isoformat(),
            "config": {
                "top_n": TOP_N,
                "holding_bonus": HOLDING_BONUS,
                "ml_rerank_pool": ML_RERANK_POOL,
                "objective": "rank:pairwise",
                "label": "asymmetric_zscore (pos*1.5, neg*0.5)",
                "features": "base_17 + offensive_5",
                "asymmetric": True,
            },
            "windows": all_results,
            "summary": {
                "baseline_avg_sharpe": float(np.mean(b_sharpes)) if b_sharpes else None,
                "ml_avg_sharpe": float(np.mean(m_sharpes)) if m_sharpes else None,
                "baseline_avg_return": float(np.mean(b_returns)) if b_returns else None,
                "ml_avg_return": float(np.mean(m_returns)) if m_returns else None,
                "sharpe_delta": float(np.mean(m_sharpes) - np.mean(b_sharpes))
                    if b_sharpes and m_sharpes else None,
                "return_delta": float(np.mean(m_returns) - np.mean(b_returns))
                    if b_returns and m_returns else None,
                "v2_avg_return": float(v2_avg_return),
                "v3a_vs_v2": float(np.mean(m_returns) - v2_avg_return)
                    if m_returns else None,
            },
        }, f, indent=2, default=str)

    logger.info(f"\n结果保存至: {output_path}")

    if all_results and ranker.model is not None:
        ranker.save()
        logger.info("最新模型保存至: models/ml_ranker/")


if __name__ == "__main__":
    asyncio.run(main())
