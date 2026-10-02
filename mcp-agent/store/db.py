"""Schema, WAL, and connection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    start_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    item TEXT NOT NULL,
    issued_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    item TEXT NOT NULL,
    max_count INTEGER NOT NULL,
    refresh_years INTEGER NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    item TEXT NOT NULL,
    reason TEXT NOT NULL,
    submitted_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'approved', 'denied', 'escalated')
    ),
    attempt INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    decision TEXT,
    trace TEXT,
    context_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_packages (
    id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    canonical_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    conflict INTEGER NOT NULL DEFAULT 0,
    built_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_decisions (
    id INTEGER PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES context_packages(id),
    memory_id TEXT NOT NULL,
    memory_kind TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('include', 'exclude')),
    reason_code TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY,
    employee_id TEXT NOT NULL,
    request TEXT NOT NULL,
    reason TEXT NOT NULL,
    package_hash TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    request_id INTEGER,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()
