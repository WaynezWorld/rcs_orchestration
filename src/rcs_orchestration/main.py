"""
CLI entry point for rcs_orchestration.

Usage examples
--------------
# Smoke run (no Snowflake needed, uses stub data):
python -m rcs_orchestration.main --mode smoke --config config/sample_config.yml \\
    --segments sample --run-id smoke-test-001

# Full run (requires rct_forecast modules + Snowflake credentials):
python -m rcs_orchestration.main --mode full --config config/sample_config.yml

# Backtest:
python -m rcs_orchestration.main --mode backtest --config config/sample_config.yml \\
    --segments seg_A seg_B --run-id bt-20260304

# Monthly run with backtest cutoff:
python -m rcs_orchestration.main --mode monthly --config config/sample_config.yml \\
    --backtest_cutoff 2026-02-01 --segments 555-21102,599-21102 --run-id small-backtest-001
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m rcs_orchestration.main",
        description="RCS Orchestration Pipeline",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "smoke", "backtest", "monthly"],
        default="full",
        help=(
            "Run mode: 'smoke' uses stubs (no Snowflake); 'full'/'monthly' use real modules; "
            "'backtest' runs historical backtest. (default: full)"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/sample_config.yml"),
        help="Path to YAML config file (default: config/sample_config.yml)",
    )
    parser.add_argument(
        "--segments",
        nargs="+",
        default=None,
        metavar="SEGMENT",
        help=(
            "One or more segment names to process.  "
            "Accepts space-separated values OR a single comma-separated string "
            "(e.g. '555-21102,599-21102').  Omit to process all segments."
        ),
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Run identifier string. Auto-generated (run-<timestamp>) if not given.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    # Backtest / monthly cut-off date — accepted as --backtest-cutoff or --backtest_cutoff
    parser.add_argument(
        "--backtest-cutoff",
        "--backtest_cutoff",
        dest="backtest_cutoff",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "ISO date used as the 'as-of' cut-off for backtest / monthly runs.  "
            "Data after this date is withheld and used for hold-out evaluation."
        ),
    )
    return parser.parse_args(argv)


def _normalise_segments(raw: list | None) -> list | None:
    """Expand a list that may contain comma-joined strings into individual segment names."""
    if raw is None:
        return None
    result = []
    for item in raw:
        result.extend(s.strip() for s in item.split(",") if s.strip())
    return result or None


def main(argv=None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger = logging.getLogger("rcs_orchestration.main")

    segments = _normalise_segments(args.segments)

    logger.info(
        "Starting RCS Orchestration  mode=%s  config=%s  run_id=%s  "
        "backtest_cutoff=%s  segments=%s",
        args.mode,
        args.config,
        args.run_id,
        args.backtest_cutoff,
        segments,
    )

    # Late import keeps help/tab-complete fast even before deps are installed
    from rcs_orchestration.orchestrator import Orchestrator

    orch = Orchestrator(config_path=args.config, run_id=args.run_id)
    orch.run(
        mode=args.mode,
        segments=segments,
        backtest_cutoff=args.backtest_cutoff,
    )

    logger.info("Orchestration complete.  run_id=%s", orch.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
