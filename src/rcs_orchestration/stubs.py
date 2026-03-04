"""
Stub implementations for smoke / local-dev mode.

Each class mirrors the interface expected by ``Orchestrator._run_segment()``.
No external I/O is performed; all data is generated in-memory so the full
pipeline can be exercised without Snowflake credentials or large datasets.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class StubLoader:
    """Minimal data loader — returns hard-coded DataFrames."""

    def __init__(self, config: Any = None) -> None:
        pass

    def list_segments(self) -> List[str]:
        return ["sample"]

    def load_monthly(self, segment: str, **kwargs) -> pd.DataFrame:
        logger.info("[StubLoader] load_monthly(%s)", segment)
        periods = [
            "2024-01", "2024-02", "2024-03", "2024-04",
            "2024-05", "2024-06", "2024-07", "2024-08",
            "2024-09", "2024-10", "2024-11", "2024-12",
            "2025-01", "2025-02", "2025-03",
        ]
        actuals = [
            100.0, 105.0, 98.0, 112.0, 120.0, 115.0,
            118.0, 125.0, 130.0, 122.0, 128.0, 140.0,
            135.0, 142.0, 150.0,
        ]
        return pd.DataFrame(
            {"Year Period": periods, "Actual": actuals, "segment": segment}
        )

    def load_daily(self, segment: str, as_of: Optional[str] = None) -> pd.DataFrame:
        logger.info("[StubLoader] load_daily(%s)", segment)
        dates = pd.date_range("2025-03-01", periods=31, freq="D").strftime("%Y-%m-%d").tolist()
        return pd.DataFrame(
            {"date": dates, "Actual": [5.0 + i * 0.1 for i in range(31)], "segment": segment}
        )


class StubFeatureEngineer:
    """Stub feature engineering — adds trivial lag/rolling features."""

    def __init__(self, config: Any = None) -> None:
        pass

    def build_features(self, df: pd.DataFrame, config: Any = None, **kwargs) -> pd.DataFrame:
        logger.info("[StubFeatureEngineer] build_features  rows=%d", len(df))
        out = df.copy()
        if "Actual" in out.columns:
            out["lag_1"] = out["Actual"].shift(1).fillna(0.0)
            out["lag_3"] = out["Actual"].shift(3).fillna(0.0)
            out["rolling_mean_3"] = out["Actual"].rolling(3, min_periods=1).mean()
        return out


class StubForecaster:
    """Stub forecaster — simple linear extrapolation from last observed value."""

    def __init__(self, config: Any = None) -> None:
        pass

    def forecast(self, df: pd.DataFrame, horizon: int = 12, **kwargs) -> pd.DataFrame:
        logger.info("[StubForecaster] forecast  horizon=%d  input_rows=%d", horizon, len(df))
        if "Actual" in df.columns and len(df) >= 2:
            last_val: float = float(df["Actual"].iloc[-1])
            slope: float = (float(df["Actual"].iloc[-1]) - float(df["Actual"].iloc[0])) / max(
                len(df) - 1, 1
            )
        else:
            last_val, slope = 100.0, 1.0

        rows = [
            {
                "period": i,
                "forecast": round(last_val + slope * i, 4),
                "lower_80": round(last_val + slope * i - 5.0, 4),
                "upper_80": round(last_val + slope * i + 5.0, 4),
            }
            for i in range(1, horizon + 1)
        ]
        return pd.DataFrame(rows)


class StubValidator:
    """Stub validator — returns a canned metrics dict."""

    def __init__(self, config: Any = None) -> None:
        pass

    def validate(
        self,
        actuals: pd.DataFrame,
        forecast: pd.DataFrame,
        config: Any = None,
        **kwargs,
    ) -> Dict[str, Any]:
        logger.info("[StubValidator] validate  actual_rows=%d  forecast_rows=%d", len(actuals), len(forecast))
        mape = 0.0
        if "Actual" in actuals.columns and "forecast" in forecast.columns and len(actuals) > 0:
            last_actual = float(actuals["Actual"].iloc[-1])
            first_fc = float(forecast["forecast"].iloc[0])
            denom = max(abs(last_actual), 1e-9)
            mape = round(abs(first_fc - last_actual) / denom * 100, 4)
        return {
            "mape": mape,
            "status": "pass",
            "rows_validated": len(actuals),
        }


class StubExporter:
    """Stub exporter — writes a JSON receipt to out_dir."""

    def __init__(self, config: Any = None) -> None:
        pass

    def export(
        self,
        segment: str,
        forecast: pd.DataFrame,
        metrics: Dict[str, Any],
        out_dir: Optional[Path | str] = None,
        config: Any = None,
        **kwargs,
    ) -> None:
        logger.info("[StubExporter] export  segment=%s  forecast_rows=%d", segment, len(forecast))
        if out_dir is not None:
            dest = Path(out_dir) / "export.json"
            dest.write_text(
                json.dumps(
                    {
                        "segment": segment,
                        "forecast_rows": len(forecast),
                        "metrics": metrics,
                        "exporter": "StubExporter",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.info("[StubExporter] Receipt written → %s", dest)
