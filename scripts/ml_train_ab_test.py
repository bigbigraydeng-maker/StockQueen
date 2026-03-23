"""
StockQueen ML Enhancement — Walk-Forward A/B Test
===================================================
ML-V3A: Asymmetric label ranker (production version)

V3A vs V2 difference:
  - Label: asymmetric z-score — upside ×1.5, downside ×0.5 (V3A)
    vs symmetric cross-sectional z-score (V2)
  - This teaches the model to care more about catching winners
    than avoiding losers

Walk-Forward Windows (expanding, mirrors production WF):
  W1: Train 2018-2019  →  Test 2020
  W2: Train 2018-2020  →  Test 2021
  W3: Train 2018-2021  →  Test 2022
  W4: Train 2018-2022  →  Test 2023
  W5: Train 2018-2023  →  Test 2024

Usage:
    cd StockQueen
    python scripts/ml_train_ab_test.py
"""

import asyncio
import json
import sys
import time
import numpy as np
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    stream=sys.stdout,
)
logging.getLogger("app.services.rotation_service").setLevel(logging.WARNING)
logging.getLogger("app.services.alphavantage_client").setLevel(logging.WARNING)
logging.getLogger("app.services.ml_scorer").setLevel(logging.INFO)

logger = logging.getLogger("ml_train_ab")

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

TOP_N = 3          # 生产配置（与 rotation_watchlist.py 一致）
HOLDING_BONUS = 0.0
ML_RERANK_POOL = 10


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
    logger.info("StockQueen ML 非对称标签排序模型 — Walk-Forward A/B 测试 ML-V3A")
    logger.info("=" * 70)

    prefetched = await fetch_data_once()
    if prefetched is None:
        return

    histories = prefetched["histories"]
    all_results = []

    for window in WINDOWS:
        wname = window["name"]
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"窗口 {wname}: 训练 {window['train_start']}~{window['train_end']}")
        logger.info(f"           测试 {window['test_start']}~{window['test_end']}")
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

        # Drop the last snapshot: its forward-return label looks 5 trading days
        # past the training end date, leaking into the test period.
        if len(train_snapshots) > 1:
            train_snapshots = train_snapshots[:-1]

        logger.info(
            f"[{wname}] 训练期 baseline: "
            f"Sharpe={_fmt_f(train_result.get('sharpe_ratio'))}, "
            f"收益={_fmt_pct(train_result.get('cumulative_return'))}, "
            f"快照={len(train_snapshots)}周（已去尾1周）"
            f"({train_time:.0f}s)"
        )

        # ── Phase 2: 训练 XGBoost Ranker ──
        logger.info(f"[{wname}] Phase 2: 训练攻击型排序模型...")
        from app.services.ml_scorer import MLRanker, build_training_data

        X_train, y_train, groups_train = build_training_data(
            train_snapshots, histories, lookahead_days=5, asymmetric=True  # V3A
        )
        logger.info(
            f"[{wname}] 训练数据: {len(X_train)} 样本, "
            f"{len(groups_train)} 周, "
            + (f"label范围 [{y_train.min():.2f}, {y_train.max():.2f}]"
               if len(y_train) > 0 else "无数据")
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

        # ── Phase 4: 对比输出 ──
        logger.info("")
        logger.info(f"[{wname}] ── A/B 对比（测试期） ──")
        logger.info(f"{'指标':<25} {'Baseline':>12} {'ML攻击型':>12} {'差值':>12}")
        logger.info("-" * 65)

        has_ml = isinstance(ml_metrics, dict) and "error" not in ml_metrics

        for metric_key, label in [
            ("cumulative_return", "累计收益"),
            ("annualized_return", "年化收益"),
            ("sharpe_ratio", "Sharpe比率"),
            ("max_drawdown", "最大回撤"),
            ("total_trades", "总交易次数"),
        ]:
            bv = baseline_metrics.get(metric_key, 0)

            if not has_ml:
                mv_str = "N/A"
                delta_str = "N/A"
            else:
                mv = ml_metrics.get(metric_key, 0)
                if metric_key in ("cumulative_return", "annualized_return", "max_drawdown"):
                    mv_str = f"{mv:+.1%}"
                    delta_str = f"{mv - bv:+.1%}"
                elif metric_key == "sharpe_ratio":
                    mv_str = f"{mv:.2f}"
                    delta_str = f"{mv - bv:+.2f}"
                else:
                    mv_str = f"{mv}"
                    delta_str = f"{int(mv - bv):+d}"

            if metric_key in ("cumulative_return", "annualized_return", "max_drawdown"):
                bv_str = f"{bv:+.1%}"
            elif metric_key == "sharpe_ratio":
                bv_str = f"{bv:.2f}"
            else:
                bv_str = f"{bv}"

            logger.info(f"{label:<25} {bv_str:>12} {mv_str:>12} {delta_str:>12}")

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
            "baseline_time": round(baseline_time, 1),
            "ml_time": round(ml_time, 1),
        }
        all_results.append(window_result)

    # ── Overall Summary ──
    logger.info("")
    logger.info("=" * 70)
    logger.info("总体结果")
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

    if b_sharpes:
        logger.info(f"Baseline   — 平均Sharpe: {np.mean(b_sharpes):.2f}, "
                     f"平均收益: {np.mean(b_returns):+.1%}, "
                     f"平均回撤: {np.mean(b_drawdowns):+.1%}")
    if m_sharpes:
        logger.info(f"ML攻击型  — 平均Sharpe: {np.mean(m_sharpes):.2f}, "
                     f"平均收益: {np.mean(m_returns):+.1%}, "
                     f"平均回撤: {np.mean(m_drawdowns):+.1%}")

    if b_sharpes and m_sharpes:
        s_delta = np.mean(m_sharpes) - np.mean(b_sharpes)
        r_delta = np.mean(m_returns) - np.mean(b_returns)
        logger.info(f"Sharpe 变化: {s_delta:+.2f}")
        logger.info(f"收益 变化: {r_delta:+.1%}")

        if r_delta > 0 and s_delta >= -0.1:
            logger.info("✓ ML攻击型模型提升了收益能力")
        elif s_delta > 0:
            logger.info("△ ML提升了Sharpe但收益变化不大")
        else:
            logger.info("✗ ML攻击型模型未能有效提升 — 需进一步调整")

    # Feature importance
    if all_results:
        last_fi = all_results[-1].get("feature_importance", {})
        if last_fi:
            logger.info("")
            logger.info("最后窗口特征重要性排名:")
            sorted_fi = sorted(last_fi.items(), key=lambda x: x[1], reverse=True)
            for rank, (feat, imp) in enumerate(sorted_fi[:10], 1):
                bar = "█" * int(imp * 50)
                logger.info(f"  {rank:2d}. {feat:<22s} {imp:.3f} {bar}")

    # Save
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
                "label": "asymmetric_zscore (upside×1.5, downside×0.5)",
                "features": "base_17 + offensive_5",
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
            },
        }, f, indent=2, default=str)

    logger.info(f"\n结果保存至: {output_path}")

    if all_results and ranker.model is not None:
        ranker.save()
        logger.info("最新模型保存至: models/ml_ranker/")


if __name__ == "__main__":
    asyncio.run(main())
