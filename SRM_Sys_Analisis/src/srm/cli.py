"""Command-line interface for the SRM prototype."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from srm.agents.violation_agent import DefaultViolationAgent
from srm.data.loader import DataLoadError, load_procurements
from srm.logging_config import configure_logging
from srm.logic.charts import generate_charts
from srm.logic.console_output import (
    print_ascii_charts_ru,
    print_output_files_ru,
    print_summary_ru,
    print_violations_ru,
)
from srm.logic.report import build_report, save_report_json
from srm.ontology.loader import OntologyLoadError, load_ontology

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

    charts = generate_charts(violations, out_dir=args.charts_dir)
    report = build_report(
        procurements=procurements,
        ontology=ontology,
        violations=violations,
        charts=charts,
        analysis_date=analysis_dt,
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


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m srm.cli ...`."""

    args = _parse_args(argv)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "serve":
        return _cmd_serve(args)
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
