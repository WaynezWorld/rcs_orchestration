# One-shot runner: installs siblings if present, runs import-test and small-backtest
# Usage: powershell -ExecutionPolicy RemoteSigned -File scripts\run_small_backtest.ps1
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO            = Split-Path -Parent $PSScriptRoot   # repo root (one level up from scripts/)
$VENV_ACTIVATE   = Join-Path $REPO ".venv\Scripts\Activate.ps1"
$SAMPLE_CONFIG   = "config\sample_config.yml"
$RUN_ID          = "small-backtest-001"
$SEGMENTS        = "555-21102,599-21102"
$BACKTEST_CUTOFF = "2026-02-01"
$LOGFILE         = Join-Path $REPO "$RUN_ID.log"

$SIBLINGS = @(
  (Join-Path $REPO "..\rcs_config"),
  (Join-Path $REPO "..\rcs_common"),
  (Join-Path $REPO "..\rcs_feature_engineering"),
  (Join-Path $REPO "..\rcs_forecasting"),
  (Join-Path $REPO "..\rcs_data_loading"),
  (Join-Path $REPO "..\rcs_validation"),
  (Join-Path $REPO "..\rcs_snowflake_export")
)

Push-Location $REPO
try {

# ── Activate venv ──────────────────────────────────────────────────────────────
if (-not (Test-Path $VENV_ACTIVATE)) {
  Write-Error "Virtualenv activate script not found: $VENV_ACTIVATE`nCreate venv with: python -m venv .venv"
  exit 1
}
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force
. $VENV_ACTIVATE
Write-Host "venv activated: $env:VIRTUAL_ENV"

python -m pip install --upgrade pip --quiet

# ── Install sibling packages ────────────────────────────────────────────────────
foreach ($abs in $SIBLINGS) {
  if (Test-Path $abs) {
    Write-Host "Installing editable: $abs"
    & python -m pip install -e $abs --quiet
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "pip install failed for $abs (exit $LASTEXITCODE) — continuing"
    }
  } else {
    Write-Host "SKIP not present: $abs"
  }
}

# ── Install orchestrator ────────────────────────────────────────────────────────
Write-Host "Installing rcs_orchestration (editable)..."
& python -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to install rcs_orchestration — continuing" }

# ── Import test ─────────────────────────────────────────────────────────────────
Write-Host "`nIMPORT TEST:"
$importScript = @"
import sys, traceback, os
try:
    from rcs_orchestration.orchestrator import Orchestrator
    cfg_path = r'config\sample_config.yml'
    orch = Orchestrator(cfg_path, run_id='import-test')
    comps = orch._build_components('full')
    ok = all(c is not None for c in comps)
    print('IMPORT_TEST_OK' if ok else 'IMPORT_TEST_PARTIAL')
except Exception as e:
    print('IMPORT_TEST_FAIL')
    traceback.print_exc()
    sys.exit(2)
"@
$importScript | python - 2>&1 | Tee-Object -Variable importOut | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Import test exited non-zero. Orchestrator will fall back to stubs."
}

# ── Run small-backtest ──────────────────────────────────────────────────────────
Write-Host "`nStarting small-backtest..."
if (Test-Path $LOGFILE) { Remove-Item $LOGFILE -Force }

& python -m rcs_orchestration.main `
    --mode monthly `
    --config $SAMPLE_CONFIG `
    --backtest_cutoff $BACKTEST_CUTOFF `
    --segments $SEGMENTS `
    --run-id $RUN_ID `
    2>&1 | Tee-Object -FilePath $LOGFILE

# ── Verification prints ─────────────────────────────────────────────────────────
$prov        = Join-Path $REPO "results\$RUN_ID\provenance\provenance.json"
$summary     = Join-Path $REPO "results\$RUN_ID\summary.json"
$pred_dir    = Join-Path $REPO "results\$RUN_ID\predictions"
$leaderboard = Join-Path $REPO "results\$RUN_ID\metrics\leaderboard_segment_weighted.csv"

Write-Host "`n--- LOG TAIL (last 60 lines) ---"
if (Test-Path $LOGFILE) {
  Get-Content $LOGFILE -Tail 60 | ForEach-Object { Write-Host $_ }
} else { Write-Host "Log not found: $LOGFILE" }

Write-Host "`n--- PROVENANCE ---"
if (Test-Path $prov) {
  Get-Content $prov -Raw | Write-Host
} else { Write-Host "No provenance found: $prov" }

Write-Host "`n--- SUMMARY ---"
if (Test-Path $summary) {
  Get-Content $summary -Raw | Write-Host
} else { Write-Host "No summary found: $summary" }

Write-Host "`n--- SAMPLE PREDICTIONS ---"
if (Test-Path $pred_dir) {
  Get-ChildItem $pred_dir -Filter "*.csv" | ForEach-Object {
    Write-Host "File: $($_.Name)"
    Get-Content $_.FullName -TotalCount 12 | ForEach-Object { Write-Host $_ }
    Write-Host ""
  }
} else { Write-Host "Predictions dir not found: $pred_dir" }

Write-Host "`n--- LEADERBOARD SNIPPET ---"
if (Test-Path $leaderboard) {
  Get-Content $leaderboard -TotalCount 20 | ForEach-Object { Write-Host $_ }
} else { Write-Host "Leaderboard not found: $leaderboard" }

Write-Host "`nRunner complete. Paste the import-test output, log tail, provenance.json, summary.json, predictions and leaderboard back to Wayne/Merlin."

} finally {
  Pop-Location
}
