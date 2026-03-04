#!/usr/bin/env python3
"""
Snowflake external-browser connection smoke test.

Usage
-----
python scripts/test_snowflake_externalbrowser.py

Environment variable overrides (all optional — defaults read from
rcs_snowflake_export config/default.yml and the YAML in config/sample_config.yml):

  SNOWFLAKE_ACCOUNT     e.g. myorg-myaccount
  SNOWFLAKE_USER        your.name@domain.com  (or SSO username)
  SNOWFLAKE_WAREHOUSE   e.g. WH_ANALYTICS
  SNOWFLAKE_DATABASE    default: DB_BI_P_EDW
  SNOWFLAKE_SCHEMA      default: CCBCC_RCT_SELFSERVICE
  SNOWFLAKE_ROLE        optional

Authentication is always externalbrowser (no password required).
A browser tab will open once for SSO; after that the session is used for queries.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── 1. Check for snowflake-connector-python ─────────────────────────────────
try:
    import snowflake.connector
except ImportError:
    print("ERROR: snowflake-connector-python is not installed.")
    print("Install it with:")
    print("  pip install snowflake-connector-python")
    sys.exit(1)

# ── 2. Resolve connection parameters ────────────────────────────────────────
#
# Priority order:
#   1. Environment variable  (SNOWFLAKE_*)
#   2. YAML default.yml from rcs_snowflake_export  (sibling repo)
#   3. Hard-coded fallback

def _load_sibling_defaults() -> dict:
    """Try to load Snowflake defaults from rcs_snowflake_export/config/default.yml."""
    try:
        import yaml  # always available (pyyaml is in requirements-dev.txt)
        candidate = (
            Path(__file__).resolve().parents[2]  # C:\GitHub
            / "rcs_snowflake_export"
            / "config"
            / "default.yml"
        )
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            sf = data.get("snowflake", {})
            print(f"[config] Loaded Snowflake defaults from {candidate}")
            return sf
    except Exception as exc:
        print(f"[config] Could not load sibling default.yml: {exc}")
    return {}

defaults = _load_sibling_defaults()

def _get(env_var: str, cfg_key: str, fallback: str = "") -> str:
    return (
        os.environ.get(env_var)
        or defaults.get(cfg_key)
        or fallback
    ).strip()

ACCOUNT   = _get("SNOWFLAKE_ACCOUNT",   "account")
USER      = _get("SNOWFLAKE_USER",      "user")
WAREHOUSE = _get("SNOWFLAKE_WAREHOUSE", "warehouse")
DATABASE  = _get("SNOWFLAKE_DATABASE",  "database",  "DB_BI_P_EDW")
SCHEMA    = _get("SNOWFLAKE_SCHEMA",    "schema",    "CCBCC_RCT_SELFSERVICE")
ROLE      = _get("SNOWFLAKE_ROLE",      "role")

# Validate mandatory params
missing = [name for name, val in [("ACCOUNT", ACCOUNT), ("USER", USER)] if not val]
if missing:
    print(
        f"\nERROR: Missing required Snowflake parameters: {', '.join(missing)}\n"
        "Set them as environment variables:\n"
        "  $env:SNOWFLAKE_ACCOUNT = 'your-account-identifier'\n"
        "  $env:SNOWFLAKE_USER    = 'your.email@domain.com'\n"
    )
    sys.exit(1)

print(f"\n{'─'*60}")
print(f"  account  : {ACCOUNT}")
print(f"  user     : {USER}")
print(f"  warehouse: {WAREHOUSE or '(default)'}")
print(f"  database : {DATABASE}")
print(f"  schema   : {SCHEMA}")
print(f"  role     : {ROLE or '(default)'}")
print(f"  auth     : externalbrowser")
print(f"  token cache: client_store_temporary_credential=True")
print(f"{'─'*60}\n")
print("Waiting for browser authentication …  (a browser tab should open)\n")
print("  (If token is cached from a prior run, browser will NOT open.)\n")

# ── 3. Connect ───────────────────────────────────────────────────────────────
conn_params: dict = {
    "account":                        ACCOUNT,
    "user":                           USER,
    "authenticator":                  "externalbrowser",
    "client_store_temporary_credential": True,  # cache SSO token locally
}
if WAREHOUSE:
    conn_params["warehouse"] = WAREHOUSE
if DATABASE:
    conn_params["database"] = DATABASE
if SCHEMA:
    conn_params["schema"] = SCHEMA
if ROLE:
    conn_params["role"] = ROLE

try:
    conn = snowflake.connector.connect(**conn_params)
    print("CONNECTED OK\n")
except Exception as exc:
    print(f"CONNECT FAILED: {exc}")
    sys.exit(2)

# ── 4. Identity / session query ──────────────────────────────────────────────
IDENTITY_SQL = (
    "SELECT "
    "CURRENT_USER()      AS \"user\", "
    "CURRENT_ROLE()      AS \"role\", "
    "CURRENT_WAREHOUSE() AS \"warehouse\", "
    "CURRENT_DATABASE()  AS \"database\", "
    "CURRENT_SCHEMA()    AS \"schema\", "
    "CURRENT_VERSION()   AS \"snowflake_version\";"
)

try:
    cur = conn.cursor()
    cur.execute(IDENTITY_SQL)
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    identity = dict(zip(cols, row))
    print("Session identity")
    print("─" * 40)
    for k, v in identity.items():
        print(f"  {k:<22}: {v}")
    print()
except Exception as exc:
    print(f"IDENTITY QUERY FAILED: {exc}")
    conn.close()
    sys.exit(3)

# ── 5. Data query — COUNT(*) against known mart ──────────────────────────────
# Use the database/schema that are actually set in the session; fall back to
# the configured ones so the query is always fully-qualified.
DB = identity.get("database") or DATABASE or "DB_BI_P_EDW"
SCH = identity.get("schema") or SCHEMA or "CCBCC_RCT_SELFSERVICE"

# Try the RCT forecast mart table first; gracefully fall back to a simple
# INFORMATION_SCHEMA count so the test succeeds even if the mart table hasn't
# been created yet.
MART_TABLE = f"{DB}.{SCH}.RCT_FORECAST_RUNS"
FALLBACK_SQL = f"SELECT COUNT(*) AS row_count FROM {DB}.INFORMATION_SCHEMA.TABLES LIMIT 1;"

DATA_SQL = f"SELECT COUNT(*) AS row_count FROM {MART_TABLE} LIMIT 1;"

try:
    cur.execute(DATA_SQL)
    (count,) = cur.fetchone()
    print(f"DATA QUERY OK — {MART_TABLE}")
    print(f"  row_count: {count}")
    print()
    print("QUERY OK\n")
except snowflake.connector.errors.ProgrammingError as exc:
    # Table may not exist yet — fall back to a metadata query
    print(
        f"  (mart table not found or no access: {exc})\n"
        f"  Falling back to: {FALLBACK_SQL}"
    )
    try:
        cur.execute(FALLBACK_SQL)
        (count,) = cur.fetchone()
        print(f"\nFALLBACK QUERY OK — INFORMATION_SCHEMA.TABLES")
        print(f"  row_count: {count}")
        print()
        print("QUERY OK (fallback)\n")
    except Exception as exc2:
        print(f"FALLBACK QUERY FAILED: {exc2}")
        conn.close()
        sys.exit(4)
except Exception as exc:
    print(f"DATA QUERY FAILED: {exc}")
    conn.close()
    sys.exit(4)

cur.close()
conn.close()
print("Connection closed.  All checks passed ✓")
