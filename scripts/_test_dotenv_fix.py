"""Verify all 6 sibling config_managers import cleanly without python-dotenv."""
import sys

SIBLINGS = [
    ("C:\\GitHub\\rcs_snowflake_export",    "rcs_snowflake_export"),
    ("C:\\GitHub\\rcs_data_loading",        "rcs_data_loading"),
    ("C:\\GitHub\\rcs_feature_engineering", "rcs_feature_engineering"),
    ("C:\\GitHub\\rcs_forecasting",         "rcs_forecasting"),
    ("C:\\GitHub\\rcs_validation",          "rcs_validation"),
    ("C:\\GitHub\\rcs_config",              "rcs_config"),
]

# Prepend each sibling root so their rct_forecast namespace is importable
for path, _ in SIBLINGS:
    if path not in sys.path:
        sys.path.insert(0, path)

# Each has a different rct_forecast package root; we need to test import
# isolation — reset modules between attempts via importlib
import importlib

ok = 0
fail = 0
for path, label in SIBLINGS:
    # Remove any cached rct_forecast modules so each sibling gets a clean slate
    to_remove = [k for k in sys.modules if k.startswith("rct_forecast")]
    for k in to_remove:
        del sys.modules[k]
    try:
        from rct_forecast.config.config_manager import ConfigManager  # type: ignore
        print(f"OK   {label}  ({ConfigManager})")
        ok += 1
    except Exception as exc:
        print(f"FAIL {label}: {exc}")
        fail += 1

print(f"\n{ok} OK  {fail} FAIL")
if fail:
    sys.exit(1)
