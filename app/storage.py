import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_minutes INTEGER NOT NULL CHECK (default_minutes BETWEEN 30 AND 1440 AND default_minutes % 30 = 0),
    default_rate_cents INTEGER NOT NULL CHECK (default_rate_cents BETWEEN 0 AND 1000000)
);
INSERT OR IGNORE INTO settings VALUES (1, 120, 0);
CREATE TABLE IF NOT EXISTS months (
    month TEXT PRIMARY KEY,
    rate_cents INTEGER NOT NULL CHECK (rate_cents BETWEEN 0 AND 1000000),
    paid INTEGER NOT NULL DEFAULT 0 CHECK (paid IN (0, 1))
);
CREATE TABLE IF NOT EXISTS entries (
    day TEXT PRIMARY KEY,
    month TEXT NOT NULL REFERENCES months(month),
    minutes INTEGER NOT NULL CHECK (minutes BETWEEN 30 AND 1440 AND minutes % 30 = 0),
    note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS entries_month ON entries(month);
CREATE TABLE IF NOT EXISTS login_limits (
    bucket TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    started REAL NOT NULL
);
"""


@contextmanager
def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize(path):
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


def settings(conn):
    return dict(conn.execute("SELECT default_minutes, default_rate_cents FROM settings WHERE id=1").fetchone())


def month_data(conn, month):
    data = conn.execute("SELECT * FROM months WHERE month=?", (month,)).fetchone()
    data = dict(data) if data else {"month": month, "rate_cents": settings(conn)["default_rate_cents"], "paid": 0}
    data["entries"] = [dict(row) for row in conn.execute("SELECT * FROM entries WHERE month=? ORDER BY day", (month,))]
    data["minutes"] = sum(row["minutes"] for row in data["entries"])
    data["days"] = len(data["entries"])
    return data


def ensure_month(conn, month):
    conn.execute("INSERT OR IGNORE INTO months(month,rate_cents) VALUES (?,?)", (month, settings(conn)["default_rate_cents"]))
