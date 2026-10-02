"""Include, exclude, hash, and ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from store import repository

_EMPLOYEE = "employee"
_EQUIPMENT = "equipment"
_POLICY = "policy"


def build_package(connection: sqlite3.Connection, request_id: int) -> dict:
    existing = repository.get_context_package(connection, request_id)
    if existing is not None:
        return _stored_package(connection, existing)

    request = repository.get_request(connection, request_id)
    if request is None:
        raise ValueError(f"request {request_id} does not exist")

    included, decisions, conflict = _decide(connection, request)
    canonical_json = json.dumps(included, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical_json.encode()).hexdigest()
    package_id = repository.insert_context_package(
        connection,
        request_id=request_id,
        canonical_json=canonical_json,
        content_hash=content_hash,
        conflict=conflict,
        decisions=decisions,
    )
    stored = repository.get_context_package(connection, request_id)
    if stored is None or int(stored["id"]) != package_id:
        raise RuntimeError("context package was not stored")
    return _stored_package(connection, stored)


def _decide(
    connection: sqlite3.Connection, request: sqlite3.Row
) -> tuple[list[dict], list[tuple[str, str, str, str]], bool]:
    subject = repository.get_employee(connection, request["employee_id"])
    included: list[dict] = []
    decisions: list[tuple[str, str, str, str]] = []

    for employee in repository.list_employees(connection):
        memory_id = f"employee:{employee['employee_id']}"
        if subject is not None and employee["employee_id"] == subject["employee_id"]:
            included.append(
                {
                    "employee_id": employee["employee_id"],
                    "kind": _EMPLOYEE,
                    "memory_id": memory_id,
                    "name": employee["name"],
                    "role": employee["role"],
                    "start_date": employee["start_date"],
                }
            )
            decisions.append((memory_id, _EMPLOYEE, "include", "include_subject"))
        else:
            decisions.append(
                (memory_id, _EMPLOYEE, "exclude", "exclude_other_employee")
            )

    subject_id = subject["employee_id"] if subject is not None else None
    for item in repository.list_all_equipment(connection):
        memory_id = f"equipment:{item['id']}"
        if subject_id is not None and item["employee_id"] == subject_id:
            included.append(
                {
                    "employee_id": item["employee_id"],
                    "issued_on": item["issued_on"],
                    "item": item["item"],
                    "kind": _EQUIPMENT,
                    "memory_id": memory_id,
                }
            )
            decisions.append((memory_id, _EQUIPMENT, "include", "include_equipment"))
        else:
            decisions.append(
                (memory_id, _EQUIPMENT, "exclude", "exclude_other_equipment")
            )

    conflict = False
    if subject is not None:
        matching = [
            policy
            for policy in repository.list_all_policies(connection)
            if policy["role"] == subject["role"] and policy["item"] == request["item"]
        ]
        current = [
            policy
            for policy in matching
            if _is_current(policy["effective_to"], request["submitted_on"])
        ]
        conflict = len(current) > 1
        current_ids = {policy["id"] for policy in current}
        for policy in matching:
            memory_id = f"policy:{policy['id']}"
            if policy["id"] in current_ids and conflict:
                decisions.append((memory_id, _POLICY, "exclude", "exclude_conflict"))
            elif policy["id"] in current_ids:
                included.append(
                    {
                        "effective_from": policy["effective_from"],
                        "effective_to": policy["effective_to"],
                        "item": policy["item"],
                        "kind": _POLICY,
                        "max_count": policy["max_count"],
                        "memory_id": memory_id,
                        "refresh_years": policy["refresh_years"],
                        "role": policy["role"],
                    }
                )
                decisions.append(
                    (memory_id, _POLICY, "include", "include_active_policy")
                )
            else:
                decisions.append((memory_id, _POLICY, "exclude", "exclude_stale_policy"))

    included.sort(key=lambda fact: fact["memory_id"])
    decisions.sort(key=lambda decision: decision[0])
    return included, decisions, conflict


def _is_current(effective_to: str | None, submitted_on: str) -> bool:
    return effective_to is None or effective_to >= submitted_on


def _stored_package(connection: sqlite3.Connection, package: sqlite3.Row) -> dict:
    decisions = [
        {
            "memory_id": row["memory_id"],
            "memory_kind": row["memory_kind"],
            "outcome": row["outcome"],
            "reason_code": row["reason_code"],
        }
        for row in repository.list_context_decisions(connection, package["id"])
    ]
    return {
        "package_id": package["id"],
        "content_hash": package["content_hash"],
        "conflict": bool(package["conflict"]),
        "canonical_json": package["canonical_json"],
        "included": json.loads(package["canonical_json"]),
        "decisions": decisions,
    }
