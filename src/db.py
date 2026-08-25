import sqlite3
import json
import gzip
from typing import List, Any

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS runs (
        event_id TEXT PRIMARY KEY,
        compressed_data BLOB NOT NULL,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

def insert_run(conn: sqlite3.Connection, event_id: str, compressed_data: dict) -> bool:
    c = conn.cursor()
    json_str = json.dumps(compressed_data, ensure_ascii=False)
    compressed_bytes = gzip.compress(json_str.encode('utf-8'))
    c.execute("INSERT OR IGNORE INTO runs (event_id, compressed_data) VALUES (?, ?)", (event_id, compressed_bytes))
    conn.commit()
    return c.rowcount > 0

def get_all_compressed_runs(conn: sqlite3.Connection) -> List[Any]:
    c = conn.cursor()
    c.execute("SELECT compressed_data FROM runs")
    rows = c.fetchall()
    result = []
    for row in rows:
        json_str = gzip.decompress(row[0]).decode('utf-8')
        data = json.loads(json_str)
        result.append(data)
    return result

def get_run_count(conn: sqlite3.Connection) -> int:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM runs")
    return c.fetchone()[0]