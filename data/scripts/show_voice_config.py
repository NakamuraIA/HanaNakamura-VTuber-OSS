import sqlite3, json

c = sqlite3.connect(r"E:\local-hana-oss\runtime\hana_memory.sqlite3")
v = json.loads(c.execute("SELECT value_json FROM settings WHERE key='voice_config'").fetchone()[0])
for k, val in v.items():
    print(f"{k} = {val}")
