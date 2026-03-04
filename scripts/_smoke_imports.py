"""
Import smoke test — one symbol from each sibling package.
Run from the rcs_orchestration venv (no Snowflake credentials needed).
"""
import sys

TESTS = [
    # (label, import_statement)
    ("rcs_config        → ConfigManager",
     "from rct_forecast.config.config_manager import ConfigManager"),
    ("rcs_data_loading  → SnowflakeLoader",
     "from rct_forecast.data_loading.snowflake_loader import SnowflakeLoader"),
    ("rcs_feature_eng   → FeatureEngineer (module)",
     "import rct_forecast.feature_engineering.feature_engineer as _fe"),
    ("rcs_forecasting   → time_series_forecaster (module)",
     "import rct_forecast.forecasting.time_series_forecaster as _tsf"),
    ("rcs_snowflake_exp → snowflake_export (module)",
     "import rct_forecast.snowflake_export as _sfx"),
    ("rcs_validation    → validator (module)",
     "import rct_forecast.validation.validator as _val"),
    ("rcs_orchestration → Orchestrator",
     "from rcs_orchestration.orchestrator import Orchestrator"),
]

ok = 0
fail = 0
print(f"\n{'─'*65}")
print(f"  {'Package / Symbol':<42}  Result")
print(f"{'─'*65}")
for label, stmt in TESTS:
    try:
        exec(stmt, {})
        print(f"  {label:<42}  OK")
        ok += 1
    except Exception as exc:
        print(f"  {label:<42}  FAIL  {exc}")
        fail += 1
print(f"{'─'*65}")
print(f"  {ok} OK   {fail} FAIL")
print(f"{'─'*65}\n")
sys.exit(0 if fail == 0 else 1)
