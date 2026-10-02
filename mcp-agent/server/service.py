"""Package, four operations, and audit writes."""

from __future__ import annotations

import sqlite3
from datetime import date

from server.context import build_package
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
    result = (
        {
            "found": True,
            "employee_id": subject["employee_id"],
            "role": subject["role"],
            "start_date": subject["start_date"],
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
    limits = [
        {
            "item": fact["item"],
            "max_count": fact["max_count"],
            "refresh_years": fact["refresh_years"],
            "memory_id": fact["memory_id"],
        }
        for fact in package["included"]
        if fact["kind"] == "policy" and fact["role"] == role
    ]
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
    connection: sqlite3.Connection, request_id: int, employee_id: str, item: str
) -> dict:
    package = build_package(connection, request_id)
    request = repository.get_request(connection, request_id)
    result = _eligibility(package, request["submitted_on"], employee_id, item)
    _audit(
        connection,
        request_id,
        "check_request_eligibility",
        f"employee_id={employee_id} item={item} status={result['status']}",
    )
    return result


def flag_for_human_review(
    connection: sqlite3.Connection,
    request_id: int,
    employee_id: str,
    request_text: str,
    reason: str,
) -> dict:
    package = build_package(connection, request_id)
    if reason is None or not reason.strip():
        _audit(
            connection,
            request_id,
            "flag_for_human_review",
            "rejected empty reason",
        )
        return {"ok": False, "error": "reason is required"}
    review_id = repository.insert_review(
        connection,
        employee_id=employee_id,
        request=request_text,
        reason=reason.strip(),
        package_hash=package["content_hash"],
    )
    _audit(
        connection,
        request_id,
        "flag_for_human_review",
        f"review_id={review_id}",
    )
    return {"ok": True, "review_id": review_id}


def _eligibility(
    package: dict, submitted_on: str, employee_id: str, item: str
) -> dict:
    subject = _included_employee(package)
    if subject is None or subject["employee_id"] != employee_id:
        return {
            "status": "unknown",
            "rule_id": None,
            "detail": "Employee is not in the package.",
        }
    if package["conflict"]:
        return {
            "status": "unknown",
            "rule_id": None,
            "detail": "Two current rules conflict for this item.",
        }
    policies = [
        fact
        for fact in package["included"]
        if fact["kind"] == "policy" and fact["item"] == item
    ]
    if not policies:
        return {
            "status": "unknown",
            "rule_id": None,
            "detail": "Item is not in the catalog.",
        }
    policy = policies[0]
    owned = [
        fact
        for fact in package["included"]
        if fact["kind"] == "equipment" and fact["item"] == item
    ]
    if len(owned) < policy["max_count"]:
        return {
            "status": "eligible",
            "rule_id": policy["memory_id"],
            "detail": f"Count is {len(owned)} of {policy['max_count']}.",
        }
    newest = max(fact["issued_on"] for fact in owned)
    next_eligible = _add_years(newest, policy["refresh_years"])
    if submitted_on >= next_eligible:
        return {
            "status": "eligible",
            "rule_id": policy["memory_id"],
            "detail": f"Refresh window is open. Next eligible was {next_eligible}.",
        }
    return {
        "status": "ineligible",
        "rule_id": policy["memory_id"],
        "detail": (
            f"Newest {item} is inside the {policy['refresh_years']}-year window. "
            f"Next eligible {next_eligible}."
        ),
        "next_eligible_on": next_eligible,
    }


def _included_employee(package: dict) -> dict | None:
    for fact in package["included"]:
        if fact["kind"] == "employee":
            return fact
    return None


def _add_years(iso_date: str, years: int) -> str:
    year, month, day = (int(part) for part in iso_date.split("-"))
    try:
        return date(year + years, month, day).isoformat()
    except ValueError:
        return date(year + years, month, 28).isoformat()


def _audit(connection: sqlite3.Connection, request_id: int, action: str, detail: str) -> None:
    repository.insert_audit(
        connection,
        request_id=request_id,
        actor=_ACTOR,
        action=action,
        detail=detail,
    )
