import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import date, timedelta
from .domain import frequency_value, month_value, week_value, week_start, earnings

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_minutes INTEGER NOT NULL CHECK (default_minutes BETWEEN 30 AND 1440 AND default_minutes % 30 = 0),
    default_rate_cents INTEGER NOT NULL CHECK (default_rate_cents BETWEEN 0 AND 1000000)
);
INSERT OR IGNORE INTO settings(id,default_minutes,default_rate_cents) VALUES (1, 120, 0);
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
        conn.execute("BEGIN IMMEDIATE")
        if "payment_frequency" not in {r[1] for r in conn.execute("PRAGMA table_info(settings)")}:
            conn.execute("ALTER TABLE settings ADD COLUMN payment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK(payment_frequency IN ('monthly','weekly'))")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
        if "rate_cents" not in columns:
            conn.execute("ALTER TABLE entries ADD COLUMN rate_cents INTEGER NOT NULL DEFAULT 0 CHECK(rate_cents BETWEEN 0 AND 1000000)")
            conn.execute("UPDATE entries SET rate_cents=(SELECT rate_cents FROM months WHERE month=entries.month)")
        if "paid" not in columns:
            conn.execute("ALTER TABLE entries ADD COLUMN paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN (0,1))")
            conn.execute("UPDATE entries SET paid=(SELECT paid FROM months WHERE month=entries.month)")
        conn.execute("CREATE TABLE IF NOT EXISTS weeks(week TEXT PRIMARY KEY,rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 1000000))")


def settings(conn):
    return dict(conn.execute("SELECT default_minutes, default_rate_cents, payment_frequency FROM settings WHERE id=1").fetchone())


def month_data(conn, month):
    return period_data(conn, "monthly", month)


def ensure_month(conn, month):
    conn.execute("INSERT OR IGNORE INTO months(month,rate_cents) VALUES (?,?)", (month, settings(conn)["default_rate_cents"]))


def bounds(frequency, key):
    frequency_value(frequency)
    if frequency == "monthly":
        month_value(key)
        start = date.fromisoformat(key + "-01")
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1)
    else:
        start = date.fromisoformat(week_value(key))
        end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def period_data(conn, frequency, key):
    start, end = bounds(frequency, key)
    table, column = ("months", "month") if frequency == "monthly" else ("weeks", "week")
    row = conn.execute(f"SELECT rate_cents FROM {table} WHERE {column}=?", (key,)).fetchone()
    default = row[0] if row else settings(conn)["default_rate_cents"]
    entries = [dict(r) for r in conn.execute("SELECT * FROM entries WHERE day BETWEEN ? AND ? ORDER BY day", (start, end))]
    minutes = sum(r["minutes"] for r in entries)
    numerator = sum(r["minutes"] * r["rate_cents"] for r in entries)
    paid_numerator = sum(r["minutes"] * r["rate_cents"] for r in entries if r["paid"])
    total, paid_total = earnings(numerator, 1), earnings(paid_numerator, 1)
    paid_days = sum(bool(r["paid"]) for r in entries)
    rates = {r["rate_cents"] for r in entries}
    if row is None and len(rates) == 1:
        default = next(iter(rates))
    signature = hashlib.sha256("".join(f"{r['day']}:{r['minutes']}:{r['rate_cents']}:{r['paid']}:{r['revision']};" for r in entries).encode()).hexdigest()
    return {"frequency": frequency, "key": key, "month": key if frequency == "monthly" else start[:7],
            "start": start, "end": end, "rate_cents": next(iter(rates)) if len(rates) == 1 else default,
            "default_rate_cents": default, "mixed_rates": len(rates) > 1, "entries": entries,
            "minutes": minutes, "days": len(entries), "paid_days": paid_days,
            "paid": int(bool(entries) and paid_days == len(entries)), "partial": 0 < paid_days < len(entries),
            "total": total, "paid_total": paid_total, "pending_total": total - paid_total, "signature": signature}


def entry_rate(conn, day):
    prefs = settings(conn)
    if prefs["payment_frequency"] == "weekly":
        key = week_start(day)
        cents = period_data(conn, "weekly", key)["default_rate_cents"]
        conn.execute("INSERT OR IGNORE INTO weeks VALUES (?,?)", (key, cents))
        return conn.execute("SELECT rate_cents FROM weeks WHERE week=?", (key,)).fetchone()[0]
    ensure_month(conn, day[:7])
    return conn.execute("SELECT rate_cents FROM months WHERE month=?", (day[:7],)).fetchone()[0]


def set_period_rate(conn, frequency, key, cents):
    start, end = bounds(frequency, key)
    table, column = ("months", "month") if frequency == "monthly" else ("weeks", "week")
    if frequency == "monthly":
        ensure_month(conn, key)
    else:
        conn.execute("INSERT OR IGNORE INTO weeks VALUES (?,?)", (key, cents))
    conn.execute(f"UPDATE {table} SET rate_cents=? WHERE {column}=?", (cents, key))
    conn.execute("UPDATE entries SET paid=CASE WHEN rate_cents!=? THEN 0 ELSE paid END, rate_cents=?,revision=revision+1 WHERE day BETWEEN ? AND ?", (cents, cents, start, end))


def set_period_paid(conn, frequency, key, paid, signature=None, expected_minutes=None, expected_rate=None):
    data = period_data(conn, frequency, key)
    if not data["days"]:
        raise ValueError("Añade horas antes de marcar el periodo como cobrado.")
    if (signature and signature != data["signature"]) or (not signature and (str(data["minutes"]) != str(expected_minutes) or str(data["rate_cents"]) != str(expected_rate))):
        raise ValueError("El total ha cambiado. Revisa el periodo antes de marcar el cobro.")
    conn.execute("UPDATE entries SET paid=? WHERE day BETWEEN ? AND ?", (paid, data["start"], data["end"]))
