"""CLI helper to seed a large demo dataset into the local SQLite DB.

Usage example:
  python tools/seed_large_demo_data.py --reset-db --clients 100 --orders 300 --purchases 700 --violations 250
"""

from __future__ import annotations

import argparse

from srm.web.seed_large import seed_large_demo_data_from_cli


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed large demo data for CRM/SRM service center.")
    p.add_argument("--reset-db", action="store_true")
    p.add_argument("--clients", type=int, default=100)
    p.add_argument("--orders", type=int, default=300)
    p.add_argument("--purchases", type=int, default=700)
    p.add_argument("--violations", type=int, default=250)
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    counts = seed_large_demo_data_from_cli(
        reset_db=bool(args.reset_db),
        clients=int(args.clients),
        orders=int(args.orders),
        purchases=int(args.purchases),
        violations=int(args.violations),
        seed=int(args.seed),
    )

    print("Большой демонстрационный набор данных — готово")
    print(f"- Клиенты: {counts['clients']}")
    print(f"- Устройства: {counts['devices']}")
    print(f"- Заказы: {counts['orders']}")
    print(f"- Поставщики: {counts['suppliers']}")
    print(f"- Закупки: {counts['purchases']}")
    print(f"- Нарушения: {counts['violations']}")
    print(f"- История риска поставщиков: {counts['supplier_risk_history']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
