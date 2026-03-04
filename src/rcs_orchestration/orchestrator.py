"""
Orchestrator — coordinates data loading, feature engineering, forecasting,
validation, and export across all configured segments.

Architecture
------------
* In **smoke** mode every component is a local stub (no Snowflake, no files).
* In **full/backtest** mode the orchestrator attempts to import the real
  ``rct_forecast.*`` modules from the sibling repos; if any import fails it
  falls back to stubs and logs a warning.
* Each step's output is persisted under ``<output_root>/<run_id>/segments/<seg>/``.
* A ``provenance.json`` is written at the end of every run.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file; return empty dict on missing / empty file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _get_git_sha() -> str:
    """Return short HEAD SHA of the current repo, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _add_sibling_to_path(pkg_dir_name: str) -> None:
    """Append C:\\GitHub\\<pkg_dir_name> to sys.path if it exists and isn't there."""
    # Walk up from this file's location to find the GitHub root
    # file structure: .../src/rcs_orchestration/... -> repo root -> C:\GitHub
    # parents[3] goes from file -> rcs_orchestration -> src -> repo root
    try:
        github_root = Path(__file__).resolve().parents[3]
    except Exception:
        github_root = Path(".").resolve()
    candidate = github_root / pkg_dir_name
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
        logger.debug("Added to sys.path: %s", candidate)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class Orchestrator:
    """
    Main orchestration class.

    Parameters
    ----------
    config_path:
        Path to a YAML config file (see ``config/sample_config.yml``).
    run_id:
        Optional run identifier.  Auto-generated as ``run-<UTC-timestamp>``
        if not supplied.
    """

    def __init__(
        self,
        config_path: Path | str = "config/sample_config.yml",
        run_id: Optional[str] = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = _load_yaml(self.config_path)
        self.run_id: str = run_id or f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"

        output_root_base = Path(self.config.get("output_root", "results"))
        self.output_root: Path = output_root_base / self.run_id
        self.output_root.mkdir(parents=True, exist_ok=True)

        self._started_at: str = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Orchestrator initialised  run_id=%s  output=%s",
            self.run_id,
            self.output_root,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(
        self,
        mode: str = "full",
        segments: Optional[List[str]] = None,
        backtest_cutoff: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute the full orchestration pipeline.

        Parameters
        ----------
        mode:
            ``"smoke"`` | ``"full"`` | ``"backtest"`` | ``"monthly"``
        segments:
            Explicit list of segment names; ``None`` means "all available".
        backtest_cutoff:
            ISO date string (``YYYY-MM-DD``) used as the as-of cut-off for
            backtest / monthly runs.  Passed through to downstream components
            and recorded in provenance.

        Returns
        -------
        dict mapping segment name → result dict.
        """
        self._backtest_cutoff = backtest_cutoff
        logger.info(
            "run()  mode=%s  requested_segments=%s  backtest_cutoff=%s",
            mode, segments, backtest_cutoff,
        )

        loader, fe, forecaster, validator, exporter = self._build_components(mode)

        # If loader is None, we are running in a very degraded mode: let stub code handle it.
        if loader is None:
            logger.warning("Loader is None — components may be stubs and handle segments differently.")
            available: List[str] = segments or []
        else:
            available: List[str] = loader.list_segments()

        if segments:
            # Keep only requested segments; fall back to requested list if none match
            matched = [s for s in available if s in segments]
            if not matched:
                logger.warning(
                    "Requested segments %s not found in available %s; "
                    "using requested list as-is (stub will handle).",
                    segments,
                    available,
                )
                matched = segments
            available = matched

        logger.info("Processing %d segment(s): %s", len(available), available)

        run_results: Dict[str, Any] = {}
        for seg in available:
            logger.info("━━━ Segment: %s ━━━", seg)
            try:
                result = self._run_segment(seg, loader, fe, forecaster, validator, exporter)
                run_results[seg] = result
            except Exception as exc:  # noqa: BLE001 — log and continue
                logger.error("Segment %s FAILED: %s", seg, exc, exc_info=True)
                run_results[seg] = {"status": "failed", "error": str(exc)}

        self._write_provenance(mode, available, run_results, backtest_cutoff)
        self._write_summary(run_results)
        self._write_leaderboard(run_results)
        logger.info(
            "All segments complete.  Provenance → %s",
            self.output_root / "provenance" / "provenance.json",
        )
        return run_results

    # ------------------------------------------------------------------ #
    # Per-segment pipeline
    # ------------------------------------------------------------------ #

    def _run_segment(
        self,
        segment: str,
        loader: Any,
        fe: Any,
        forecaster: Any,
        validator: Any,
        exporter: Any,
    ) -> Dict[str, Any]:
        seg_out = self.output_root / "segments" / segment
        seg_out.mkdir(parents=True, exist_ok=True)

        # 1 — Data loading
        logger.info("[%s] Step 1/5 — data loading", segment)
        df_monthly: pd.DataFrame = loader.load_monthly(segment)
        logger.info("[%s]   loaded %d rows × %d cols", segment, *df_monthly.shape)

        # 2 — Feature engineering
        logger.info("[%s] Step 2/5 — feature engineering", segment)
        fe_cfg: Dict[str, Any] = self.config.get("feature_engineering", {})
        if fe_cfg.get("enabled", True):
            features = fe.build_features(df_monthly, config=fe_cfg)
        else:
            features = df_monthly.copy()
            logger.info("[%s]   feature engineering disabled — passing through raw data", segment)
        try:
            features.to_parquet(seg_out / "features.parquet", index=False)
        except Exception:
            # If features is not a DataFrame (stubs), attempt json fallback
            (seg_out / "features.json").write_text(json.dumps(features, default=str), encoding="utf-8")

        # 3 — Forecasting
        logger.info("[%s] Step 3/5 — forecasting", segment)
        fc_cfg: Dict[str, Any] = self.config.get("forecasting", {})
        horizon: int = fc_cfg.get("horizon", 12)
        forecast = forecaster.forecast(features, horizon=horizon)
        try:
            forecast.to_parquet(seg_out / "forecast.parquet", index=False)
        except Exception:
            (seg_out / "forecast.json").write_text(json.dumps(forecast, default=str), encoding="utf-8")
        logger.info("[%s]   forecast %d periods", segment, len(forecast))

        # 4 — Validation
        logger.info("[%s] Step 4/5 — validation", segment)
        val_cfg: Dict[str, Any] = self.config.get("validation", {})
        if val_cfg.get("enabled", True):
            metrics = validator.validate(df_monthly, forecast, config=val_cfg)
        else:
            metrics = {"status": "skipped"}
            logger.info("[%s]   validation disabled", segment)
        (seg_out / "metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8"
        )

        # 5 — Export
        logger.info("[%s] Step 5/5 — export", segment)
        exp_cfg: Dict[str, Any] = self.config.get("export", {})
        exporter.export(segment, forecast, metrics, out_dir=seg_out, config=exp_cfg)

        # 6 — Write CSV prediction artefact (predictions/<segment>.csv)
        pred_dir = self.output_root / "predictions"
        pred_dir.mkdir(parents=True, exist_ok=True)
        try:
            pred_csv = pred_dir / f"{segment}.csv"
            if isinstance(forecast, pd.DataFrame):
                out_fc = forecast.copy()
                out_fc.insert(0, "segment", segment)
                if hasattr(self, "_backtest_cutoff") and self._backtest_cutoff:
                    out_fc.insert(1, "backtest_cutoff", self._backtest_cutoff)
                out_fc.to_csv(pred_csv, index=False)
                logger.info("[%s] Predictions CSV → %s", segment, pred_csv)
        except Exception as exc:
            logger.warning("[%s] Could not write predictions CSV: %s", segment, exc)

        logger.info("[%s] ✓ complete  status=ok  metrics=%s", segment, metrics)
        return {
            "status": "ok",
            "rows_loaded": len(df_monthly),
            "forecast_horizon": len(forecast),
            "metrics": metrics,
        }

    # ------------------------------------------------------------------ #
    # Component factory
    # ------------------------------------------------------------------ #

    def _build_components(self, mode: str) -> Tuple[Any, Any, Any, Any, Any]:
        """
        Return (loader, feature_engineer, forecaster, validator, exporter).

        smoke mode  → always use local stubs (no I/O).
        full mode   → try to import real rct_forecast modules; fall back to stubs.
        backtest    → same as full for component resolution.
        """
        if mode == "smoke":
            logger.info("Smoke mode — all components are stubs (no Snowflake required)")
            return self._stub_components()

        # full / backtest / monthly — same component resolution
        try:
            components = self._real_components()
            logger.info("Real rct_forecast components loaded successfully")
            return components
        except ImportError as exc:
            logger.warning(
                "Could not load real rct_forecast modules (%s); "
                "falling back to stubs for this run.",
                exc,
            )
            return self._stub_components()

    def _real_components(self) -> Tuple[Any, Any, Any, Any, Any]:
        """Import the live rct_forecast implementations from sibling repos."""
        # Add each sibling package root to sys.path so its rct_forecast namespace is importable
        for pkg_dir in (
            "rcs_data_loading",
            "rcs_feature_engineering",
            "rcs_forecasting",
            "rcs_validation",
            "rcs_snowflake_export",
        ):
            _add_sibling_to_path(pkg_dir)

        # Attempt to import real modules from the rct_forecast package
        try:
            from rct_forecast.data_loading.snowflake_loader import SnowflakeLoader  # type: ignore
            from rct_forecast.feature_engineering.feature_engineer import FeatureEngineer  # type: ignore
            from rct_forecast.forecasting.time_series_forecaster import TimeSeriesForecaster  # type: ignore
        except Exception as exc:
            logger.exception("Error importing rct_forecast real modules: %s", exc)
            raise ImportError("Failed to import real rct_forecast modules") from exc

        # Build a minimal ConfigManager shim so the constructors are satisfied
        class _YamlCfgShim:
            """Thin adapter: exposes ConfigManager.get() over a plain YAML dict."""

            def __init__(self, d: Dict[str, Any]) -> None:
                self._d = d

            def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
                parts = key.split(".")
                node: Any = self._d
                for part in parts:
                    if not isinstance(node, dict):
                        return default
                    node = node.get(part, default)
                return node

        cfg = _YamlCfgShim(self.config)
        loader = SnowflakeLoader(cfg)
        feature_engineer = FeatureEngineer(cfg)
        forecaster = TimeSeriesForecaster(cfg)

        # Validation / export from stubs until rcs_validation exposes a matching interface
        from rcs_orchestration.stubs import StubExporter, StubValidator  # noqa: PLC0415

        return loader, feature_engineer, forecaster, StubValidator(), StubExporter()

    def _stub_components(self) -> Tuple[Any, Any, Any, Any, Any]:
        from rcs_orchestration.stubs import (  # noqa: PLC0415
            StubExporter,
            StubFeatureEngineer,
            StubForecaster,
            StubLoader,
            StubValidator,
        )

        return (
            StubLoader(),
            StubFeatureEngineer(),
            StubForecaster(),
            StubValidator(),
            StubExporter(),
        )

    # ------------------------------------------------------------------ #
    # Provenance & summary
    # ------------------------------------------------------------------ #

    def _write_provenance(
        self,
        mode: str,
        segments: List[str],
        results: Dict[str, Any],
        backtest_cutoff: Optional[str] = None,
    ) -> None:
        prov_dir = self.output_root / "provenance"
        prov_dir.mkdir(parents=True, exist_ok=True)

        cfg_text = self.config_path.read_text(encoding="utf-8")
        cfg_hash = hashlib.sha256(cfg_text.encode()).hexdigest()[:16]

        provenance = {
            "run_id": self.run_id,
            "mode": mode,
            "backtest_cutoff": backtest_cutoff,
            "started_at": self._started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "config_file": str(self.config_path),
            "config_hash_sha256_16": cfg_hash,
            "git_sha": _get_git_sha(),
            "python_version": sys.version,
            "segments_processed": segments,
            "segment_statuses": {
                s: results[s].get("status", "unknown") for s in segments
            },
            "output_root": str(self.output_root),
        }
        (prov_dir / "provenance.json").write_text(
            json.dumps(provenance, indent=2), encoding="utf-8"
        )
        logger.debug("Provenance written: %s", prov_dir / "provenance.json")

    def _write_summary(self, results: Dict[str, Any]) -> None:
        summary = {
            "run_id": self.run_id,
            "total_segments": len(results),
            "ok": sum(1 for r in results.values() if r.get("status") == "ok"),
            "failed": sum(1 for r in results.values() if r.get("status") == "failed"),
            "results": results,
        }
        (self.output_root / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )

    def _write_leaderboard(self, results: Dict[str, Any]) -> None:
        """Write a segment-weighted leaderboard CSV to metrics/leaderboard_segment_weighted.csv."""
        metrics_dir = self.output_root / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for seg, res in results.items():
            if res.get("status") != "ok":
                continue
            m = res.get("metrics", {})
            rows.append({
                "segment": seg,
                "status": res.get("status", "unknown"),
                "rows_loaded": res.get("rows_loaded", 0),
                "forecast_horizon": res.get("forecast_horizon", 0),
                "mape": m.get("mape", ""),
                "validation_status": m.get("status", ""),
            })
        if rows:
            lb = pd.DataFrame(rows)
            lb_path = metrics_dir / "leaderboard_segment_weighted.csv"
            lb.to_csv(lb_path, index=False)
            logger.info("Leaderboard written → %s", lb_path)
        else:
            logger.warning("No successful segments — leaderboard not written.")