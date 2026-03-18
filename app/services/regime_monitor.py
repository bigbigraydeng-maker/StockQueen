"""
StockQueen — Regime Change Monitor

Runs daily after market close. Detects regime changes by comparing
the current regime against the last recorded regime in Supabase.
Sends an immediate Feishu alert when a transition is detected.

Table: regime_history
Columns: id, date (unique), regime, score, spy_price, signals (jsonb), created_at
"""

import logging
from datetime import date, timedelta

from app.database import get_db

logger = logging.getLogger(__name__)

TABLE = "regime_history"


async def check_regime_and_alert() -> dict:
    """
    Core monitor function — called daily by the scheduler.

    1. Compute current regime via detect_regime_details()
    2. Load last recorded regime from DB
    3. If changed → send Feishu alert + save new record
    4. If unchanged → save record silently

    Returns a summary dict for logging.
    """
    from app.services.rotation_service import detect_regime_details

    # --- Step 1: detect current regime ---
    details = await detect_regime_details()
    current_regime = details.get("regime", "unknown")
    score = details.get("score", 0)
    spy_price = details.get("spy_price", 0.0)
    signals = details.get("signals", [])

    if current_regime == "unknown":
        logger.warning("Regime monitor: detection returned unknown, skipping")
        return {"status": "skipped", "reason": "unknown_regime"}

    today = date.today().isoformat()

    # --- Step 2: get last recorded regime ---
    db = get_db()
    prev_row = (
        db.table(TABLE)
        .select("regime, date")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )

    prev_regime = None
    if prev_row.data:
        prev_regime = prev_row.data[0].get("regime")
        prev_date = prev_row.data[0].get("date")
        # Skip if already recorded today
        if prev_date == today:
            logger.info(f"Regime monitor: already recorded today ({current_regime}), skipping")
            return {"status": "already_recorded", "regime": current_regime}

    # --- Step 3: detect change ---
    changed = prev_regime is not None and prev_regime != current_regime

    if changed:
        logger.warning(
            f"REGIME CHANGE DETECTED: {prev_regime} → {current_regime} "
            f"(score={score}, SPY=${spy_price:.2f})"
        )
        # Send alert
        try:
            from app.services.notification_service import notify_regime_change
            await notify_regime_change(
                prev_regime=prev_regime,
                new_regime=current_regime,
                score=score,
                signals=signals,
                spy_price=spy_price,
            )
            logger.info("Regime change alert sent via Feishu")
        except Exception as e:
            logger.error(f"Failed to send regime change alert: {e}", exc_info=True)
    else:
        logger.info(
            f"Regime monitor: {current_regime} (unchanged), score={score}"
        )

    # --- Step 4: save to DB ---
    # Compact signals for storage (keep name + value + contribution only)
    signals_compact = [
        {
            "name": s.get("name", ""),
            "value": s.get("value"),
            "unit": s.get("unit", ""),
            "contribution": s.get("contribution", 0),
        }
        for s in signals
    ]

    try:
        db.table(TABLE).upsert(
            {
                "date": today,
                "regime": current_regime,
                "score": score,
                "spy_price": round(spy_price, 2),
                "signals": signals_compact,
                "changed_from": prev_regime if changed else None,
            },
            on_conflict="date",
        ).execute()
        logger.info(f"Regime history saved: {today} → {current_regime}")
    except Exception as e:
        logger.error(f"Failed to save regime history: {e}", exc_info=True)

    return {
        "status": "changed" if changed else "stable",
        "date": today,
        "regime": current_regime,
        "previous": prev_regime,
        "score": score,
        "spy_price": spy_price,
    }
