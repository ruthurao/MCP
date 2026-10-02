"""Claim queued requests and record one employee lookup."""

from __future__ import annotations

import sqlite3

from client.agent import lookup_employee
from store.repository import claim_next, get_request, save_trace


def run(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    claimed: list[sqlite3.Row] = []
    while True:
        row = claim_next(connection)
        if row is None:
            return claimed
        trace = lookup_employee(_database_path(connection), row["id"], row["employee_id"])
        save_trace(connection, row["id"], trace)
        stored = get_request(connection, row["id"])
        if stored is None:
            raise RuntimeError(f"request {row['id']} disappeared after claim")
        claimed.append(stored)


def _database_path(connection: sqlite3.Connection) -> str:
    path = connection.execute("PRAGMA database_list").fetchone()["file"]
    if not path:
        raise RuntimeError("worker needs a database file")
    return path
