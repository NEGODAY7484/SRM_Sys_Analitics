"""Inventory decision-support helpers.

Goal: provide an *intelligent* stock control layer:
- detect low stock vs configured minimum
- calculate recommended stock level from usage history
- produce purchase recommendations ("сколько докупить")

The logic is intentionally lightweight/statistical (no external services), suitable for
offline diploma demos and easy extension.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class PurchaseRecommendation:
    sku: str
    name: str
    category_code: str | None
    current_stock: int
    min_stock: int
    recommended_stock: int
    purchase_needed: int
    usage_30d_qty: int
    usage_30d_orders: int


def recalc_recommended_stock_levels(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 30,
    coverage_days: int = 21,
) -> int:
    """Recalculate `inventory_items.recommended_stock_qty` for all SKUs.

    Returns number of updated rows.
    """

    skus = [str(r["sku"]) for r in conn.execute("SELECT sku FROM inventory_items").fetchall()]
    updated = 0
    for sku in skus:
        rec = compute_recommended_stock_qty(
            conn, sku=sku, lookback_days=lookback_days, coverage_days=coverage_days
        )
        conn.execute(
            "UPDATE inventory_items SET recommended_stock_qty = ? WHERE sku = ?",
            (int(rec), sku),
        )
        updated += 1
    conn.commit()
    return updated


def compute_recommended_stock_qty(
    conn: sqlite3.Connection,
    *,
    sku: str,
    lookback_days: int = 30,
    coverage_days: int = 21,
) -> int:
    """Compute recommended stock quantity from usage history.

    Heuristic:
    - take consumption quantity for last `lookback_days`
    - estimate average daily usage
    - recommended = max(min_stock, ceil(avg_daily_usage * coverage_days) + safety)
    - safety buffer grows with number of affected orders
    """

    row = conn.execute(
        "SELECT sku, stock_qty, min_stock_qty FROM inventory_items WHERE sku = ?",
        (sku,),
    ).fetchone()
    if row is None:
        return 0
    min_stock = int(row["min_stock_qty"] or 0)

    # inventory_moves.created_at is ISO string; filter by date prefix (YYYY-MM-DD)
    since = (date.today() - timedelta(days=int(lookback_days))).isoformat()
    usage = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN delta_qty < 0 THEN -delta_qty ELSE 0 END), 0) AS qty,
          COALESCE(COUNT(DISTINCT CASE WHEN ref_type = 'order' THEN ref_id END), 0) AS orders
        FROM inventory_moves
        WHERE sku = ? AND reason = 'consume' AND substr(created_at, 1, 10) >= ?
        """,
        (sku, since),
    ).fetchone()
    usage_qty = int(usage["qty"] or 0) if usage is not None else 0
    usage_orders = int(usage["orders"] or 0) if usage is not None else 0

    if lookback_days <= 0:
        return max(0, min_stock)
    avg_daily = usage_qty / float(lookback_days)

    # Safety grows with orders count (more variety/uncertainty).
    safety = min_stock
    if usage_orders > 0:
        safety += int(math.ceil(math.sqrt(float(usage_orders))))

    recommended = int(math.ceil(avg_daily * float(coverage_days))) + safety
    return max(min_stock, recommended, 0)


def build_purchase_recommendations(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 30,
    coverage_days: int = 21,
    limit: int = 200,
) -> list[PurchaseRecommendation]:
    """Return purchase recommendations for SKUs with shortage vs recommended_stock_qty."""

    # Update recommended_stock_qty on the fly to keep UI consistent.
    recalc_recommended_stock_levels(conn, lookback_days=lookback_days, coverage_days=coverage_days)

    rows = conn.execute(
        """
        SELECT sku, name, category_code, stock_qty, min_stock_qty, COALESCE(recommended_stock_qty, 0) AS recommended_stock_qty
        FROM inventory_items
        ORDER BY name
        """
    ).fetchall()

    recs: list[PurchaseRecommendation] = []
    since = (date.today() - timedelta(days=int(lookback_days))).isoformat()
    for r in rows:
        sku = str(r["sku"])
        current = int(r["stock_qty"] or 0)
        min_stock = int(r["min_stock_qty"] or 0)
        recommended = int(r["recommended_stock_qty"] or 0)
        needed = max(0, recommended - current)
        if needed <= 0:
            continue

        usage = conn.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN delta_qty < 0 THEN -delta_qty ELSE 0 END), 0) AS qty,
              COALESCE(COUNT(DISTINCT CASE WHEN ref_type = 'order' THEN ref_id END), 0) AS orders
            FROM inventory_moves
            WHERE sku = ? AND reason = 'consume' AND substr(created_at, 1, 10) >= ?
            """,
            (sku, since),
        ).fetchone()
        usage_qty = int(usage["qty"] or 0) if usage is not None else 0
        usage_orders = int(usage["orders"] or 0) if usage is not None else 0

        recs.append(
            PurchaseRecommendation(
                sku=sku,
                name=str(r["name"]),
                category_code=str(r["category_code"]) if r["category_code"] is not None else None,
                current_stock=current,
                min_stock=min_stock,
                recommended_stock=recommended,
                purchase_needed=needed,
                usage_30d_qty=usage_qty,
                usage_30d_orders=usage_orders,
            )
        )

    # Sort by shortage desc, then by usage desc.
    recs.sort(key=lambda x: (x.purchase_needed, x.usage_30d_qty), reverse=True)
    return recs[: int(limit)]


def maybe_create_low_stock_notification(
    conn: sqlite3.Connection, *, sku: str, commit: bool = True
) -> bool:
    """Create a low-stock notification if below min_stock_qty.

    Returns True if notification inserted.
    """

    row = conn.execute(
        "SELECT sku, name, stock_qty, min_stock_qty FROM inventory_items WHERE sku = ?",
        (sku,),
    ).fetchone()
    if row is None:
        return False
    stock = int(row["stock_qty"] or 0)
    min_stock = int(row["min_stock_qty"] or 0)
    if min_stock <= 0 or stock >= min_stock:
        return False

    # Avoid spamming: if there is an unread low_stock notification for this SKU, do nothing.
    existing = conn.execute(
        """
        SELECT COUNT(1) AS c
        FROM notifications
        WHERE type = 'low_stock' AND ref_type = 'inventory' AND ref_id = ? AND read_at IS NULL
        """,
        (sku,),
    ).fetchone()
    if existing is not None and int(existing["c"] or 0) > 0:
        return False

    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (
            f"Низкий остаток: {row['name']} ({sku}) — осталось {stock}, минимум {min_stock}.",
            "low_stock",
            "inventory",
            sku,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    if commit:
        conn.commit()
    return True
