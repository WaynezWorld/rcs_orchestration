"""
Unit & integration tests for rcs_orchestration.

Run with:  pytest -q   (from repo root)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from rcs_orchestration.stubs import (
    StubExporter,
    StubFeatureEngineer,
    StubForecaster,
    StubLoader,
    StubValidator,
)
from rcs_orchestration.orchestrator import Orchestrator


# ═══════════════════════════════════════════════════════════════════════════ #
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════ #

@pytest.fixture()
def sample_config(tmp_path: Path) -> Path:
    """Write a minimal YAML config to a temp file and return its path."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        """
output_root: results
logging:
  level: INFO
feature_engineering:
  enabled: true
forecasting:
  horizon: 6
validation:
  enabled: true
export:
  type: local
""",
        encoding="utf-8",
    )
    return cfg


# ═══════════════════════════════════════════════════════════════════════════ #
# Stub: StubLoader
# ═══════════════════════════════════════════════════════════════════════════ #

class TestStubLoader:
    def test_list_segments_returns_list(self):
        loader = StubLoader()
        segs = loader.list_segments()
        assert isinstance(segs, list)
        assert len(segs) >= 1

    def test_load_monthly_returns_dataframe(self):
        loader = StubLoader()
        df = loader.load_monthly("sample")
        assert isinstance(df, pd.DataFrame)
        assert "Actual" in df.columns
        assert "Year Period" in df.columns
        assert len(df) > 0

    def test_load_monthly_contains_segment_column(self):
        loader = StubLoader()
        df = loader.load_monthly("seg_A")
        assert (df["segment"] == "seg_A").all()

    def test_load_daily_returns_dataframe(self):
        loader = StubLoader()
        df = loader.load_daily("sample")
        assert isinstance(df, pd.DataFrame)
        assert "Actual" in df.columns
        assert len(df) == 31


# ═══════════════════════════════════════════════════════════════════════════ #
# Stub: StubFeatureEngineer
# ═══════════════════════════════════════════════════════════════════════════ #

class TestStubFeatureEngineer:
    @pytest.fixture()
    def monthly_df(self) -> pd.DataFrame:
        return StubLoader().load_monthly("sample")

    def test_adds_lag_features(self, monthly_df):
        fe = StubFeatureEngineer()
        out = fe.build_features(monthly_df)
        assert "lag_1" in out.columns
        assert "lag_3" in out.columns

    def test_row_count_preserved(self, monthly_df):
        fe = StubFeatureEngineer()
        out = fe.build_features(monthly_df)
        assert len(out) == len(monthly_df)

    def test_rolling_mean_column_present(self, monthly_df):
        fe = StubFeatureEngineer()
        out = fe.build_features(monthly_df)
        assert "rolling_mean_3" in out.columns


# ═══════════════════════════════════════════════════════════════════════════ #
# Stub: StubForecaster
# ═══════════════════════════════════════════════════════════════════════════ #

class TestStubForecaster:
    @pytest.fixture()
    def feature_df(self) -> pd.DataFrame:
        return StubFeatureEngineer().build_features(StubLoader().load_monthly("sample"))

    def test_returns_dataframe(self, feature_df):
        fc = StubForecaster().forecast(feature_df, horizon=6)
        assert isinstance(fc, pd.DataFrame)

    def test_correct_horizon_rows(self, feature_df):
        for h in (1, 6, 12, 24):
            fc = StubForecaster().forecast(feature_df, horizon=h)
            assert len(fc) == h, f"Expected {h} rows, got {len(fc)}"

    def test_forecast_columns(self, feature_df):
        fc = StubForecaster().forecast(feature_df, horizon=6)
        assert "forecast" in fc.columns
        assert "lower_80" in fc.columns
        assert "upper_80" in fc.columns

    def test_period_column_sequential(self, feature_df):
        fc = StubForecaster().forecast(feature_df, horizon=6)
        assert list(fc["period"]) == list(range(1, 7))

    def test_forecast_values_increasing_with_positive_slope(self, feature_df):
        fc = StubForecaster().forecast(feature_df, horizon=6)
        # Actual column is increasing in stub data so slope > 0
        assert fc["forecast"].iloc[-1] > fc["forecast"].iloc[0]


# ═══════════════════════════════════════════════════════════════════════════ #
# Stub: StubValidator
# ═══════════════════════════════════════════════════════════════════════════ #

class TestStubValidator:
    @pytest.fixture()
    def actuals_and_forecast(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        actuals = StubLoader().load_monthly("sample")
        forecast = StubForecaster().forecast(actuals, horizon=6)
        return actuals, forecast

    def test_returns_dict(self, actuals_and_forecast):
        actuals, forecast = actuals_and_forecast
        metrics = StubValidator().validate(actuals, forecast)
        assert isinstance(metrics, dict)

    def test_mape_key_present(self, actuals_and_forecast):
        actuals, forecast = actuals_and_forecast
        metrics = StubValidator().validate(actuals, forecast)
        assert "mape" in metrics

    def test_status_pass(self, actuals_and_forecast):
        actuals, forecast = actuals_and_forecast
        metrics = StubValidator().validate(actuals, forecast)
        assert metrics["status"] == "pass"

    def test_rows_validated_matches_actuals(self, actuals_and_forecast):
        actuals, forecast = actuals_and_forecast
        metrics = StubValidator().validate(actuals, forecast)
        assert metrics["rows_validated"] == len(actuals)


# ═══════════════════════════════════════════════════════════════════════════ #
# Stub: StubExporter
# ═══════════════════════════════════════════════════════════════════════════ #

class TestStubExporter:
    def test_writes_export_json(self, tmp_path):
        forecast = pd.DataFrame({"period": [1, 2], "forecast": [100.0, 101.0]})
        metrics = {"mape": 1.0, "status": "pass", "rows_validated": 10}
        StubExporter().export("sample", forecast, metrics, out_dir=tmp_path)
        export_file = tmp_path / "export.json"
        assert export_file.exists(), "export.json not created"

    def test_export_json_content(self, tmp_path):
        forecast = pd.DataFrame({"period": [1], "forecast": [99.0]})
        metrics = {"mape": 2.5, "status": "pass", "rows_validated": 5}
        StubExporter().export("seg_X", forecast, metrics, out_dir=tmp_path)
        data = json.loads((tmp_path / "export.json").read_text())
        assert data["segment"] == "seg_X"
        assert data["forecast_rows"] == 1
        assert data["metrics"]["status"] == "pass"

    def test_export_no_out_dir_does_not_raise(self):
        forecast = pd.DataFrame({"period": [1], "forecast": [100.0]})
        StubExporter().export("sample", forecast, {}, out_dir=None)  # should not raise


# ═══════════════════════════════════════════════════════════════════════════ #
# Orchestrator — integration / smoke tests
# ═══════════════════════════════════════════════════════════════════════════ #

class TestOrchestrator:
    def test_init_creates_output_dir(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="init-test-001")
        assert orch.output_root.exists()

    def test_default_run_id_starts_with_run(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config)
        assert orch.run_id.startswith("run-")

    def test_explicit_run_id_preserved(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="custom-abc-123")
        assert orch.run_id == "custom-abc-123"

    def test_missing_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            Orchestrator(config_path=tmp_path / "nonexistent.yml", run_id="x")

    def test_smoke_run_returns_results_dict(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-ret-001")
        results = orch.run(mode="smoke", segments=["sample"])
        assert isinstance(results, dict)
        assert "sample" in results

    def test_smoke_run_segment_status_ok(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-ok-001")
        results = orch.run(mode="smoke", segments=["sample"])
        assert results["sample"]["status"] == "ok"

    def test_smoke_run_provenance_written(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-prov-001")
        orch.run(mode="smoke", segments=["sample"])
        prov_file = orch.output_root / "provenance" / "provenance.json"
        assert prov_file.exists(), f"provenance.json missing at {prov_file}"

    def test_smoke_run_provenance_fields(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-fields-001")
        orch.run(mode="smoke", segments=["sample"])
        prov = json.loads(
            (orch.output_root / "provenance" / "provenance.json").read_text()
        )
        assert prov["run_id"] == "smoke-fields-001"
        assert prov["mode"] == "smoke"
        assert "sample" in prov["segments_processed"]
        assert prov["segment_statuses"]["sample"] == "ok"
        assert "git_sha" in prov
        assert "python_version" in prov
        assert "config_hash_sha256_16" in prov
        assert "backtest_cutoff" in prov   # new field — None when not supplied

    def test_smoke_run_summary_written(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-sum-001")
        orch.run(mode="smoke", segments=["sample"])
        summary_file = orch.output_root / "summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text())
        assert summary["ok"] == 1
        assert summary["failed"] == 0

    def test_smoke_run_creates_parquet_outputs(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-parq-001")
        orch.run(mode="smoke", segments=["sample"])
        seg_dir = orch.output_root / "segments" / "sample"
        assert (seg_dir / "features.parquet").exists()
        assert (seg_dir / "forecast.parquet").exists()
        assert (seg_dir / "metrics.json").exists()
        assert (seg_dir / "export.json").exists()

    def test_smoke_run_with_unknown_segment_still_runs(
        self, sample_config, tmp_path, monkeypatch
    ):
        """Requesting a segment not in loader.list_segments() should still produce output."""
        monkeypatch.chdir(tmp_path)
        orch = Orchestrator(config_path=sample_config, run_id="smoke-unknown-001")
        results = orch.run(mode="smoke", segments=["unknown_seg"])
        assert "unknown_seg" in results
        # Stub handles any segment name — status should be ok
        assert results["unknown_seg"]["status"] == "ok"
