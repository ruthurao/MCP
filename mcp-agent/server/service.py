"""Package, four operations, and audit writes."""

from __future__ import annotations

import sqlite3
from datetime import date

from server.context import build_package
from server.policy import check_eligibility
from server.reviews import append_review
from store import repository

_ACTOR = "service"


def get_employee_info(
    connection: sqlite3.Connection, request_id: int, employee_id: str
) -> dict:
    package = build_package(connection, request_id)
    subject = _included_employee(package)
    equipment = [
        {"item": fact["item"], "issued_on": fact["issued_on"]}
        for fact in package["included"]
        if fact["kind"] == "equipment"
    ]
    found = subject is not None and subject["employee_id"] == employee_id
    request = repository.get_request(connection, request_id)
    result = (
        {
            "found": True,
            "employee_id": subject["employee_id"],
            "name": subject["name"],
            "role": subject["role"],
            "start_date": subject["start_date"],
            "tenure_days": _tenure_days(subject["start_date"], request["submitted_on"]),
            "equipment": equipment,
        }
        if found
        else {"found": False}
    )
    _audit(
        connection,
        request_id,
        "get_employee_info",
        f"employee_id={employee_id} found={result['found']}",
    )
    return result


def get_policy_limits(connection: sqlite3.Connection, request_id: int, role: str) -> dict:
    package = build_package(connection, request_id)
    subject = _included_employee(package)
    limits = {
        fact["item"]: {
            "max_count": fact["max_count"],
            "refresh_years": fact["refresh_years"],
            "memory_id": fact["memory_id"],
        }
        for fact in package["included"]
        if fact["kind"] == "policy" and fact["role"] == role
    }
    found = subject is not None and subject["role"] == role and bool(limits)
    result = {"found": True, "role": role, "limits": limits} if found else {"found": False}
    _audit(
        connection,
        request_id,
        "get_policy_limits",
        f"role={role} found={result['found']}",
    )
    return result


def check_request_eligibility(
    connection: sqlite3.Connection,
    request_id: int,
    employee_id: str,
    item: str,
    request_text: str | None = None,
) -> dict:
    package = build_package(connection, request_id)
    request = repository.get_request(connection, request_id)
    text = request["reason"] if not request_text else request_text
    result = _eligibility(package, request["submitted_on"], employee_id, item, text)
    _audit(
        connection,
        request_id,
        "check_request_eligibility",
        (
            f"employee_id={employee_id} item={item} "
            f"status={result['status']} reason_code={result['reason_code']}"
        ),
    )
    return result


def flag_for_human_review(
    connection: sqlite3.Connection,
    request_id: int,
    employee_id: str,
    request_text: str,
    reason: str,
) -> dict:
    build_package(connection, request_id)
    if reason is None or not str(reason).strip():
        _audit(
            connection,
            request_id,
            "flag_for_human_review",
            "rejected empty reason",
        )
        return {"ok": False, "error": "reason is required", "ticket_id": None, "duplicate": False}
    result = append_review(connection, employee_id, request_text, reason.strip())
    if not result["ok"]:
        _audit(
            connection,
            request_id,
            "flag_for_human_review",
            f"rejected reason {reason.strip()}",
        )
        return result
    _audit(
        connection,
        request_id,
        "flag_for_human_review",
        f"ticket_id={result['ticket_id']} duplicate={result['duplicate']}",
    )
    return result


def _eligibility(
    package: dict,
    submitted_on: str,
    employee_id: str,
    item: str,
    request_text: str,
) -> dict:
    subject = _included_employee(package)
    equipment = [
        {"item": fact["item"], "issued_on": fact["issued_on"]}
        for fact in package["included"]
        if fact["kind"] == "equipment"
    ]
    employee = None
    if subject is not None:
        employee = {
            "employee_id": subject["employee_id"],
            "name": subject["name"],
            "role": subject["role"],
            "start_date": subject["start_date"],
            "equipment": equipment,
        }
    policies = [
        fact
        for fact in package["included"]
        if fact["kind"] == "policy" and fact["item"] == item
    ]
    policy = policies[0] if policies else None
    return check_eligibility(
        employee_id,
        item,
        request_text,
        as_of=date.fromisoformat(submitted_on),
        employee=employee,
        policy=policy,
        conflict=bool(package["conflict"]),
    )


def _included_employee(package: dict) -> dict | None:
    for fact in package["included"]:
        if fact["kind"] == "employee":
            return fact
    return None


def _tenure_days(start: str, on: str) -> int:
    return (date.fromisoformat(on) - date.fromisoformat(start)).days


def _audit(connection: sqlite3.Connection, request_id: int, action: str, detail: str) -> None:
    repository.insert_audit(
        connection,
        request_id=request_id,
        actor=_ACTOR,
        action=action,
        detail=detail,
    )
