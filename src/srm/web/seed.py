"""Seed demo data for the service center domain (CRM + SRM).

Data policy note:
We use a demonstration test dataset сформированный для проверки сценариев работы системы.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def seed_demo_data(conn: sqlite3.Connection) -> None:
    """Seed demo data if tables are empty.

    Data source:
    - `examples/repair_demo_data.json` (preferred)
    - fallback built-in dataset (if file is missing)
    """

    now = datetime.now(timezone.utc).isoformat()
    data = _load_demo_json()

    _seed_if_empty(
        conn,
        table="suppliers",
        insert_sql=(
            "INSERT INTO suppliers("
            "supplier_id,name,rating,approved,status,contact_person,phone,email,warranty_terms,average_delivery_days,comment,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                s["supplier_id"],
                s["name"],
                float(s["rating"]) if s.get("rating") is not None else None,
                1 if bool(s.get("approved", True)) else 0,
                s.get("status"),
                s.get("contact_person"),
                s.get("phone"),
                s.get("email"),
                s.get("warranty_terms"),
                int(s["average_delivery_days"])
                if s.get("average_delivery_days") is not None
                else None,
                s.get("comment"),
                now,
            )
            for s in data["suppliers"]
        ],
    )

    _seed_if_empty(
        conn,
        table="supplier_categories",
        insert_sql="INSERT INTO supplier_categories(code,name,created_at) VALUES(?,?,?)",
        rows=[(c["code"], c["name"], now) for c in data.get("supplier_categories", [])],
    )

    _seed_if_empty(
        conn,
        table="supplier_category_link",
        insert_sql="INSERT INTO supplier_category_link(supplier_id,category_code,created_at) VALUES(?,?,?)",
        rows=[
            (x["supplier_id"], x["category_code"], now)
            for x in data.get("supplier_category_link", [])
        ],
    )

    _seed_if_empty(
        conn,
        table="categories",
        insert_sql="INSERT INTO categories(code,name,avg_price,created_at) VALUES(?,?,?,?)",
        rows=[
            (
                c["code"],
                c["name"],
                float(c["avg_price"]) if c.get("avg_price") is not None else None,
                now,
            )
            for c in data["categories"]
        ],
    )

    _seed_if_empty(
        conn,
        table="purchases",
        insert_sql=(
            "INSERT INTO purchases(purchase_id,supplier_id,category_code,sku,item_name,quantity,unit_price,total_amount,"
            "planned_budget,warranty_months,order_date,delivery_due_date,delivery_actual_date,status,related_order_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                p["purchase_id"],
                p["supplier_id"],
                p.get("category_code"),
                p.get("sku"),
                p.get("item_name"),
                int(p["quantity"]) if p.get("quantity") is not None else None,
                float(p["unit_price"]) if p.get("unit_price") is not None else None,
                float(p["total_amount"]),
                float(p["planned_budget"]) if p.get("planned_budget") is not None else None,
                int(p["warranty_months"]) if p.get("warranty_months") is not None else None,
                p.get("order_date"),
                p.get("delivery_due_date"),
                p.get("delivery_actual_date"),
                p.get("status"),
                p.get("related_order_id"),
                now,
            )
            for p in data["purchases"]
        ],
    )

    # Legacy: demo repair_requests (kept for backward compatibility in UI).
    _seed_if_empty(
        conn,
        table="repair_requests",
        insert_sql="INSERT INTO repair_requests(ticket_id,device_type,brand,model,issue,status,created_at) VALUES(?,?,?,?,?,?,?)",
        rows=[
            (
                r["ticket_id"],
                r["device_type"],
                r["brand"],
                r["model"],
                r["issue"],
                r.get("status", "new"),
                now,
            )
            for r in data["repairs"]
        ],
    )

    _seed_if_empty(
        conn,
        table="clients",
        insert_sql="INSERT INTO clients(client_id,name,phone,email,comment,balance,created_at) VALUES(?,?,?,?,?,?,?)",
        rows=[
            (
                c["client_id"],
                c["name"],
                c.get("phone"),
                c.get("email"),
                c.get("comment"),
                float(c.get("balance", 0.0) or 0.0),
                now,
            )
            for c in data.get("clients", [])
        ],
    )

    _seed_if_empty(
        conn,
        table="devices",
        insert_sql=(
            "INSERT INTO devices(device_id,client_id,device_type,brand,model,serial_or_imei,intake_condition,"
            "defects_text,photo_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                d["device_id"],
                d["client_id"],
                d["device_type"],
                d["brand"],
                d["model"],
                d.get("serial_or_imei"),
                d.get("intake_condition"),
                d.get("defects_text"),
                d.get("photo_path"),
                now,
            )
            for d in data.get("devices", [])
        ],
    )

    _seed_if_empty(
        conn,
        table="repair_orders",
        insert_sql=(
            "INSERT INTO repair_orders(order_id,client_id,device_id,issue,status,assigned_master,created_at,updated_at,"
            "due_date,diagnostic_result,preliminary_cost,approval_status,decline_reason,labor_cost,paid_amount) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                o["order_id"],
                o["client_id"],
                o["device_id"],
                o["issue"],
                o.get("status", "accepted"),
                o.get("assigned_master"),
                now,
                now,
                o.get("due_date"),
                o.get("diagnostic_result"),
                float(o["preliminary_cost"]) if o.get("preliminary_cost") is not None else None,
                o.get("approval_status", "pending"),
                o.get("decline_reason"),
                float(o["labor_cost"]) if o.get("labor_cost") is not None else None,
                float(o.get("paid_amount", 0.0) or 0.0),
            )
            for o in data.get("orders", [])
        ],
    )

    _seed_if_empty(
        conn,
        table="inventory_items",
        insert_sql=(
            "INSERT INTO inventory_items(sku,name,category_code,stock_qty,min_stock_qty,purchase_price,retail_price,"
            "warranty_months,preferred_supplier_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                i["sku"],
                i["name"],
                i.get("category_code"),
                int(i.get("stock_qty", 0) or 0),
                int(i.get("min_stock_qty", 0) or 0),
                float(i["purchase_price"]) if i.get("purchase_price") is not None else None,
                float(i["retail_price"]) if i.get("retail_price") is not None else None,
                int(i["warranty_months"]) if i.get("warranty_months") is not None else None,
                i.get("preferred_supplier_id"),
                now,
                now,
            )
            for i in data.get("inventory", [])
        ],
    )

    # Add seed moves if inventory existed and moves are empty.
    moves_count = int(conn.execute("SELECT COUNT(1) AS c FROM inventory_moves").fetchone()["c"])
    inv_count = int(conn.execute("SELECT COUNT(1) AS c FROM inventory_items").fetchone()["c"])
    if inv_count > 0 and moves_count == 0:
        for i in data.get("inventory", []):
            qty = int(i.get("stock_qty", 0) or 0)
            if qty == 0:
                continue
            conn.execute(
                "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
                (i["sku"], qty, "seed", None, None, now),
            )
        conn.commit()

    _seed_if_empty(
        conn,
        table="tasks",
        insert_sql=(
            "INSERT INTO tasks(task_id,title,description,status,priority,due_date,assigned_to,ref_type,ref_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)"
        ),
        rows=[
            (
                t["task_id"],
                t["title"],
                t.get("description"),
                t.get("status", "new"),
                t.get("priority", "medium"),
                t.get("due_date"),
                t.get("assigned_to"),
                t.get("ref_type"),
                t.get("ref_id"),
                now,
            )
            for t in data.get("tasks", [])
        ],
    )

    notif_count = int(conn.execute("SELECT COUNT(1) AS c FROM notifications").fetchone()["c"])
    if notif_count == 0:
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                "Демо-данные загружены. Создавайте заказы, работайте со складом и запускайте SRM-проверки.",
                "demo",
                None,
                None,
                now,
            ),
        )
        conn.commit()


def _seed_if_empty(
    conn: sqlite3.Connection, *, table: str, insert_sql: str, rows: list[tuple[object, ...]]
) -> None:
    count = int(conn.execute(f"SELECT COUNT(1) AS c FROM {table}").fetchone()["c"])
    if count > 0:
        return
    if not rows:
        return
    conn.executemany(insert_sql, rows)
    conn.commit()


def _load_demo_json() -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "examples" / "repair_demo_data.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {
            "suppliers": list(raw.get("suppliers", [])),
            "categories": list(raw.get("categories", [])),
            "supplier_categories": list(raw.get("supplier_categories", [])),
            "supplier_category_link": list(raw.get("supplier_category_link", [])),
            "purchases": list(raw.get("purchases", [])),
            "repairs": list(raw.get("repairs", [])),
            "clients": list(raw.get("clients", [])),
            "devices": list(raw.get("devices", [])),
            "orders": list(raw.get("orders", [])),
            "inventory": list(raw.get("inventory", [])),
            "tasks": list(raw.get("tasks", [])),
        }

    # Fallback minimal dataset
    return {
        "suppliers": [
            {
                "supplier_id": "SUP-SCR-001",
                "name": "ScreenParts RU",
                "rating": 4.6,
                "approved": True,
            },
            {
                "supplier_id": "SUP-MLB-004",
                "name": "BoardService",
                "rating": 2.4,
                "approved": False,
            },
        ],
        "categories": [
            {"code": "SCREEN", "name": "Дисплеи/экраны", "avg_price": 8500.0},
            {"code": "BOARD", "name": "Платы/микросхемы", "avg_price": 12500.0},
        ],
        "purchases": [],
        "repairs": [],
        "clients": [],
        "devices": [],
        "orders": [],
        "inventory": [],
        "tasks": [],
    }
