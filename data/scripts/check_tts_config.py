import sqlite3

for db in [r"E:\local-hana-oss\runtime\hana_agent_oss.sqlite3",
           r"E:\local-hana-oss\runtime\hana_memory.sqlite3"]:
    print("=== DB:", db)
    c = sqlite3.connect(db)
    cur = c.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    hits = [t for t in tables if any(k in t.lower() for k in ("tts", "voice", "setting", "config", "speaker"))]
    print("tables:", tables)
    print("hits:", hits)
    for t in hits:
        cols = [d[1] for d in cur.execute(f"PRAGMA table_info({t})")]
        print(f"\n-- {t} {cols}")
        for row in cur.execute(f"SELECT * FROM {t} LIMIT 8"):
            s = str(row)
            print(s[:400])
    c.close()
