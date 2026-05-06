"""Supplier rating calculation (configurable, explainable).

This module provides a separate *supplier rating* (quality KPI) that is configurable via
DB table `supplier_rating_config`. It is distinct from `risk_score`:
- rating answers: "Насколько поставщик хорош?" (0..5)
- risk_score answers: "Насколько поставщик рискованный?" (0..100)

Rating factors (weights are configurable):
- price: prices vs category average
- delivery: delivery delays vs allowed delay
- warranty: warranty coverage vs required minimum
- violations: number of violations in recent history
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class SupplierRatingConfig:
    w_price: float
    w_delivery: float
    w_warranty: float
    w_violations: float

    def normalized(self) -> SupplierRatingConfig:
        s = float(self.w_price + self.w_delivery + self.w_warranty + self.w_violations)
        if s <= 0:
            return SupplierRatingConfig(0.30, 0.30, 0.20, 0.20)
        return SupplierRatingConfig(
            w_price=float(self.w_price / s),
            w_delivery=float(self.w_delivery / s),
            w_warranty=float(self.w_warranty / s),
            w_violations=float(self.w_violations / s),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "w_price": self.w_price,
                "w_delivery": self.w_delivery,
                "w_warranty": self.w_warranty,
                "w_violations": self.w_violations,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True, slots=True)
class SupplierRatingBreakdown:
    supplier_id: str
    rating_0_5: float
    score_0_100: float
    factors: dict[str, float]  # 0..1
    weights: SupplierRatingConfig
    explanation: list[str]
    calculated_at: str


def load_active_rating_config(conn: sqlite3.Connection) -> SupplierRatingConfig:
    row = conn.execute(
        """
        SELECT w_price, w_delivery, w_warranty, w_violations
        FROM supplier_rating_config
        WHERE is_active = 1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return SupplierRatingConfig(0.30, 0.30, 0.20, 0.20).normalized()
    return SupplierRatingConfig(
        w_price=float(row["w_price"]),
        w_delivery=float(row["w_delivery"]),
        w_warranty=float(row["w_warranty"]),
        w_violations=float(row["w_violations"]),
    ).normalized()


def set_active_rating_config(
    conn: sqlite3.Connection,
    *,
    config: SupplierRatingConfig,
    actor: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE supplier_rating_config SET is_active = 0")
    conn.execute(
        """
        INSERT INTO supplier_rating_config(
          is_active, w_price, w_delivery, w_warranty, w_violations,
          created_at, updated_at, created_by
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            1,
            float(config.w_price),
            float(config.w_delivery),
            float(config.w_warranty),
            float(config.w_violations),
            now,
            now,
            actor,
        ),
    )
    conn.commit()


def recalc_supplier_ratings(
    conn: sqlite3.Connection,
    *,
    analysis_date: date | None = None,
    lookback_days: int = 30,
) -> list[SupplierRatingBreakdown]:
    """Recalculate suppliers.rating and write supplier_rating_history.

    Returns computed breakdowns ordered by rating (desc).
    """

    cfg = load_active_rating_config(conn)
    now = datetime.now(timezone.utc).isoformat()
    dt = analysis_date or date.today()
    since = (dt - timedelta(days=int(lookback_days))).isoformat()

    suppliers = [
        str(r["supplier_id"])
        for r in conn.execute("SELECT supplier_id FROM suppliers ORDER BY supplier_id").fetchall()
    ]

    breakdowns: list[SupplierRatingBreakdown] = []
    for supplier_id in suppliers:
        b = _compute_supplier_rating(
            conn,
            supplier_id=supplier_id,
            cfg=cfg,
            analysis_dt=dt,
            since_iso=since,
        )
        breakdowns.append(b)
        rating_config = json.dumps(
            {
                "score_0_100": b.score_0_100,
                "rating_0_5": b.rating_0_5,
                "factors": b.factors,
                "weights": {
                    "w_price": b.weights.w_price,
                    "w_delivery": b.weights.w_delivery,
                    "w_warranty": b.weights.w_warranty,
                    "w_violations": b.weights.w_violations,
                },
                "explanation": b.explanation,
                "since": since,
                "lookback_days": int(lookback_days),
            },
            ensure_ascii=False,
        )
        conn.execute(
            "UPDATE suppliers SET rating = ?, rating_config = ?, last_rating_update = ? WHERE supplier_id = ?",
            (float(b.rating_0_5), rating_config, now, supplier_id),
        )
        conn.execute(
            """
            INSERT INTO supplier_rating_history(
              supplier_id, rating, rating_scale, factors_json, weights_json, explanation_json,
              calculated_at, created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                supplier_id,
                float(b.rating_0_5),
                "0..5",
                json.dumps(b.factors, ensure_ascii=False),
                b.weights.to_json(),
                json.dumps(b.explanation, ensure_ascii=False),
                b.calculated_at,
                now,
            ),
        )

    conn.commit()
    breakdowns.sort(key=lambda x: x.rating_0_5, reverse=True)
    return breakdowns


def get_last_rating_breakdown(
    conn: sqlite3.Connection, *, supplier_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT rating, rating_scale, factors_json, weights_json, explanation_json, calculated_at
        FROM supplier_rating_history
        WHERE supplier_id = ?
        ORDER BY calculated_at DESC, id DESC
        LIMIT 1
        """,
        (supplier_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        factors = json.loads(str(row["factors_json"] or "{}"))
    except Exception:
        factors = {}
    try:
        weights = json.loads(str(row["weights_json"] or "{}"))
    except Exception:
        weights = {}
    try:
        explanation = json.loads(str(row["explanation_json"] or "[]"))
    except Exception:
        explanation = []
    return {
        "rating": float(row["rating"]),
        "scale": str(row["rating_scale"]),
        "factors": factors,
        "weights": weights,
        "explanation": explanation,
        "calculated_at": str(row["calculated_at"]),
    }


def _compute_supplier_rating(
    conn: sqlite3.Connection,
    *,
    supplier_id: str,
    cfg: SupplierRatingConfig,
    analysis_dt: date,
    since_iso: str,
) -> SupplierRatingBreakdown:
    """Compute supplier rating factors and combine into a single score."""

    # -------------------------
    # Factor: price vs avg
    # -------------------------
    rows = conn.execute(
        """
        SELECT p.unit_price, p.quantity, c.avg_price
        FROM purchases p
        LEFT JOIN categories c ON c.code = p.category_code
        WHERE p.supplier_id = ? AND substr(p.created_at, 1, 10) >= ?
        """,
        (supplier_id, since_iso),
    ).fetchall()
    ratios: list[float] = []
    for r in rows:
        if r["unit_price"] is None or r["avg_price"] is None:
            continue
        try:
            avg = float(r["avg_price"])
            if avg <= 0:
                continue
            ratios.append(float(r["unit_price"]) / avg)
        except Exception:
            continue
    mean_ratio = sum(ratios) / len(ratios) if ratios else 1.0
    # If mean ratio is 1.0 (equal to average) -> score 1.0
    # If 1.35 -> score approaches 0.0
    price_over_pct = max(0.0, (mean_ratio - 1.0) * 100.0)
    price_score = _clamp01(1.0 - (price_over_pct / 35.0))

    # -------------------------
    # Factor: delivery delays
    # -------------------------
    drows = conn.execute(
        """
        SELECT delivery_due_date, delivery_actual_date
        FROM purchases
        WHERE supplier_id = ? AND delivery_due_date IS NOT NULL AND substr(created_at, 1, 10) >= ?
        """,
        (supplier_id, since_iso),
    ).fetchall()
    delays: list[int] = []
    for r in drows:
        due_s = str(r["delivery_due_date"] or "").strip()
        act_s = str(r["delivery_actual_date"] or "").strip()
        try:
            due = date.fromisoformat(due_s)
        except Exception:
            continue
        if act_s:
            try:
                act = date.fromisoformat(act_s)
            except Exception:
                continue
        else:
            # undelivered: treat as delay up to analysis date
            act = analysis_dt
        delays.append(max(0, (act - due).days))
    avg_delay = (sum(delays) / len(delays)) if delays else 0.0
    # Soft penalty: 0 days -> 1.0, 5 days -> 0.5, 10+ -> ~0
    delivery_score = _clamp01(1.0 - (avg_delay / 10.0))

    # -------------------------
    # Factor: warranty coverage
    # -------------------------
    wrows = conn.execute(
        """
        SELECT warranty_months
        FROM purchases
        WHERE supplier_id = ? AND substr(created_at, 1, 10) >= ?
        """,
        (supplier_id, since_iso),
    ).fetchall()
    values: list[int] = []
    for r in wrows:
        if r["warranty_months"] in (None, ""):
            continue
        try:
            values.append(int(r["warranty_months"]))
        except Exception:
            continue
    avg_warranty = (sum(values) / len(values)) if values else 0.0
    # 0 months -> 0, 3+ -> 1.0
    warranty_score = _clamp01(avg_warranty / 3.0)

    # -------------------------
    # Factor: violations count
    # -------------------------
    vcount = int(
        conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM violations
            WHERE supplier_id = ? AND substr(created_at, 1, 10) >= ?
            """,
            (supplier_id, since_iso),
        ).fetchone()["c"]
    )
    # 0 -> 1.0, 10+ -> 0.0
    violations_score = _clamp01(1.0 - (float(vcount) / 10.0))

    factors = {
        "price": round(price_score, 4),
        "delivery": round(delivery_score, 4),
        "warranty": round(warranty_score, 4),
        "violations": round(violations_score, 4),
    }

    weights = cfg.normalized()
    score01 = (
        weights.w_price * factors["price"]
        + weights.w_delivery * factors["delivery"]
        + weights.w_warranty * factors["warranty"]
        + weights.w_violations * factors["violations"]
    )
    score01 = _clamp01(score01)
    score_0_100 = round(score01 * 100.0, 2)
    rating_0_5 = round(score01 * 5.0, 2)

    explanation: list[str] = []
    explanation.append(
        f"Факторы рейтинга (0..1): цена={factors['price']}, сроки={factors['delivery']}, гарантия={factors['warranty']}, нарушения={factors['violations']}."
    )
    if price_over_pct > 0:
        explanation.append(
            f"Средняя цена выше средней по категории примерно на {round(price_over_pct, 1)}%."
        )
    if avg_delay > 0:
        explanation.append(f"Средняя просрочка поставки: {round(avg_delay, 1)} дн.")
    if avg_warranty > 0:
        explanation.append(f"Средняя гарантия по закупкам: {round(avg_warranty, 1)} мес.")
    if vcount > 0:
        explanation.append(
            f"Нарушений за последние {int((analysis_dt - date.fromisoformat(since_iso)).days)} дней: {vcount}."
        )

    return SupplierRatingBreakdown(
        supplier_id=supplier_id,
        rating_0_5=rating_0_5,
        score_0_100=score_0_100,
        factors=factors,
        weights=weights,
        explanation=explanation,
        calculated_at=datetime.now(timezone.utc).isoformat(),
    )


def _clamp01(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return float(x)
