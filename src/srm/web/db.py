"""SQLite persistence layer for the local SRM web app.

We keep it lightweight (stdlib sqlite3) to ensure offline-first installation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist and apply lightweight migrations."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL,
          full_name TEXT,
          wage_percent REAL,
          wage_fixed_per_order REAL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS suppliers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          rating REAL,
          approved INTEGER NOT NULL DEFAULT 1,
          status TEXT,
          contact_person TEXT,
          phone TEXT,
          email TEXT,
          warranty_terms TEXT,
          average_delivery_days INTEGER,
          comment TEXT,
          created_at TEXT NOT NULL
        );

        -- Supplier specialization categories (independent from parts categories)
        CREATE TABLE IF NOT EXISTS supplier_categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_category_link (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          category_code TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(supplier_id, category_code),
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
          FOREIGN KEY(category_code) REFERENCES supplier_categories(code) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          avg_price REAL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS purchases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          purchase_id TEXT NOT NULL UNIQUE,
          supplier_id TEXT NOT NULL,
          category_code TEXT,
          sku TEXT,
          item_name TEXT,
          quantity INTEGER,
          unit_price REAL,
          total_amount REAL NOT NULL,
          planned_budget REAL,
          warranty_months INTEGER,
          order_date TEXT,
          delivery_due_date TEXT,
          delivery_actual_date TEXT,
          status TEXT,
          related_order_id TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id),
          FOREIGN KEY(category_code) REFERENCES categories(code)
        );

        CREATE TABLE IF NOT EXISTS repair_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticket_id TEXT NOT NULL UNIQUE,
          device_type TEXT NOT NULL,
          brand TEXT NOT NULL,
          model TEXT NOT NULL,
          issue TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        -- CRM entities (service center domain)
        CREATE TABLE IF NOT EXISTS clients (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          client_id TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          phone TEXT,
          email TEXT,
          comment TEXT,
          balance REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS devices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          device_id TEXT NOT NULL UNIQUE,
          client_id TEXT NOT NULL,
          device_type TEXT NOT NULL,
          brand TEXT NOT NULL,
          model TEXT NOT NULL,
          serial_or_imei TEXT,
          intake_condition TEXT,
          defects_text TEXT,
          photo_path TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(client_id) REFERENCES clients(client_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS repair_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id TEXT NOT NULL UNIQUE,
          client_id TEXT NOT NULL,
          device_id TEXT NOT NULL,
          order_type TEXT,
          issue TEXT NOT NULL,
          status TEXT NOT NULL,
          assigned_master TEXT,
          manager_username TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          due_date TEXT,
          diagnostic_result TEXT,
          preliminary_cost REAL,
          approval_status TEXT,
          decline_reason TEXT,
          labor_cost REAL,
          paid_amount REAL NOT NULL DEFAULT 0,
          comment TEXT,
          FOREIGN KEY(client_id) REFERENCES clients(client_id),
          FOREIGN KEY(device_id) REFERENCES devices(device_id)
        );

        CREATE TABLE IF NOT EXISTS order_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id TEXT NOT NULL,
          changed_at TEXT NOT NULL,
          actor TEXT,
          field TEXT NOT NULL,
          old_value TEXT,
          new_value TEXT,
          FOREIGN KEY(order_id) REFERENCES repair_orders(order_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS inventory_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sku TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          category_code TEXT,
          stock_qty INTEGER NOT NULL DEFAULT 0,
          min_stock_qty INTEGER NOT NULL DEFAULT 0,
          purchase_price REAL,
          retail_price REAL,
          warranty_months INTEGER,
          preferred_supplier_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(category_code) REFERENCES categories(code),
          FOREIGN KEY(preferred_supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS inventory_moves (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sku TEXT NOT NULL,
          delta_qty INTEGER NOT NULL,
          reason TEXT NOT NULL,
          ref_type TEXT,
          ref_id TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(sku) REFERENCES inventory_items(sku) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS order_parts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id TEXT NOT NULL,
          sku TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          unit_price REAL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES repair_orders(order_id) ON DELETE CASCADE,
          FOREIGN KEY(sku) REFERENCES inventory_items(sku)
        );

        CREATE TABLE IF NOT EXISTS order_photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id TEXT NOT NULL,
          path TEXT NOT NULL,
          caption TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES repair_orders(order_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          description TEXT,
          status TEXT NOT NULL,
          priority TEXT NOT NULL,
          due_date TEXT,
          assigned_to TEXT,
          ref_type TEXT,
          ref_id TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message TEXT NOT NULL,
          type TEXT NOT NULL,
          ref_type TEXT,
          ref_id TEXT,
          created_at TEXT NOT NULL,
          read_at TEXT
        );

        -- Unified violations workflow table (covers purchases, suppliers, orders, inventory, etc.)
        CREATE TABLE IF NOT EXISTS violations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          violation_id TEXT NOT NULL UNIQUE,
          run_id TEXT,
          source TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          supplier_id TEXT,
          type TEXT NOT NULL,
          risk_level TEXT NOT NULL,
          status TEXT NOT NULL,
          message TEXT NOT NULL,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        -- SRM-specific violations table (normalized supplier-centric view)
        CREATE TABLE IF NOT EXISTS supplier_violations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          purchase_id TEXT,
          violation_type TEXT NOT NULL,
          risk_level TEXT NOT NULL,
          description TEXT NOT NULL,
          rule_code TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          resolved_by TEXT,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id),
          FOREIGN KEY(purchase_id) REFERENCES purchases(purchase_id)
        );

        CREATE TABLE IF NOT EXISTS supplier_score_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          score REAL NOT NULL,
          score_level TEXT NOT NULL,
          score_date TEXT NOT NULL,
          reason TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );

        -- Scientific SRM: full supplier risk history with explainability
        CREATE TABLE IF NOT EXISTS supplier_risk_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          risk_score REAL NOT NULL,
          risk_level TEXT NOT NULL,
          score_date TEXT NOT NULL,
          reasons_json TEXT NOT NULL,
          components_json TEXT NOT NULL,
          linked_violations_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS rulesets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          version TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 0,
          json_path TEXT,
          json_content TEXT,
          created_at TEXT NOT NULL,
          created_by TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL UNIQUE,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          user_id INTEGER,
          analysis_date TEXT NOT NULL,
          status TEXT,
          rules_version TEXT,
          ruleset_id INTEGER,
          records_count INTEGER,
          violations_count INTEGER,
          summary_json TEXT NOT NULL,
          report_path TEXT,
          charts_dir TEXT,
          log_path TEXT,
          error_message TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS run_violations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          purchase_id TEXT,
          supplier_id TEXT,
          type TEXT NOT NULL,
          message TEXT NOT NULL,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
        );

        -- Predictive risk assessments per purchase (decision support layer)
        CREATE TABLE IF NOT EXISTS purchase_risks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          purchase_id TEXT NOT NULL,
          supplier_id TEXT,
          p_delay REAL NOT NULL,
          p_budget REAL NOT NULL,
          risk_probability REAL NOT NULL,
          explain_json TEXT NOT NULL,
          features_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
        );
        """
    )
    migrate_db(conn)
    conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    """Apply small, safe schema migrations for SQLite.

    We intentionally avoid Alembic to keep installation simple for offline demos.
    Migrations are idempotent and run at startup.
    """

    _migrate_users_roles(conn)
    _fix_sessions_fk(conn)
    _ensure_columns(conn, "suppliers", [("status", "TEXT")])
    _ensure_columns(
        conn,
        "suppliers",
        [
            ("contact_person", "TEXT"),
            ("phone", "TEXT"),
            ("email", "TEXT"),
            ("warranty_terms", "TEXT"),
            ("average_delivery_days", "INTEGER"),
            ("comment", "TEXT"),
        ],
    )
    _ensure_columns(
        conn,
        "purchases",
        [
            ("sku", "TEXT"),
            ("status", "TEXT"),
            ("related_order_id", "TEXT"),
            ("created_by", "TEXT"),
        ],
    )
    _ensure_columns(
        conn,
        "repair_orders",
        [
            ("order_type", "TEXT"),
            ("manager_username", "TEXT"),
            ("comment", "TEXT"),
        ],
    )
    _ensure_columns(conn, "users", [("photo_path", "TEXT")])
    _ensure_columns(
        conn,
        "users",
        [
            ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
            ("locked_until", "TEXT"),
            ("last_failed_login_at", "TEXT"),
        ],
    )
    _ensure_columns(conn, "sessions", [("csrf_token", "TEXT")])
    _ensure_columns(conn, "inventory_items", [("photo_path", "TEXT")])
    _ensure_columns(conn, "inventory_items", [("recommended_stock_qty", "INTEGER")])
    _ensure_columns(conn, "suppliers", [("rating_config", "TEXT"), ("last_rating_update", "TEXT")])
    _ensure_columns(
        conn,
        "analysis_runs",
        [
            ("finished_at", "TEXT"),
            ("user_id", "INTEGER"),
            ("status", "TEXT"),
            ("ruleset_id", "INTEGER"),
            ("records_count", "INTEGER"),
            ("violations_count", "INTEGER"),
            ("log_path", "TEXT"),
            ("error_message", "TEXT"),
        ],
    )
    _ensure_indexes(conn)

    # New tables are created in init_db executescript; ensure presence for older DBs.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_rating_config (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          is_active INTEGER NOT NULL DEFAULT 1,
          w_price REAL NOT NULL,
          w_delivery REAL NOT NULL,
          w_warranty REAL NOT NULL,
          w_violations REAL NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          created_by TEXT
        );

        CREATE TABLE IF NOT EXISTS supplier_rating_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          rating REAL NOT NULL,
          rating_scale TEXT NOT NULL,
          factors_json TEXT NOT NULL,
          weights_json TEXT NOT NULL,
          explanation_json TEXT NOT NULL,
          calculated_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS security_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ip TEXT,
          username TEXT,
          action TEXT NOT NULL,
          risk_level TEXT NOT NULL,
          details_json TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id TEXT NOT NULL,
          path TEXT NOT NULL,
          caption TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(order_id) REFERENCES repair_orders(order_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS supplier_categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS supplier_category_link (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          category_code TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(supplier_id, category_code),
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
          FOREIGN KEY(category_code) REFERENCES supplier_categories(code) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS supplier_violations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          purchase_id TEXT,
          violation_type TEXT NOT NULL,
          risk_level TEXT NOT NULL,
          description TEXT NOT NULL,
          rule_code TEXT,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          resolved_by TEXT,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id),
          FOREIGN KEY(purchase_id) REFERENCES purchases(purchase_id)
        );

        CREATE TABLE IF NOT EXISTS supplier_score_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          score REAL NOT NULL,
          score_level TEXT NOT NULL,
          score_date TEXT NOT NULL,
          reason TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS supplier_risk_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_id TEXT NOT NULL,
          risk_score REAL NOT NULL,
          risk_level TEXT NOT NULL,
          score_date TEXT NOT NULL,
          reasons_json TEXT NOT NULL,
          components_json TEXT NOT NULL,
          linked_violations_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS rulesets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          version TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 0,
          json_path TEXT,
          json_content TEXT,
          created_at TEXT NOT NULL,
          created_by TEXT
        );

        CREATE TABLE IF NOT EXISTS purchase_risks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          purchase_id TEXT NOT NULL,
          supplier_id TEXT,
          p_delay REAL NOT NULL,
          p_budget REAL NOT NULL,
          risk_probability REAL NOT NULL,
          explain_json TEXT NOT NULL,
          features_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
        );
        """
    )

    _ensure_default_supplier_rating_config(conn)


def _ensure_default_supplier_rating_config(conn: sqlite3.Connection) -> None:
    """Ensure there is at least one active supplier rating config.

    We keep rating weights configurable from the UI (admin) and via CLI.
    """

    row = conn.execute(
        "SELECT id FROM supplier_rating_config WHERE is_active = 1 LIMIT 1"
    ).fetchone()
    if row is not None:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO supplier_rating_config(
          is_active, w_price, w_delivery, w_warranty, w_violations, created_at, updated_at, created_by
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (1, 0.30, 0.30, 0.20, 0.20, now, now, "system"),
    )


def _migrate_users_roles(conn: sqlite3.Connection) -> None:
    """Expand roles to: admin, manager, master, analyst.

    Earlier schema had a CHECK constraint with roles: admin, analyst, viewer.
    SQLite cannot DROP CHECK constraints, so we rebuild the table if we detect it.
    """

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if row is None or row["sql"] is None:
        return

    sql = str(row["sql"])
    if "CHECK(role IN ('admin','analyst','viewer'))" not in sql:
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    try:
        conn.execute("ALTER TABLE users RENAME TO users_old;")
        conn.execute(
            """
            CREATE TABLE users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              full_name TEXT,
              wage_percent REAL,
              wage_fixed_per_order REAL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO users(id, username, password_hash, role, created_at)
            SELECT id, username, password_hash,
                   CASE WHEN role = 'viewer' THEN 'analyst' ELSE role END,
                   created_at
            FROM users_old
            """
        )
        conn.execute("DROP TABLE users_old;")
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")


def _fix_sessions_fk(conn: sqlite3.Connection) -> None:
    """Ensure `sessions.user_id` FK references the `users` table.

    A previous migration rebuilt the `users` table via rename to `users_old`. SQLite updates
    foreign keys on rename, which caused `sessions` to reference `users_old` (dropped later).
    That breaks login/authorization on existing DBs.
    """

    try:
        fks = conn.execute("PRAGMA foreign_key_list(sessions)").fetchall()
    except sqlite3.OperationalError:
        return

    # Expect exactly one FK to users(id). If it points elsewhere, rebuild sessions.
    if not fks:
        return
    fk_table = str(fks[0]["table"])
    if fk_table == "users":
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    try:
        conn.execute("ALTER TABLE sessions RENAME TO sessions_old;")
        conn.execute(
            """
            CREATE TABLE sessions (
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions(token,user_id,created_at,expires_at)
            SELECT token,user_id,created_at,expires_at
            FROM sessions_old
            """
        )
        conn.execute("DROP TABLE sessions_old;")
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")


def _ensure_columns(conn: sqlite3.Connection, table: str, cols: Iterable[tuple[str, str]]) -> None:
    existing = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, col_type in cols:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Create performance indexes for large demo datasets.

    Requirements mapping:
    - users.login -> users.username
    - orders.* -> repair_orders.*
    """

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);
        CREATE INDEX IF NOT EXISTS idx_devices_serial ON devices(serial_or_imei);
        CREATE INDEX IF NOT EXISTS idx_repair_orders_status ON repair_orders(status);
        CREATE INDEX IF NOT EXISTS idx_repair_orders_created_at ON repair_orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_suppliers_status ON suppliers(status);
        CREATE INDEX IF NOT EXISTS idx_purchases_supplier_id ON purchases(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_purchases_status ON purchases(status);
        CREATE INDEX IF NOT EXISTS idx_violations_supplier_id ON violations(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status);
        CREATE INDEX IF NOT EXISTS idx_analysis_runs_started_at ON analysis_runs(started_at);
        """
    )
