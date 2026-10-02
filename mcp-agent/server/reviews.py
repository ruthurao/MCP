"""Append-only review log. Ticket ids are a hash. A repeat returns the same id."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from server.policy import ESCALATION_REASONS, normalize_employee_id

FIELDS = ("ticket_id", "employee_id", "request", "reason")


def log_path(connection: sqlite3.Connection) -> Path:
    row = connection.execute("PRAGMA database_list").fetchone()
    file = row["file"] if row is not None else ""
    if not file:
        raise RuntimeError("review log needs a database file")
    return Path(file).with_name("review_queue.jsonl")


def normalize_request_text(text: str) -> str:
    return " ".join(text.split())


def make_ticket_id(employee_id: str, request: str, reason: str) -> str:
    payload = f"{employee_id}|{request}|{reason}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"RVW-{digest}"


def read_entries(path: Path) -> tuple[list[dict], list[int]]:
    if not path.exists():
        return [], []
    entries: list[dict] = []
    corrupt: list[int] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            corrupt.append(number)
            continue
        if not isinstance(obj, dict) or set(obj) != set(FIELDS):
            corrupt.append(number)
            continue
        if any(not isinstance(obj[field], str) or obj[field] == "" for field in FIELDS):
            corrupt.append(number)
            continue
        entries.append({field: obj[field] for field in FIELDS})
    return entries, corrupt


def append_review(
    connection: sqlite3.Connection, employee_id: str, request: str, reason: str
) -> dict:
    """Write one line when the reason is an escalation code. Anything else writes nothing."""
    if reason not in ESCALATION_REASONS:
        return {"ok": False, "ticket_id": None, "duplicate": False}

    normalized = normalize_employee_id(employee_id)
    stored_id = normalized if normalized else normalize_request_text(employee_id)
    stored_request = normalize_request_text(request)
    ticket_id = make_ticket_id(stored_id, stored_request, reason)
    path = log_path(connection)
    entries, _corrupt = read_entries(path)
    if any(entry["ticket_id"] == ticket_id for entry in entries):
        return {"ok": True, "ticket_id": ticket_id, "duplicate": True}

    record = {
        "ticket_id": ticket_id,
        "employee_id": stored_id,
        "request": stored_request,
        "reason": reason,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return {"ok": True, "ticket_id": ticket_id, "duplicate": False}


def ticket_on_file(connection: sqlite3.Connection, ticket_id: str) -> bool:
    entries, _corrupt = read_entries(log_path(connection))
    return any(entry["ticket_id"] == ticket_id for entry in entries)
