"""SQL for the eight tables."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_employee(
    connection: sqlite3.Connection, employee_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT employee_id, name, role, start_date
        FROM employees
        WHERE employee_id = ?
        """,
        (employee_id,),
    ).fetchone()


def list_equipment(
    connection: sqlite3.Connection, employee_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, employee_id, item, issued_on
        FROM equipment
        WHERE employee_id = ?
        ORDER BY issued_on, item
        """,
        (employee_id,),
    ).fetchall()


def list_policies(connection: sqlite3.Connection, role: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, role, item, max_count, refresh_years, effective_from, effective_to
        FROM policies
        WHERE role = ?
        ORDER BY item
        """,
        (role,),
    ).fetchall()


def insert_request(
    connection: sqlite3.Connection,
    *,
    employee_id: str,
    item: str,
    reason: str,
    submitted_on: str,
) -> int:
    now = _timestamp()
    cursor = connection.execute(
        """
        INSERT INTO requests (
            employee_id, item, reason, submitted_on, status, attempt,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
        """,
        (employee_id, item, reason, submitted_on, now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def claim_next(connection: sqlite3.Connection) -> sqlite3.Row | None:
    """Mark the oldest queued request running. A second caller cannot take it."""
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            """
            SELECT id
            FROM requests
            WHERE status = 'queued'
            ORDER BY created_at, id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            connection.execute("COMMIT")
            return None
        now = _timestamp()
        updated = connection.execute(
            """
            UPDATE requests
            SET status = 'running', updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, row["id"]),
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    if updated.rowcount != 1:
        return None
    return connection.execute(
        "SELECT * FROM requests WHERE id = ?",
        (row["id"],),
    ).fetchone()
