# rcs_orchestration

Orchestration layer for the RCS Revenue Forecasting system.  Coordinates
`data loading → feature engineering → forecasting → validation → export`
across all configured segments.

---

## Quick-start (smoke test — no Snowflake required)

```powershell
# 1. Create & activate venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dev deps
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

# 3. Install orchestrator (editable)
pip install -e .

# 4. Run unit tests
pytest -q

# 5. Smoke run
python -m rcs_orchestration.main `
    --mode smoke `
    --config config/sample_config.yml `
    --segments sample `
    --run-id smoke-test-001
```

---

## Installing sibling packages (optional for smoke mode)

```powershell
$pkgs = @(
  "..\rcs_common",           # SKIP — not present; rcs_config used instead
  "..\rcs_data_loading",
  "..\rcs_feature_engineering",
  "..\rcs_forecasting",
  "..\rcs_validation",
  "..\rcs_snowflake_export"
)

foreach ($p in $pkgs) {
  if (Test-Path $p) {
    Write-Host "Installing $p"
    pip install -e $p
  } else {
    Write-Host "SKIP (not found): $p"
  }
}
```

> **Note**: All sibling repos expose the `rct_forecast` namespace.  Installing
> several editable copies may cause namespace shadowing.  The orchestrator's
> `smoke` mode bypasses real module imports entirely, so this is not required
> for local development.

---

## Project structure

```
rcs_orchestration/
├── src/
│   └── rcs_orchestration/
│       ├── __init__.py
│       ├── main.py          # CLI entry point
│       ├── orchestrator.py  # Orchestrator class
│       └── stubs.py         # Stub implementations (smoke / dev)
├── tests/
│   └── test_orchestrator.py
├── config/
│   └── sample_config.yml
├── results/
│   └── segments/            # placeholder
├── pyproject.toml
└── requirements-dev.txt
```

---

## Run modes

| mode       | description |
|------------|-------------|
| `smoke`    | Uses stub data/components; no Snowflake or files needed. |
| `full`     | Attempts real `rct_forecast.*` imports; falls back to stubs. |
| `backtest` | Same component resolution as `full`. |

---

## Acceptance criteria checklist

- [ ] `python --version` ≥ 3.10
- [ ] `.venv` activated
- [ ] `pip install -e .` succeeds
- [ ] `pytest -q` — all tests pass
- [ ] Smoke run exits cleanly, `results/smoke-test-001/provenance/provenance.json` exists
