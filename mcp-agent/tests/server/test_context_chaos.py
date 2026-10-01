"""Stale, restricted, and conflicting rows."""

from __future__ import annotations

from pathlib import Path

from server.context import build_package
from store.db import connect, create_schema
from store.repository import insert_request
from store.seed import seed


def _connection(tmp_path: Path):
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    return connection


def _reasons(package: dict) -> dict[str, str]:
    return {
        decision["memory_id"]: decision["reason_code"]
        for decision in package["decisions"]
    }


def test_stale_higher_monitor_cap_stays_out_of_the_hash(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    cursor = connection.execute(
        """
        INSERT INTO policies (
            role, item, max_count, refresh_years, effective_from, effective_to
        ) VALUES ('ic', 'monitor', 2, 3, '2020-01-01', '2025-09-30')
        """
    )
    stale_id = int(cursor.lastrowid)
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="I want a bigger second monitor.",
        submitted_on="2026-09-30",
    )

    package = build_package(connection, request_id)

    assert _reasons(package)[f"policy:{stale_id}"] == "exclude_stale_policy"
    included_caps = [
        fact["max_count"]
        for fact in package["included"]
        if fact["kind"] == "policy" and fact["item"] == "monitor"
    ]
    assert included_caps == [1]
    assert package["conflict"] is False


def test_other_employees_laptop_is_excluded_from_priyas_request(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    laptop = connection.execute(
        """
        SELECT id FROM equipment
        WHERE employee_id = 'E1002' AND item = 'laptop'
        """
    ).fetchone()
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="I want a bigger second monitor.",
        submitted_on="2026-09-30",
    )

    package = build_package(connection, request_id)
    reasons = _reasons(package)

    assert reasons["employee:E1002"] == "exclude_other_employee"
    assert reasons[f"equipment:{laptop['id']}"] == "exclude_other_equipment"
    assert "Jordan" not in package["canonical_json"]
    assert "2025-02-01" not in package["canonical_json"]


def test_two_current_laptop_limits_are_both_excluded(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    current_ids = [
        row["id"]
        for row in connection.execute(
            """
            SELECT id FROM policies
            WHERE role = 'ic' AND item = 'laptop' AND effective_to IS NULL
            """
        )
    ]
    cursor = connection.execute(
        """
        INSERT INTO policies (
            role, item, max_count, refresh_years, effective_from, effective_to
        ) VALUES ('ic', 'laptop', 3, 4, '2020-01-01', NULL)
        """
    )
    current_ids.append(int(cursor.lastrowid))
    request_id = insert_request(
        connection,
        employee_id="E1003",
        item="laptop",
        reason="I need a laptop for my desk.",
        submitted_on="2026-09-30",
    )

    package = build_package(connection, request_id)
    reasons = _reasons(package)

    assert len(current_ids) == 2
    assert reasons[f"policy:{current_ids[0]}"] == "exclude_conflict"
    assert reasons[f"policy:{current_ids[1]}"] == "exclude_conflict"
    assert not any(
        fact["kind"] == "policy" and fact["item"] == "laptop"
        for fact in package["included"]
    )
    assert package["conflict"] is True
