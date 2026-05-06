"""Command-line interface for the SRM prototype."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from importlib import import_module
from pathlib import Path

from srm.agents.violation_agent import DefaultViolationAgent
from srm.config import load_config
from srm.data.loader import DataLoadError, load_procurements
from srm.logging_config import configure_logging
from srm.logic.charts import generate_charts_srm
from srm.logic.console_output import (
    print_ascii_charts_ru,
    print_output_files_ru,
    print_summary_ru,
    print_violations_ru,
)
from srm.logic.deploy_check import ready_check
from srm.logic.predictions import compute_risk_assessments
from srm.logic.report import build_report, save_report_json
from srm.logic.supplier_rating import recalc_supplier_ratings
from srm.ontology.loader import OntologyLoadError, load_ontology
from srm.web.auth import reset_failed_login
from srm.web.db import connect, init_db
from srm.web.rulesets import ensure_default_ruleset
from srm.web.security import hash_password
from srm.web.seed_large import seed_large_demo_data_from_cli

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="srm", description="SRM violations analysis prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze procurements and produce report")
    analyze.add_argument("--data", required=True, type=Path, help="Path to procurements JSON/CSV")
    analyze.add_argument("--rules", required=True, type=Path, help="Path to ontology rules JSON")
    analyze.add_argument("--out", required=True, type=Path, help="Path to output report JSON")
    analyze.add_argument(
        "--charts-dir",
        type=Path,
        default=Path("outputs/charts"),
        help="Directory for charts (PNG)",
    )
    analyze.add_argument(
        "--analysis-date",
        type=str,
        default=None,
        help="Override analysis date in ISO format (YYYY-MM-DD). Default: today.",
    )
    analyze.add_argument("--log-dir", type=Path, default=Path("outputs/logs"))
    analyze.add_argument("--log-level", type=str, default="INFO")
    analyze.add_argument("--print-json", action="store_true", help="Print report JSON to console")
    analyze.add_argument(
        "--print-violations",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print violations list to console",
    )
    analyze.add_argument(
        "--ascii-charts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print ASCII charts to console",
    )
    analyze.add_argument(
        "--open-output",
        action="store_true",
        help="Open report and charts in separate windows (OS default apps)",
    )

    serve = sub.add_parser("serve", help="Run minimal FastAPI server (optional extra)")
    serve.add_argument("--host", type=str, default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    exp = sub.add_parser(
        "experiment-risk", help="Run scientific SRM experiment: baseline vs proposed"
    )
    exp.add_argument("--out-dir", type=Path, default=Path("outputs/experiments"))
    exp.add_argument("--seed", type=int, default=7)
    exp.add_argument("--n-records", type=int, default=2000)
    exp.add_argument("--open-output", action="store_true")

    seed_large = sub.add_parser(
        "seed-large-demo", help="Seed a large demo dataset into web SQLite DB"
    )
    seed_large.add_argument("--reset-db", action="store_true")
    seed_large.add_argument("--clients", type=int, default=100)
    seed_large.add_argument("--orders", type=int, default=300)
    seed_large.add_argument("--purchases", type=int, default=700)
    seed_large.add_argument("--violations", type=int, default=250)
    seed_large.add_argument("--seed", type=int, default=7)

    recalc_rating = sub.add_parser(
        "recalc-supplier-rating", help="Recalculate supplier rating KPI based on DB history"
    )
    recalc_rating.add_argument(
        "--analysis-date",
        type=str,
        default=None,
        help="Override date in ISO format (YYYY-MM-DD). Default: today.",
    )
    recalc_rating.add_argument("--lookback-days", type=int, default=30)

    reset_pw = sub.add_parser("reset-password", help="Reset a local user's password in SQLite DB")
    reset_pw.add_argument("--username", type=str, required=True)
    reset_pw.add_argument("--password", type=str, required=True)

    sub.add_parser("check-deploy", help="Check deployment readiness (DB, folders, ruleset)")

    return parser.parse_args(argv)


def _cmd_analyze(args: argparse.Namespace) -> int:
    configure_logging(args.log_dir, level=args.log_level)
    logger.info("Запуск анализа")

    analysis_dt = date.fromisoformat(args.analysis_date) if args.analysis_date else date.today()

    try:
        procurements = load_procurements(args.data)
    except DataLoadError as e:
        logger.error("Failed to load procurements: %s", e)
        return 2

    try:
        ontology = load_ontology(args.rules)
    except OntologyLoadError as e:
        logger.error("Failed to load ontology rules: %s", e)
        return 2

    agent = DefaultViolationAgent()
    violations = agent.analyze(procurements, ontology, analysis_date=analysis_dt)

    charts = generate_charts_srm(violations, procurements=procurements, out_dir=args.charts_dir)
    risk_assessments = compute_risk_assessments(procurements, ontology, analysis_date=analysis_dt)
    report = build_report(
        procurements=procurements,
        ontology=ontology,
        violations=violations,
        charts=charts,
        analysis_date=analysis_dt,
        risk_assessments=risk_assessments,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_report_json(args.out, report)

    logger.info("Отчёт сохранён: %s", args.out)
    logger.info("Найдено нарушений: %d", len(violations))

    print_summary_ru(report)
    if args.ascii_charts:
        print_ascii_charts_ru(report)
    if args.print_violations:
        print_violations_ru(report)
    print_output_files_ru(args.out, charts, log_path=args.log_dir / "srm.log")
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.open_output:
        _open_output_files(args.out, charts)
    return 0


def _open_output_files(report_path: Path, charts: dict[str, str]) -> None:
    """Open output files in separate windows using OS default apps."""

    to_open: list[Path] = [report_path]
    for p in charts.values():
        to_open.append(Path(p))

    for path in to_open:
        try:
            if hasattr(os, "startfile") and sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:  # pragma: no cover
                # Best-effort fallback for non-Windows
                import webbrowser

                webbrowser.open(path.resolve().as_uri())
        except Exception as e:
            logger.warning("Failed to open %s: %s", path, e)


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # type: ignore
    except Exception as e:  # pragma: no cover
        print(
            'FastAPI server requires optional dependencies. Install with: pip install -e ".[api]"'
        )
        print(f"Import error: {e}")
        return 2

    uvicorn.run("srm.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


def _cmd_experiment_risk(args: argparse.Namespace) -> int:
    """Run baseline vs proposed experiment and save artifacts."""

    from srm.experiments.risk_comparison import run_experiment_risk

    out_dir: Path = args.out_dir
    report = run_experiment_risk(
        out_dir=out_dir, seed=int(args.seed), n_records=int(args.n_records)
    )

    json_path = Path(str(report["artifacts"]["json"]))
    csv_path = Path(str(report["artifacts"]["csv"]))
    plot_f1 = Path(str(report["artifacts"]["plots"]["f1"]))
    plot_time = Path(str(report["artifacts"]["plots"]["runtime"]))

    print("Эксперимент SRM (baseline vs proposed) — готово")
    print(f"- JSON: {json_path}")
    print(f"- CSV: {csv_path}")
    print(f"- Графики: {plot_f1}, {plot_time}")
    print(f"- Интерпретация: {report.get('interpretation_ru')}")

    if args.open_output:
        _open_output_files(json_path, {"f1": str(plot_f1), "runtime": str(plot_time)})
    return 0


def _cmd_seed_large_demo(args: argparse.Namespace) -> int:
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


def _cmd_check_deploy(_: argparse.Namespace) -> int:
    cfg = load_config()
    env_path = Path(".env")
    cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)

    deps_ok = True
    deps_msg = "ok"
    try:
        import_module("fastapi")
        import_module("uvicorn")
    except Exception as e:  # pragma: no cover
        deps_ok = False
        deps_msg = str(e)

    conn = connect(cfg.db_path)
    try:
        init_db(conn)
        ensure_default_ruleset(conn, rules_path=cfg.rules_path)
        res = ready_check(conn=conn, uploads_dir=cfg.uploads_dir, artifacts_dir=cfg.artifacts_dir)
    finally:
        conn.close()

    print("Проверка развёртывания")
    print(f"- Python: {res.details.get('python')}")
    print(f"- .env: {'OK' if env_path.exists() else 'НЕ НАЙДЕН'} ({env_path.resolve()})")
    print(f"- Зависимости (FastAPI/uvicorn): {'OK' if deps_ok else 'FAIL'} ({deps_msg})")
    print(f"- База данных: {'OK' if res.details.get('db', {}).get('ok') else 'FAIL'}")
    print(
        f"- Uploads: {'OK' if res.details.get('uploads', {}).get('ok') else 'FAIL'} ({res.details.get('uploads', {}).get('path')})"
    )
    print(
        f"- Artifacts: {'OK' if res.details.get('artifacts', {}).get('ok') else 'FAIL'} ({res.details.get('artifacts', {}).get('path')})"
    )
    print(
        f"- Ruleset: {'OK' if res.details.get('ruleset', {}).get('ok') else 'FAIL'} ({res.details.get('ruleset', {}).get('message')})"
    )

    if not res.ok or not deps_ok:
        print("Готовность: НЕ ГОТОВО")
        return 2
    print("Готовность: OK")
    return 0


def _cmd_recalc_supplier_rating(args: argparse.Namespace) -> int:
    cfg = load_config()
    analysis_dt = date.fromisoformat(args.analysis_date) if args.analysis_date else date.today()
    conn = connect(cfg.db_path)
    try:
        init_db(conn)
        breakdowns = recalc_supplier_ratings(
            conn, analysis_date=analysis_dt, lookback_days=int(args.lookback_days)
        )
    finally:
        conn.close()

    print("Пересчёт рейтинга поставщиков — готово")
    print(f"- Поставщиков обработано: {len(breakdowns)}")
    if breakdowns:
        top = breakdowns[:10]
        print("- ТОП-10 по рейтингу (0..5):")
        for b in top:
            print(f"  • {b.supplier_id}: {b.rating_0_5} (score {b.score_0_100}/100)")
    return 0


def _cmd_reset_password(args: argparse.Namespace) -> int:
    cfg = load_config()
    username = str(args.username or "").strip()
    password = str(args.password or "")
    if not username:
        print("Ошибка: пустой username")
        return 2

    conn = connect(cfg.db_path)
    try:
        init_db(conn)
        row = conn.execute(
            "SELECT id, username FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            print(f"Пользователь не найден: {username}")
            return 2
        pw_hash = hash_password(password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (pw_hash, username),
        )
        conn.commit()
        # Also clear lock/failed attempts if any.
        reset_failed_login(conn, username=username)
        print(f"Пароль обновлён для пользователя: {username}")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m srm.cli ...`."""

    args = _parse_args(argv)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "experiment-risk":
        return _cmd_experiment_risk(args)
    if args.command == "seed-large-demo":
        return _cmd_seed_large_demo(args)
    if args.command == "recalc-supplier-rating":
        return _cmd_recalc_supplier_rating(args)
    if args.command == "reset-password":
        return _cmd_reset_password(args)
    if args.command == "check-deploy":
        return _cmd_check_deploy(args)
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
