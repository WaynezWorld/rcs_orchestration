"""One-shot: check ALLOW_ID_TOKEN account parameter (reuses cached SSO token)."""
import snowflake.connector

conn = snowflake.connector.connect(
    account="CONA-CCCI",
    user="NBALJE",
    authenticator="externalbrowser",
    role="SNFL_PRD_BI_POWERUSER_FR",
    warehouse="BI_P_QRY_FIN_OPT_WH",
    client_store_temporary_credential=True,
)
cur = conn.cursor()
cur.execute("SHOW PARAMETERS LIKE 'ALLOW_ID_TOKEN' IN ACCOUNT")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]
print("\nALLOW_ID_TOKEN parameter:")
print("─" * 60)
for row in rows:
    d = dict(zip(cols, row))
    print(f"  key  : {d.get('key', d.get('name', '?'))}")
    print(f"  value: {d.get('value', '?')}")
    print(f"  type : {d.get('type', '?')}")
    print(f"  desc : {d.get('description', '?')}")
cur.close()
conn.close()
print("\nDone (no browser = token was cached ✓)")
