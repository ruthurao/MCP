"""Insert a queued request from one sentence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from server.policy import classify_items
from store.db import connect, create_schema
from store.repository import insert_request
from store.seed import seed

DEMO_DATE = "2026-09-30"


def parse_sentence(sentence: str) -> tuple[str, str, str]:
    if ":" not in sentence:
        raise ValueError("sentence needs an employee id and a colon")
    employee_id, remainder = sentence.split(":", 1)
    employee_id = employee_id.strip()
    reason = remainder.strip()
    if not employee_id or not reason:
        raise ValueError("sentence needs an employee id and a reason")
    return employee_id, _item(reason), reason


def open_database(path: str | Path) -> sqlite3.Connection:
    connection = connect(path)
    create_schema(connection)
    count = connection.execute("SELECT COUNT(*) AS count FROM employees").fetchone()["count"]
    if count == 0:
        seed(connection)
    return connection


def submit(
    connection: sqlite3.Connection,
    sentence: str,
    submitted_on: str = DEMO_DATE,
) -> int:
    employee_id, item, reason = parse_sentence(sentence)
    return insert_request(
        connection,
        employee_id=employee_id,
        item=item,
        reason=reason,
        submitted_on=submitted_on,
    )


def _item(reason: str) -> str:
    found = classify_items(reason)
    if not found:
        return reason
    return found[0]
