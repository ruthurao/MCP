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


def get_request(connection: sqlite3.Connection, request_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()


def save_trace(connection: sqlite3.Connection, request_id: int, trace: str) -> None:
    connection.execute(
        """
        UPDATE requests
        SET trace = ?, updated_at = ?
        WHERE id = ?
        """,
        (trace, _timestamp(), request_id),
    )
    connection.commit()


def list_employees(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT employee_id, name, role, start_date
        FROM employees
        ORDER BY employee_id
        """
    ).fetchall()


def list_all_equipment(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, employee_id, item, issued_on
        FROM equipment
        ORDER BY id
        """
    ).fetchall()


def list_all_policies(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, role, item, max_count, refresh_years, effective_from, effective_to
        FROM policies
        ORDER BY id
        """
    ).fetchall()


def get_context_package(
    connection: sqlite3.Connection, request_id: int
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM context_packages WHERE request_id = ?",
        (request_id,),
    ).fetchone()


def list_context_decisions(
    connection: sqlite3.Connection, package_id: int
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT memory_id, memory_kind, outcome, reason_code
        FROM context_decisions
        WHERE package_id = ?
        ORDER BY memory_id
        """,
        (package_id,),
    ).fetchall()


def insert_context_package(
    connection: sqlite3.Connection,
    *,
    request_id: int,
    canonical_json: str,
    content_hash: str,
    conflict: bool,
    decisions: list[tuple[str, str, str, str]],
) -> int:
    now = _timestamp()
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT id FROM context_packages WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if existing is not None:
            connection.execute("COMMIT")
            return int(existing["id"])
        cursor = connection.execute(
            """
            INSERT INTO context_packages (
                request_id, canonical_json, content_hash, conflict, built_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (request_id, canonical_json, content_hash, int(conflict), now),
        )
        package_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO context_decisions (
                package_id, memory_id, memory_kind, outcome, reason_code
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [(package_id, *decision) for decision in decisions],
        )
        connection.execute(
            """
            UPDATE requests
            SET context_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (content_hash, now, request_id),
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return package_id


def insert_audit(
    connection: sqlite3.Connection,
    *,
    request_id: int,
    actor: str,
    action: str,
    detail: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO audit_log (request_id, actor, action, detail, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (request_id, actor, action, detail, _timestamp()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def list_audit_log(connection: sqlite3.Connection, request_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT actor, action, detail
        FROM audit_log
        WHERE request_id = ?
        ORDER BY id
        """,
        (request_id,),
    ).fetchall()


def insert_review(
    connection: sqlite3.Connection,
    *,
    employee_id: str,
    request: str,
    reason: str,
    package_hash: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO review_queue (
            employee_id, request, reason, package_hash, status, created_at
        ) VALUES (?, ?, ?, ?, 'open', ?)
        """,
        (employee_id, request, reason, package_hash, _timestamp()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def list_reviews(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT id, employee_id, request, reason, package_hash, status
        FROM review_queue
        ORDER BY id
        """
    ).fetchall()
