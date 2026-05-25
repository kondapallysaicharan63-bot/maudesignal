"""Ground-truth queries — run against the real SQLite DB."""

import json
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
db_path_str = os.environ.get("MAUDESIGNAL_DB_PATH", "data/maudesignal.db")
db_path = (PROJECT_ROOT / db_path_str).resolve()
print(f"DB: {db_path}  exists={db_path.exists()}")

con = sqlite3.connect(db_path)
cur = con.cursor()

# --- counts ---
raw = cur.execute("SELECT COUNT(*) FROM raw_reports").fetchone()[0]
norm = cur.execute("SELECT COUNT(*) FROM normalized_events").fetchone()[0]
ext_all = cur.execute("SELECT COUNT(*) FROM extractions").fetchone()[0]
ext_narr = cur.execute(
    "SELECT COUNT(*) FROM extractions WHERE skill_name='maude-narrative-extractor'"
).fetchone()[0]
ext_sev = cur.execute(
    "SELECT COUNT(*) FROM extractions WHERE skill_name='severity-triage'"
).fetchone()[0]
ext_cls = cur.execute(
    "SELECT COUNT(*) FROM extractions WHERE skill_name='ai-failure-mode-classifier'"
).fetchone()[0]

print("\n=== COUNTS ===")
print(f"raw_reports:            {raw}")
print(f"normalized_events:      {norm}")
print(f"extractions (all):      {ext_all}")
print(f"  maude-narrative-extractor: {ext_narr}")
print(f"  severity-triage:           {ext_sev}")
print(f"  ai-failure-mode-classifier:{ext_cls}")

# --- AI signals (ai_related_flag=true in narrative extractor rows) ---
rows = cur.execute(
    "SELECT output_json FROM extractions WHERE skill_name='maude-narrative-extractor'"
).fetchall()
ai_count = sum(1 for (j,) in rows if json.loads(j).get("ai_related_flag") is True)
print("\n=== DASHBOARD KPIs ===")
print(f"AI Signals Detected (ai_related_flag=True): {ai_count}")

confs = [
    json.loads(j).get("confidence_score", 0)
    for (j,) in rows
    if json.loads(j).get("confidence_score") is not None
]
avg_conf = sum(confs) / len(confs) if confs else 0
print(f"Avg Confidence (narrative extractor):        {avg_conf:.3f}")

# --- severity breakdown ---
print("\n=== SEVERITY DISTRIBUTION ===")
sev_rows = cur.execute(
    "SELECT output_json FROM extractions WHERE skill_name='maude-narrative-extractor'"
).fetchall()
sev_counts = {}
for (j,) in sev_rows:
    s = json.loads(j).get("severity", "unknown") or "unknown"
    sev_counts[s] = sev_counts.get(s, 0) + 1
for k, v in sorted(sev_counts.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

# --- failure modes ---
print("\n=== FAILURE MODES ===")
cls_rows = cur.execute(
    "SELECT output_json FROM extractions WHERE skill_name='ai-failure-mode-classifier'"
).fetchall()
fm_counts = {}
for (j,) in cls_rows:
    fm = json.loads(j).get("failure_mode_category", "unknown") or "unknown"
    fm_counts[fm] = fm_counts.get(fm, 0) + 1
for k, v in sorted(fm_counts.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

# --- alert rules ---
rules = cur.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0]
active_rules = cur.execute("SELECT COUNT(*) FROM alert_rules WHERE active=1").fetchone()[0]
print("\n=== ALERTS ===")
print(f"Alert rules (total): {rules}  active: {active_rules}")

# --- llm cost ---
cost = cur.execute("SELECT SUM(cost_estimate_usd) FROM llm_audit_log").fetchone()[0] or 0.0
print("\n=== LLM COST ===")
print(f"Total: ${cost:.4f}")

# --- catalog ---
cat = cur.execute("SELECT COUNT(*) FROM device_catalog").fetchone()[0]
print("\n=== CATALOG ===")
print(f"Catalog devices: {cat}")

# --- psur ---
psur = cur.execute("SELECT COUNT(*) FROM psur_reports").fetchone()[0]
print("\n=== PSUR ===")
print(f"PSUR reports: {psur}")

# --- unprocessed events (pending extraction) ---
extracted_ids = {
    r[0]
    for r in cur.execute(
        "SELECT DISTINCT maude_report_id FROM extractions WHERE skill_name='maude-narrative-extractor'"
    ).fetchall()
}
all_event_ids = {
    r[0] for r in cur.execute("SELECT maude_report_id FROM normalized_events").fetchall()
}
pending = len(all_event_ids - extracted_ids)
print("\n=== EXTRACTION QUEUE ===")
print(f"Total normalized events: {len(all_event_ids)}")
print(f"Already extracted:       {len(extracted_ids)}")
print(f"Pending:                 {pending}")

# --- recent signals (last 5) ---
recent = cur.execute(
    "SELECT maude_report_id, skill_name, confidence_score, extraction_ts FROM extractions "
    "WHERE skill_name='maude-narrative-extractor' ORDER BY extraction_ts DESC LIMIT 5"
).fetchall()
print("\n=== RECENT SIGNALS (top 5) ===")
for row in recent:
    print(f"  {row[3]}  {row[0]}  conf={row[2]}")

con.close()
print("\nDONE")
