"""Large demo dataset seeding for the CRM/SRM service center app.

Purpose:
- create a *much larger* demo dataset than `seed_demo_data`, with realistic relations
  (client → device → order; supplier → purchase; purchase → violations; runs → artifacts).
- keep existing demo data (do not delete) unless `reset_db=True`.

Data policy note:
Use the wording in docs/README:
"демонстрационный набор данных, сформированный для проверки сценариев работы системы".
"""

from __future__ import annotations

import json
import random
import sqlite3
import string
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from srm.config import AppConfig, load_config
from srm.web.auth import create_user, ensure_admin_user
from srm.web.db import connect, init_db
from srm.web.rulesets import ensure_default_ruleset
from srm.web.seed import seed_demo_data


@dataclass(frozen=True, slots=True)
class SeedOptions:
    reset_db: bool
    clients: int
    orders: int
    purchases: int
    violations: int
    devices: int = 150
    suppliers: int = 30
    categories: int = 12
    inventory_items: int = 500
    inventory_moves: int = 1000
    analysis_runs: int = 50


def seed_large_demo_data(
    *,
    config: AppConfig | None = None,
    options: SeedOptions,
    seed: int = 7,
) -> dict[str, int]:
    """Seed a large demo dataset and return created totals (counts in DB)."""

    cfg = config or load_config()
    rng = random.Random(seed)

    if options.reset_db:
        _reset_db_files(cfg)

    conn = connect(cfg.db_path)
    try:
        init_db(conn)

        # Ensure baseline data exists (small demo dataset + required accounts)
        ensure_admin_user(conn)
        ensure_default_ruleset(conn, rules_path=cfg.rules_path)
        seed_demo_data(conn)

        # Ensure roles/users for more realistic assignments.
        _ensure_staff(conn, rng=rng)

        _ensure_suppliers(conn, target=options.suppliers, rng=rng)
        _ensure_categories(conn, target=options.categories)
        _ensure_inventory_items(conn, target=options.inventory_items, rng=rng)
        _ensure_inventory_moves(conn, target=options.inventory_moves, rng=rng)

        _ensure_clients(conn, target=options.clients, rng=rng)
        _ensure_devices(conn, target=options.devices, rng=rng)
        _ensure_orders(conn, target=options.orders, rng=rng)
        _ensure_order_parts(conn, rng=rng)

        _ensure_purchases(conn, target=options.purchases, rng=rng)
        _ensure_violations(conn, target=options.violations, rng=rng)

        _ensure_analysis_runs_and_artifacts(conn, cfg=cfg, target=options.analysis_runs, rng=rng)
        _ensure_supplier_risk_history(conn, rng=rng)

        conn.commit()
        return _counts(conn)
    finally:
        conn.close()


def seed_large_demo_data_from_cli(
    *,
    config: AppConfig | None = None,
    reset_db: bool,
    clients: int,
    orders: int,
    purchases: int,
    violations: int,
    seed: int = 7,
) -> dict[str, int]:
    opts = SeedOptions(
        reset_db=reset_db,
        clients=clients,
        orders=orders,
        purchases=purchases,
        violations=violations,
    )
    return seed_large_demo_data(config=config, options=opts, seed=seed)


def _reset_db_files(cfg: AppConfig) -> None:
    # Be careful: delete only configured DB file; do not wipe the whole repo.
    if cfg.db_path.exists():
        cfg.db_path.unlink()
    # Keep artifacts/uploads directories, but ensure they exist.
    cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rand_phone(rng: random.Random) -> str:
    return f"+7 9{rng.randint(10, 99)} {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}"


def _rand_email(rng: random.Random, name: str) -> str:
    local = "".join(ch for ch in name.lower() if ch.isalnum())
    local = (local[:20] or "client") + str(rng.randint(10, 9999))
    return f"{local}@example.com"


def _rand_imei(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(15))


def _rand_text_id(rng: random.Random, *, prefix: str, width: int = 4) -> str:
    n = rng.randint(1, 10**width - 1)
    return f"{prefix}-{n:0{width}d}-{rng.choice(string.ascii_uppercase)}{rng.randint(0, 9)}"


def _next_human_id(conn: sqlite3.Connection, *, table: str, field: str, prefix: str) -> str:
    row = conn.execute(f"SELECT {field} AS v FROM {table} ORDER BY {field} DESC LIMIT 1").fetchone()
    if row is None or row["v"] is None:
        return f"{prefix}-0001"
    raw = str(row["v"])
    try:
        n = int(raw.split("-")[-1])
    except Exception:
        n = 0
    return f"{prefix}-{n + 1:04d}"


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    def c(sql: str) -> int:
        return int(conn.execute(sql).fetchone()["c"])

    return {
        "clients": c("SELECT COUNT(1) AS c FROM clients"),
        "devices": c("SELECT COUNT(1) AS c FROM devices"),
        "orders": c("SELECT COUNT(1) AS c FROM repair_orders"),
        "suppliers": c("SELECT COUNT(1) AS c FROM suppliers"),
        "categories": c("SELECT COUNT(1) AS c FROM categories"),
        "inventory_items": c("SELECT COUNT(1) AS c FROM inventory_items"),
        "inventory_moves": c("SELECT COUNT(1) AS c FROM inventory_moves"),
        "purchases": c("SELECT COUNT(1) AS c FROM purchases"),
        "violations": c("SELECT COUNT(1) AS c FROM violations"),
        "analysis_runs": c("SELECT COUNT(1) AS c FROM analysis_runs"),
        "supplier_risk_history": c("SELECT COUNT(1) AS c FROM supplier_risk_history"),
    }


def _ensure_staff(conn: sqlite3.Connection, *, rng: random.Random) -> None:
    """Create additional employees for realistic assignments."""

    now = _now_iso()
    existing = {str(r["username"]) for r in conn.execute("SELECT username FROM users").fetchall()}
    # Create several masters and managers if missing.
    for i in range(1, 9):
        u = f"master{i}"
        if u in existing:
            continue
        create_user(conn, username=u, password="master123", role="master")
        conn.execute(
            "UPDATE users SET full_name = ?, created_at = ? WHERE username = ?",
            (f"Мастер {i}", now, u),
        )
    for i in range(1, 5):
        u = f"manager{i}"
        if u in existing:
            continue
        create_user(conn, username=u, password="manager123", role="manager")
        conn.execute(
            "UPDATE users SET full_name = ?, created_at = ? WHERE username = ?",
            (f"Менеджер {i}", now, u),
        )
    conn.commit()


def _ensure_suppliers(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM suppliers").fetchone()["c"])
    if current >= target:
        return

    # A few intentionally problematic suppliers:
    problematic = [
        ("SUP-DELAY-001", "FastShip Parts", "risky", 2.6, 0, 18, "Частые просрочки поставки"),
        ("SUP-DEFECT-002", "QualityIssues Ltd", "risky", 2.9, 1, 9, "Повышенный процент брака"),
        ("SUP-BLOCK-003", "Blacklisted Supply", "blocked", 1.8, 0, 25, "Заблокирован регламентом"),
    ]
    for sup_id, name, status, rating, approved, avg_days, comment in problematic:
        conn.execute(
            """
            INSERT OR IGNORE INTO suppliers(
              supplier_id,name,rating,approved,status,contact_person,phone,email,warranty_terms,average_delivery_days,comment,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sup_id,
                name,
                float(rating),
                int(approved),
                status,
                "Отдел продаж",
                _rand_phone(rng),
                f"sales-{sup_id.lower()}@example.com",
                "6-12 месяцев",
                int(avg_days),
                comment,
                now,
            ),
        )

    brands = ["Apple", "Samsung", "Xiaomi", "Huawei", "Lenovo", "Asus", "HP", "Dell"]
    parts = ["Screen", "Battery", "Flex", "Board", "Case", "Camera", "Connector", "Keyboard"]
    statuses = ["approved", "approved", "approved", "candidate", "risky"]

    to_add = target - int(conn.execute("SELECT COUNT(1) AS c FROM suppliers").fetchone()["c"])
    for _ in range(max(0, to_add)):
        supplier_id = _rand_text_id(rng, prefix="SUP", width=4).replace("-", "")[:12]
        supplier_id = f"SUP-{supplier_id}"
        name = f"{rng.choice(parts)}{rng.choice(brands)} Supply {rng.randint(1, 99)}"
        status = rng.choice(statuses)
        rating = round(rng.uniform(1.5, 5.0), 1)
        approved = 1 if status in {"approved", "candidate"} and rating >= 3.0 else 0
        avg_days = int(rng.randint(3, 21))
        conn.execute(
            """
            INSERT INTO suppliers(
              supplier_id,name,rating,approved,status,contact_person,phone,email,warranty_terms,average_delivery_days,comment,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                supplier_id,
                name,
                float(rating),
                int(approved),
                status,
                "Менеджер",
                _rand_phone(rng),
                f"contact{rng.randint(1, 999)}@example.com",
                rng.choice(["3 месяца", "6 месяцев", "12 месяцев", "без гарантии"]),
                avg_days,
                None,
                now,
            ),
        )
    conn.commit()


def _ensure_categories(conn: sqlite3.Connection, *, target: int) -> None:
    now = _now_iso()
    base = [
        ("SCREEN", "Дисплеи/экраны", 8500.0),
        ("BATTERY", "Аккумуляторы", 3200.0),
        ("FLEX", "Шлейфы/коннекторы", 900.0),
        ("BOARD", "Платы/микросхемы", 12500.0),
        ("CASE", "Корпуса/рамки", 2600.0),
        ("CAMERA", "Камеры", 4200.0),
        ("CHARGE", "Разъёмы зарядки", 1100.0),
        ("SPEAKER", "Динамики", 950.0),
        ("MIC", "Микрофоны", 800.0),
        ("KEYBOARD", "Клавиатуры", 2800.0),
        ("TOOL", "Инструменты", 1800.0),
        ("CONSUM", "Расходники", 400.0),
    ]

    existing = {str(r["code"]) for r in conn.execute("SELECT code FROM categories").fetchall()}
    for code, name, avg in base[:target]:
        if code in existing:
            continue
        conn.execute(
            "INSERT INTO categories(code,name,avg_price,created_at) VALUES(?,?,?,?)",
            (code, name, float(avg), now),
        )
    conn.commit()


def _ensure_inventory_items(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM inventory_items").fetchone()["c"])
    if current >= target:
        return

    categories = [str(r["code"]) for r in conn.execute("SELECT code FROM categories").fetchall()]
    suppliers = [
        str(r["supplier_id"]) for r in conn.execute("SELECT supplier_id FROM suppliers").fetchall()
    ]
    if not categories or not suppliers:
        return

    models = [
        "iPhone 13",
        "iPhone 14",
        "iPad mini",
        "MacBook Pro 14",
        "Galaxy A52",
        "Redmi Note 10",
        "ThinkPad T14",
    ]
    parts = [
        ("SCREEN", "Экран"),
        ("BATTERY", "Аккумулятор"),
        ("FLEX", "Шлейф"),
        ("BOARD", "Плата"),
        ("CASE", "Корпус"),
        ("CAMERA", "Камера"),
        ("CHARGE", "Разъём зарядки"),
        ("SPEAKER", "Динамик"),
        ("MIC", "Микрофон"),
        ("KEYBOARD", "Клавиатура"),
    ]
    parts_by_cat = {c: [] for c in categories}
    for cat, label in parts:
        if cat in parts_by_cat:
            parts_by_cat[cat].append(label)

    to_add = target - current
    for _ in range(to_add):
        sku = f"SKU-{uuid.uuid4().hex[:10].upper()}"
        cat = rng.choice(categories)
        label = rng.choice(parts_by_cat.get(cat) or ["Запчасть"])
        model = rng.choice(models)
        name = f"{label} для {model}"
        avg = conn.execute("SELECT avg_price FROM categories WHERE code = ?", (cat,)).fetchone()
        avg_price = float(avg["avg_price"] or 1000.0) if avg else 1000.0
        purchase_price = round(avg_price * rng.uniform(0.7, 1.15), 2)
        retail_price = round(purchase_price * rng.uniform(1.3, 1.8), 2)
        stock_qty = int(rng.randint(0, 30))
        min_qty = int(rng.choice([0, 0, 2, 3, 5, 8]))
        preferred_supplier = rng.choice(suppliers)
        warranty_months = int(rng.choice([0, 3, 6, 12]))
        conn.execute(
            """
            INSERT INTO inventory_items(
              sku,name,category_code,stock_qty,min_stock_qty,purchase_price,retail_price,warranty_months,preferred_supplier_id,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sku,
                name,
                cat,
                stock_qty,
                min_qty,
                purchase_price,
                retail_price,
                warranty_months,
                preferred_supplier,
                now,
                now,
            ),
        )
    conn.commit()


def _ensure_inventory_moves(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM inventory_moves").fetchone()["c"])
    if current >= target:
        return

    skus = [str(r["sku"]) for r in conn.execute("SELECT sku FROM inventory_items").fetchall()]
    if not skus:
        return

    to_add = target - current
    reasons = ["purchase", "adjustment", "order_use", "inventory_check"]
    for _ in range(to_add):
        sku = rng.choice(skus)
        delta = int(rng.choice([1, 2, 3, 5, 10, -1, -2, -3]))
        reason = rng.choice(reasons)
        conn.execute(
            "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
            (sku, delta, reason, None, None, now),
        )
        # keep stock_qty in sync (best-effort, do not go below 0)
        row = conn.execute("SELECT stock_qty FROM inventory_items WHERE sku = ?", (sku,)).fetchone()
        if row:
            stock = int(row["stock_qty"] or 0)
            new_stock = max(0, stock + delta)
            conn.execute(
                "UPDATE inventory_items SET stock_qty = ?, updated_at = ? WHERE sku = ?",
                (new_stock, now, sku),
            )
    conn.commit()


def _ensure_clients(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM clients").fetchone()["c"])
    if current >= target:
        return

    first = [
        "Алексей",
        "Иван",
        "Мария",
        "Екатерина",
        "Анна",
        "Сергей",
        "Дмитрий",
        "Ольга",
        "Никита",
        "Павел",
    ]
    last = [
        "Петров",
        "Соколов",
        "Иванов",
        "Смирнова",
        "Кузнецов",
        "Попова",
        "Орлова",
        "Морозов",
        "Волков",
        "Фёдоров",
    ]
    org = ['ООО "ТехСервис"', 'ООО "МобайлПарк"', "ИП Сидоров", 'АО "ИнфоТехника"']

    to_add = target - current
    for _ in range(to_add):
        client_id = _next_human_id(conn, table="clients", field="client_id", prefix="CL")
        if rng.random() < 0.12:
            name = rng.choice(org)
        else:
            name = f"{rng.choice(first)} {rng.choice(last)}"
        phone = _rand_phone(rng)
        email = _rand_email(rng, name=name)
        comment = rng.choice(
            [None, "Просит звонить после 18:00", "Только SMS", "Срочно", "Постоянный клиент"]
        )
        balance = round(rng.uniform(-1500, 5000), 2)
        conn.execute(
            "INSERT INTO clients(client_id,name,phone,email,comment,balance,created_at) VALUES(?,?,?,?,?,?,?)",
            (client_id, name, phone, email, comment, balance, now),
        )
    conn.commit()


def _ensure_devices(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM devices").fetchone()["c"])
    if current >= target:
        return

    clients = [
        str(r["client_id"]) for r in conn.execute("SELECT client_id FROM clients").fetchall()
    ]
    if not clients:
        return

    brands_models = {
        "Apple": [
            "iPhone 13",
            "iPhone 14",
            "iPad mini",
            "MacBook Air",
            "MacBook Pro 14",
            "Apple Watch S8",
        ],
        "Samsung": ["Galaxy A52", "Galaxy S22", "Galaxy Tab S7"],
        "Xiaomi": ["Redmi Note 10", "Redmi 12", "Mi 11"],
        "Huawei": ["P40", "MateBook D15", "MatePad"],
        "Lenovo": ["ThinkPad T14", "IdeaPad 5"],
        "Asus": ["ZenBook 14", "ROG Strix"],
        "HP": ["Pavilion 15", "EliteBook 840"],
        "Dell": ["XPS 13", "Inspiron 15"],
    }
    device_types = ["phone", "tablet", "laptop", "watch"]
    conditions = [
        "без повреждений",
        "царапины",
        "сколы",
        "потёртости",
        "разбит экран",
        "следы влаги",
    ]

    to_add = target - current
    for _ in range(to_add):
        device_id = _next_human_id(conn, table="devices", field="device_id", prefix="DEV")
        client_id = rng.choice(clients)
        brand = rng.choice(list(brands_models))
        model = rng.choice(brands_models[brand])
        device_type = rng.choice(device_types)
        serial = (
            _rand_imei(rng)
            if device_type in {"phone", "tablet"}
            else f"SN{rng.randint(100000, 999999)}"
        )
        intake = rng.choice(conditions)
        defects = rng.choice(
            [
                "не включается",
                "не заряжается",
                "разбит экран",
                "нет звука",
                "не работает камера",
                "греется",
                "самопроизвольная перезагрузка",
            ]
        )
        conn.execute(
            """
            INSERT INTO devices(
              device_id,client_id,device_type,brand,model,serial_or_imei,intake_condition,defects_text,photo_path,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (device_id, client_id, device_type, brand, model, serial, intake, defects, None, now),
        )
    conn.commit()


def _ensure_orders(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    current = int(conn.execute("SELECT COUNT(1) AS c FROM repair_orders").fetchone()["c"])
    if current >= target:
        return

    devices = conn.execute("SELECT device_id, client_id FROM devices").fetchall()
    if not devices:
        return

    masters = [
        str(r["username"])
        for r in conn.execute("SELECT username FROM users WHERE role = 'master'").fetchall()
    ]
    managers = [
        str(r["username"])
        for r in conn.execute("SELECT username FROM users WHERE role = 'manager'").fetchall()
    ]
    if not masters:
        masters = ["master"]
    if not managers:
        managers = ["manager"]

    issues = [
        "замена дисплея",
        "замена аккумулятора",
        "замена разъёма зарядки",
        "замена камеры",
        "ремонт платы",
        "замена клавиатуры",
    ]
    statuses = ["accepted", "diagnostics", "approval", "in_repair", "ready", "issued", "canceled"]

    to_add = target - current
    today = date.today()
    for _ in range(to_add):
        order_id = _next_human_id(conn, table="repair_orders", field="order_id", prefix="ORD")
        d = rng.choice(devices)
        device_id = str(d["device_id"])
        client_id = str(d["client_id"])
        issue = rng.choice(issues)
        status = rng.choice(statuses)
        assigned_master = rng.choice(masters)
        manager_username = rng.choice(managers)

        created_at = datetime.now(timezone.utc) - timedelta(days=int(rng.randint(0, 60)))
        updated_at = created_at + timedelta(days=int(rng.randint(0, 10)))

        # Due date: some overdue scenarios.
        due = (
            created_at.date() + timedelta(days=int(rng.choice([2, 3, 5, 7, 10, 14])))
        ).isoformat()
        if rng.random() < 0.18:
            # Force overdue
            due = (today - timedelta(days=int(rng.randint(1, 10)))).isoformat()
            if status in {"ready", "issued", "canceled"}:
                status = rng.choice(["accepted", "diagnostics", "in_repair"])

        labor_cost = round(rng.uniform(800, 15000), 2)
        paid_amount = (
            0.0 if status not in {"issued"} else float(round(labor_cost * rng.uniform(0.8, 1.0), 2))
        )
        preliminary_cost = float(round(labor_cost * rng.uniform(0.8, 1.2), 2))
        approval_status = (
            rng.choice(["pending", "approved", "declined"])
            if status in {"approval"}
            else "approved"
        )
        decline_reason = "клиент отказался" if approval_status == "declined" else None
        diagnostic_result = rng.choice(
            [None, "требуется замена модуля", "требуется пайка", "возможен ремонт"]
        )

        conn.execute(
            """
            INSERT INTO repair_orders(
              order_id,client_id,device_id,order_type,issue,status,assigned_master,manager_username,
              created_at,updated_at,due_date,diagnostic_result,preliminary_cost,approval_status,decline_reason,
              labor_cost,paid_amount,comment
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id,
                client_id,
                device_id,
                rng.choice(["paid", "warranty"]),
                issue,
                status,
                assigned_master,
                manager_username,
                created_at.isoformat(),
                updated_at.isoformat(),
                due,
                diagnostic_result,
                preliminary_cost,
                approval_status,
                decline_reason,
                labor_cost,
                paid_amount,
                rng.choice([None, "Срочный заказ", "Нужна диагностика", "Проверить гарантию"]),
            ),
        )
    conn.commit()


def _ensure_order_parts(conn: sqlite3.Connection, *, rng: random.Random) -> None:
    """Add parts usage for existing orders (best-effort, idempotent)."""

    now = _now_iso()
    orders = [
        str(r["order_id"]) for r in conn.execute("SELECT order_id FROM repair_orders").fetchall()
    ]
    skus = [str(r["sku"]) for r in conn.execute("SELECT sku FROM inventory_items").fetchall()]
    if not orders or not skus:
        return

    # Add parts only for orders without any parts yet.
    for order_id in orders:
        has = conn.execute(
            "SELECT 1 FROM order_parts WHERE order_id = ? LIMIT 1", (order_id,)
        ).fetchone()
        if has:
            continue
        if rng.random() < 0.35:
            continue
        n = int(rng.choice([1, 1, 2, 2, 3]))
        chosen = rng.sample(skus, k=min(n, len(skus)))
        for sku in chosen:
            qty = int(rng.choice([1, 1, 1, 2]))
            row = conn.execute(
                "SELECT retail_price, stock_qty FROM inventory_items WHERE sku = ?", (sku,)
            ).fetchone()
            unit_price = float(row["retail_price"] or 0.0) if row else 0.0
            stock = int(row["stock_qty"] or 0) if row else 0
            if stock <= 0:
                continue
            use_qty = min(qty, stock)
            conn.execute(
                "INSERT INTO order_parts(order_id,sku,quantity,unit_price,created_at) VALUES(?,?,?,?,?)",
                (order_id, sku, use_qty, unit_price, now),
            )
            conn.execute(
                "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
                (sku, -use_qty, "order_use", "order", order_id, now),
            )
            conn.execute(
                "UPDATE inventory_items SET stock_qty = stock_qty - ?, updated_at = ? WHERE sku = ?",
                (use_qty, now, sku),
            )
    conn.commit()


def _ensure_purchases(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM purchases").fetchone()["c"])
    if current >= target:
        return

    suppliers = [
        str(r["supplier_id"]) for r in conn.execute("SELECT supplier_id FROM suppliers").fetchall()
    ]
    categories = [str(r["code"]) for r in conn.execute("SELECT code FROM categories").fetchall()]
    inventory = conn.execute(
        "SELECT sku, name, category_code, purchase_price, warranty_months FROM inventory_items"
    ).fetchall()
    orders = [
        str(r["order_id"]) for r in conn.execute("SELECT order_id FROM repair_orders").fetchall()
    ]
    if not suppliers or not categories or not inventory:
        return

    statuses = ["planned", "ordered", "delivered", "delayed", "cancelled"]
    today = date.today()

    to_add = target - current
    for _ in range(to_add):
        purchase_id = _next_human_id(conn, table="purchases", field="purchase_id", prefix="PO")
        inv = rng.choice(inventory)
        sku = str(inv["sku"])
        item_name = str(inv["name"])
        cat = str(inv["category_code"]) if inv["category_code"] else rng.choice(categories)
        supplier_id = rng.choice(suppliers)
        qty = int(rng.choice([1, 2, 3, 5, 10, 20]))
        unit_price = float(inv["purchase_price"] or rng.uniform(300, 15000))
        # Price outlier scenario: some are intentionally above average
        if rng.random() < 0.07:
            unit_price = round(unit_price * rng.uniform(1.6, 2.2), 2)
        total_amount = round(unit_price * qty, 2)
        planned_budget = round(total_amount * rng.uniform(0.85, 1.20), 2)
        # Budget exceeded scenario:
        if rng.random() < 0.08:
            planned_budget = round(total_amount * rng.uniform(0.55, 0.80), 2)

        order_date = today - timedelta(days=int(rng.randint(0, 120)))
        due_date = order_date + timedelta(days=int(rng.randint(5, 25)))
        status = rng.choice(statuses)

        actual_date: str | None
        if status in {"delivered"}:
            # Delay scenario:
            if rng.random() < 0.15:
                actual_date = (due_date + timedelta(days=int(rng.randint(3, 20)))).isoformat()
            else:
                actual_date = (order_date + timedelta(days=int(rng.randint(2, 18)))).isoformat()
        elif status in {"delayed"}:
            actual_date = (due_date + timedelta(days=int(rng.randint(5, 30)))).isoformat()
        else:
            actual_date = None

        warranty_months = int(inv["warranty_months"] or rng.choice([0, 3, 6, 12]))
        # Missing warranty scenario:
        if rng.random() < 0.08:
            warranty_months = 0

        related_order_id = rng.choice(orders) if orders and rng.random() < 0.3 else None

        conn.execute(
            """
            INSERT INTO purchases(
              purchase_id,supplier_id,category_code,sku,item_name,quantity,unit_price,total_amount,
              planned_budget,warranty_months,order_date,delivery_due_date,delivery_actual_date,status,related_order_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                purchase_id,
                supplier_id,
                cat,
                sku,
                item_name,
                qty,
                unit_price,
                total_amount,
                planned_budget,
                warranty_months,
                order_date.isoformat(),
                due_date.isoformat(),
                actual_date,
                status,
                related_order_id,
                now,
            ),
        )
    conn.commit()


def _ensure_violations(conn: sqlite3.Connection, *, target: int, rng: random.Random) -> None:
    """Seed violations linked to purchases and suppliers."""

    now = _now_iso()
    current = int(conn.execute("SELECT COUNT(1) AS c FROM violations").fetchone()["c"])
    if current >= target:
        return

    purchases = conn.execute(
        "SELECT purchase_id, supplier_id, total_amount, planned_budget, warranty_months, delivery_due_date, delivery_actual_date FROM purchases"
    ).fetchall()
    if not purchases:
        return

    types = [
        ("BUDGET_EXCEEDED", "Превышение бюджета закупки"),
        ("DISALLOWED_SUPPLIER", "Поставщик не одобрен регламентом"),
        ("DELIVERY_DELAY", "Просрочка поставки"),
        ("LOW_RATING_SUPPLIER", "Низкий рейтинг поставщика"),
        ("MISSING_WARRANTY", "Отсутствие гарантии"),
        ("PRICE_TOO_HIGH", "Цена выше средней по категории"),
        ("RECURRING_SUPPLIER_VIOLATIONS", "Повторяющиеся нарушения"),
        ("LOW_STOCK", "Низкий складской остаток"),
        ("QUALITY_DEFECT", "Повышенный процент брака"),
    ]
    risk_levels = ["low", "medium", "high", "critical"]
    statuses = ["new", "checking", "fixed", "rejected"]

    to_add = target - current
    for _ in range(to_add):
        p = rng.choice(purchases)
        purchase_id = str(p["purchase_id"])
        supplier_id = str(p["supplier_id"])
        vtype, vname = rng.choice(types)
        risk = rng.choices(risk_levels, weights=[40, 35, 18, 7], k=1)[0]
        status = rng.choices(statuses, weights=[65, 20, 10, 5], k=1)[0]
        vio_id = f"VIO-{uuid.uuid4().hex[:10].upper()}"

        msg = vname
        details: dict[str, Any] = {"purchase_id": purchase_id, "supplier_id": supplier_id}
        if vtype == "BUDGET_EXCEEDED":
            details["planned_budget"] = p["planned_budget"]
            details["total_amount"] = p["total_amount"]
        if vtype == "MISSING_WARRANTY":
            details["warranty_months"] = p["warranty_months"]
        if vtype == "DELIVERY_DELAY":
            details["due"] = p["delivery_due_date"]
            details["actual"] = p["delivery_actual_date"]

        conn.execute(
            """
            INSERT INTO violations(
              violation_id,run_id,source,entity_type,entity_id,supplier_id,type,risk_level,status,message,details_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                vio_id,
                None,
                "seed",
                "purchase",
                purchase_id,
                supplier_id,
                vtype,
                risk,
                status,
                msg,
                json.dumps(details, ensure_ascii=False),
                now,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO supplier_violations(
              supplier_id,purchase_id,violation_type,risk_level,description,rule_code,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                supplier_id,
                purchase_id,
                vtype,
                risk,
                msg,
                vtype,
                status,
                now,
            ),
        )
    conn.commit()


def _ensure_analysis_runs_and_artifacts(
    conn: sqlite3.Connection,
    *,
    cfg: AppConfig,
    target: int,
    rng: random.Random,
) -> None:
    """Seed analysis runs (with report.json/charts/log placeholders) and link some violations."""

    now = datetime.now(timezone.utc)
    current = int(conn.execute("SELECT COUNT(1) AS c FROM analysis_runs").fetchone()["c"])
    if current >= target:
        return

    # Prefer to link runs to existing users.
    users = [int(r["id"]) for r in conn.execute("SELECT id FROM users").fetchall()]
    if not users:
        return

    purchases = [
        str(r["purchase_id"]) for r in conn.execute("SELECT purchase_id FROM purchases").fetchall()
    ]
    suppliers = [
        str(r["supplier_id"]) for r in conn.execute("SELECT supplier_id FROM suppliers").fetchall()
    ]
    if not purchases:
        return

    # Prepare a lightweight placeholder PNG once (optional). If matplotlib isn't available,
    # we still create report.json and skip images.
    placeholder_png: Path | None = None
    try:
        import matplotlib.pyplot as plt  # type: ignore

        tmp = cfg.artifacts_dir / "_seed_assets"
        tmp.mkdir(parents=True, exist_ok=True)
        placeholder_png = tmp / "demo_chart.png"
        if not placeholder_png.exists():
            fig = plt.figure(figsize=(6, 3))
            ax = fig.add_subplot(111)
            ax.bar(["Нарушения"], [1], color="#4f46e5")
            ax.set_title("Демо-график")
            ax.set_ylabel("Кол-во")
            fig.tight_layout()
            fig.savefig(placeholder_png)
            plt.close(fig)
    except Exception:
        placeholder_png = None

    run_types = ["success", "success", "success", "failed"]
    vio_types = [
        "BUDGET_EXCEEDED",
        "DISALLOWED_SUPPLIER",
        "DELIVERY_DELAY",
        "LOW_RATING_SUPPLIER",
        "MISSING_WARRANTY",
        "PRICE_TOO_HIGH",
        "RECURRING_SUPPLIER_VIOLATIONS",
    ]

    # `run_violations` references `analysis_runs(run_id)` via FK. In this seeding routine we
    # insert run_violations before analysis_runs for simplicity; defer FK checks until commit.
    conn.execute("PRAGMA defer_foreign_keys = ON;")

    to_add = target - current
    for i in range(to_add):
        run_id = f"seed-run-{uuid.uuid4().hex[:8]}"
        started_at = (
            now - timedelta(days=int(rng.randint(0, 45)), hours=int(rng.randint(0, 23)))
        ).isoformat()
        finished_at = (
            datetime.fromisoformat(started_at) + timedelta(minutes=int(rng.randint(1, 12)))
        ).isoformat()
        analysis_dt = (date.today() - timedelta(days=int(rng.randint(0, 45)))).isoformat()
        status = rng.choice(run_types)
        user_id = rng.choice(users)

        run_dir = cfg.artifacts_dir / run_id
        charts_dir = run_dir / "charts"
        logs_dir = run_dir / "logs"
        run_dir.mkdir(parents=True, exist_ok=True)
        charts_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "report.json"
        log_path = logs_dir / "srm.log"

        # Link several seeded run_violations per run.
        n_v = int(rng.randint(2, 10))
        by_type: dict[str, int] = {}
        for _ in range(n_v):
            p_id = rng.choice(purchases)
            s_id = rng.choice(suppliers) if suppliers else None
            t = rng.choice(vio_types)
            by_type[t] = by_type.get(t, 0) + 1
            conn.execute(
                """
                INSERT INTO run_violations(run_id,purchase_id,supplier_id,type,message,details_json,created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    p_id,
                    s_id,
                    t,
                    t,
                    json.dumps({"purchase_id": p_id, "supplier_id": s_id}, ensure_ascii=False),
                    finished_at,
                ),
            )

        summary = {
            "records_total": int(rng.randint(200, 900)),
            "violations_total": int(sum(by_type.values())),
            "violations_by_type": by_type,
            "loss_overspend_total": round(rng.uniform(0, 350_000), 2),
            "loss_delivery_delay_total": round(rng.uniform(0, 120_000), 2),
        }

        report = {
            "meta": {
                "generated_at": finished_at,
                "analysis_date": analysis_dt,
                "ontology_version": "demo",
            },
            "summary": summary,
            "charts": {},
            "violations": [],
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log_path.write_text(
            f"{finished_at} | INFO | seed | Демонстрационный запуск анализа ({i + 1}/{to_add})\n",
            encoding="utf-8",
        )

        if placeholder_png is not None:
            (charts_dir / "violations_by_type.png").write_bytes(placeholder_png.read_bytes())
            (charts_dir / "violations_by_supplier.png").write_bytes(placeholder_png.read_bytes())

        conn.execute(
            """
            INSERT INTO analysis_runs(
              run_id,started_at,finished_at,user_id,analysis_date,status,rules_version,ruleset_id,
              records_count,violations_count,summary_json,report_path,charts_dir,log_path,error_message
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                started_at,
                finished_at,
                user_id,
                analysis_dt,
                status,
                "demo",
                None,
                int(summary["records_total"]),
                int(summary["violations_total"]),
                json.dumps(summary, ensure_ascii=False),
                str(report_path),
                str(charts_dir),
                str(log_path),
                None if status == "success" else "Демонстрационная ошибка",
            ),
        )
    conn.commit()


def _ensure_supplier_risk_history(conn: sqlite3.Connection, *, rng: random.Random) -> None:
    """Seed supplier risk score history (0-100) with explainability fields."""

    now = _now_iso()
    suppliers = [
        str(r["supplier_id"]) for r in conn.execute("SELECT supplier_id FROM suppliers").fetchall()
    ]
    if not suppliers:
        return

    # Keep history small but present; we can append only if table is empty or very small.
    existing = int(conn.execute("SELECT COUNT(1) AS c FROM supplier_risk_history").fetchone()["c"])
    if existing > 0:
        return

    base_date = date.today() - timedelta(days=60)
    for s in suppliers:
        # 4 points in time per supplier
        score = rng.uniform(10, 85)
        for k in range(4):
            d = base_date + timedelta(days=15 * k)
            score = max(0.0, min(100.0, score + rng.uniform(-8, 12)))
            level = (
                "low"
                if score < 25
                else "medium"
                if score < 50
                else "high"
                if score < 75
                else "critical"
            )
            reasons = {
                "budget": round(rng.uniform(0, 1), 2),
                "delivery": round(rng.uniform(0, 1), 2),
                "warranty": round(rng.uniform(0, 1), 2),
                "repeat": round(rng.uniform(0, 1), 2),
            }
            components = {
                "budget_score": round(rng.uniform(0, 30), 2),
                "delivery_score": round(rng.uniform(0, 30), 2),
                "warranty_score": round(rng.uniform(0, 20), 2),
                "repeat_score": round(rng.uniform(0, 20), 2),
            }
            linked = {"supplier_id": s, "note": "seed"}
            conn.execute(
                """
                INSERT INTO supplier_risk_history(
                  supplier_id,risk_score,risk_level,score_date,reasons_json,components_json,linked_violations_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    s,
                    float(round(score, 2)),
                    level,
                    d.isoformat(),
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(components, ensure_ascii=False),
                    json.dumps(linked, ensure_ascii=False),
                    now,
                ),
            )

            # Also populate supplier_score_history for dashboard averages.
            conn.execute(
                """
                INSERT INTO supplier_score_history(supplier_id,score,score_level,score_date,reason,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    s,
                    float(round(score, 2)),
                    level,
                    d.isoformat(),
                    "Демонстрационный расчёт риска",
                    now,
                ),
            )
    conn.commit()
