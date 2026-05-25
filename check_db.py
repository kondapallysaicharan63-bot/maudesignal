import sqlite3
conn = sqlite3.connect("data/safesignal.db")
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM extractions")
print("Total extractions:", c.fetchone()[0])
c.execute("SELECT skill_name, COUNT(*) FROM extractions GROUP BY skill_name")
print("By skill:")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
c.execute("SELECT COUNT(DISTINCT maude_report_id) FROM extractions WHERE skill_name='maude-narrative-extractor'")
print("Unique records with extractor:", c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM normalized_events WHERE maude_report_id NOT IN (SELECT maude_report_id FROM extractions WHERE skill_name='maude-narrative-extractor')")
print("Records with no extractor row:", c.fetchone()[0])
conn.close()
