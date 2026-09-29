from __future__ import annotations

import json
import sqlite3
from deals_v13.config import Settings


st = Settings.from_env()
conn = sqlite3.connect(st.db_path)
conn.row_factory = sqlite3.Row

print('=== V13 DEAL STATS ===')
rows = conn.execute("SELECT store,lane,state,COUNT(*) n FROM deals GROUP BY store,lane,state ORDER BY store,lane,state").fetchall()
for r in rows:
    print(f"{r['store']:7} {r['lane']:6} {r['state']:11} {r['n']}")

print('\n=== TOP SOURCES ===')
rows = conn.execute("""
SELECT store,source,category,scans,candidates,verified,sent,errors,
       ROUND(CAST(verified AS REAL)/CASE WHEN candidates=0 THEN 1 ELSE candidates END,3) verify_rate
FROM source_health
ORDER BY sent DESC, verified DESC, candidates DESC LIMIT 30
""").fetchall()
for r in rows:
    print(json.dumps(dict(r), ensure_ascii=False))
