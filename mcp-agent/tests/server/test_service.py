"""Eligibility and an empty escalation reason."""

from pathlib import Path

from server.reviews import read_entries, log_path
from server.service import (
    check_request_eligibility,
    flag_for_human_review,
    get_employee_info,
    get_policy_limits,
)
from store.db import connect, create_schema
from store.repository import insert_request, list_audit_log
from store.seed import seed


def _request(tmp_path: Path, employee_id: str, item: str, reason: str) -> tuple:
    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id=employee_id,
        item=item,
        reason=reason,
        submitted_on="2026-09-30",
    )
    return connection, request_id


def test_first_laptop_is_eligible(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1003", "laptop", "I need a laptop for my desk."
    )

    info = get_employee_info(connection, request_id, "E1003")
    limits = get_policy_limits(connection, request_id, "ic")
    eligibility = check_request_eligibility(connection, request_id, "E1003", "laptop")

    assert info["found"] is True
    assert info["role"] == "ic"
    assert info["equipment"] == []
    assert limits["found"] is True
    assert limits["limits"]["laptop"]["max_count"] == 1
    assert limits["limits"]["laptop"]["refresh_years"] == 4
    assert eligibility["status"] == "eligible"
    assert eligibility["reason_code"] == "within_policy"
    actions = [row["action"] for row in list_audit_log(connection, request_id)]
    assert actions == [
        "get_employee_info",
        "get_policy_limits",
        "check_request_eligibility",
    ]


def test_recent_monitor_is_ineligible(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1001", "monitor", "I want a bigger second monitor."
    )

    eligibility = check_request_eligibility(connection, request_id, "E1001", "monitor")
    hidden = get_employee_info(connection, request_id, "E1002")

    assert eligibility["status"] == "ineligible"
    assert eligibility["reason_code"] == "at_cap"
    assert eligibility["evidence"]["due_on"] == "2027-11-01"
    assert hidden["found"] is False


def test_unknown_item_and_missing_employee_are_unknown(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1003", "drawing tablet", "I need a drawing tablet for design work."
    )
    missing_id = insert_request(
        connection,
        employee_id="E9999",
        item="laptop",
        reason="I need a laptop.",
        submitted_on="2026-09-30",
    )

    tablet = check_request_eligibility(
        connection, request_id, "E1003", "drawing tablet"
    )
    missing = check_request_eligibility(connection, missing_id, "E9999", "laptop")
    unknown_role = get_policy_limits(connection, request_id, "intern")

    assert tablet["status"] == "ambiguous"
    assert tablet["reason_code"] == "invalid_input"
    assert missing["status"] == "ambiguous"
    assert missing["reason_code"] == "unknown_employee"
    assert unknown_role["found"] is False


def test_conflicting_rules_are_unknown(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1003", "laptop", "I need a laptop for my desk."
    )
    connection.execute(
        """
        INSERT INTO policies (
            role, item, max_count, refresh_years, effective_from, effective_to
        ) VALUES ('ic', 'laptop', 3, 4, '2020-01-01', NULL)
        """
    )

    eligibility = check_request_eligibility(connection, request_id, "E1003", "laptop")

    assert eligibility["status"] == "ambiguous"
    assert eligibility["reason_code"] == "data_error"
    assert eligibility["evidence"]["notes"] == "Two current rules conflict for this item."


def test_seeded_edge_cases(tmp_path: Path) -> None:
    connection, boundary_id = _request(
        tmp_path, "E1004", "monitor", "Please replace my monitor."
    )
    leap_id = insert_request(
        connection,
        employee_id="E1005",
        item="monitor",
        reason="Please replace my monitor.",
        submitted_on="2026-09-30",
    )
    under_cap_id = insert_request(
        connection,
        employee_id="E1006",
        item="monitor",
        reason="I need another monitor.",
        submitted_on="2026-09-30",
    )
    priya_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="I want a bigger second monitor.",
        submitted_on="2026-09-30",
    )

    boundary = check_request_eligibility(connection, boundary_id, "E1004", "monitor")
    assert boundary["status"] == "eligible"
    assert boundary["reason_code"] == "within_policy"
    assert boundary["evidence"]["due_on"] == "2026-09-30"
    leap_result = check_request_eligibility(connection, leap_id, "E1005", "monitor")
    assert leap_result["status"] == "ambiguous"
    assert leap_result["reason_code"] == "borderline_cadence"
    assert leap_result["evidence"]["due_on"] == "2027-02-28"
    under_cap = check_request_eligibility(connection, under_cap_id, "E1006", "monitor")
    assert under_cap["reason_code"] == "within_policy"
    assert under_cap["evidence"]["count_on_file"] == 1
    priya_result = check_request_eligibility(connection, priya_id, "E1001", "monitor")
    assert priya_result["status"] == "ineligible"
    assert priya_result["reason_code"] == "at_cap"
    assert priya_result["evidence"]["due_on"] == "2027-11-01"

    mina_laptop = insert_request(
        connection,
        employee_id="E1007",
        item="laptop",
        reason="Please replace my laptop.",
        submitted_on="2026-09-30",
    )
    mina_keyboard = insert_request(
        connection,
        employee_id="E1007",
        item="keyboard",
        reason="Please replace my keyboard.",
        submitted_on="2026-09-30",
    )
    owen_laptop = insert_request(
        connection,
        employee_id="E1008",
        item="laptop",
        reason="Please replace my laptop.",
        submitted_on="2026-09-30",
    )
    owen_monitor = insert_request(
        connection,
        employee_id="E1008",
        item="monitor",
        reason="I need a monitor.",
        submitted_on="2026-09-30",
    )
    lila_headset = insert_request(
        connection,
        employee_id="E1009",
        item="headset",
        reason="Please replace my headset.",
        submitted_on="2026-09-30",
    )
    lila_dock = insert_request(
        connection,
        employee_id="E1009",
        item="docking_station",
        reason="Please replace my dock.",
        submitted_on="2026-09-30",
    )

    mina_laptop_result = check_request_eligibility(connection, mina_laptop, "E1007", "laptop")
    assert mina_laptop_result["reason_code"] == "within_policy"
    assert mina_laptop_result["evidence"]["due_on"] == "2026-09-30"
    mina_keyboard_result = check_request_eligibility(
        connection, mina_keyboard, "E1007", "keyboard"
    )
    assert mina_keyboard_result["reason_code"] == "too_soon"
    assert mina_keyboard_result["evidence"]["due_on"] == "2028-01-15"
    owen_laptop_result = check_request_eligibility(connection, owen_laptop, "E1008", "laptop")
    assert owen_laptop_result["reason_code"] == "within_policy"
    assert owen_laptop_result["evidence"]["due_on"] == "2026-01-15"
    owen_monitor_result = check_request_eligibility(connection, owen_monitor, "E1008", "monitor")
    assert owen_monitor_result["reason_code"] == "within_policy"
    assert owen_monitor_result["evidence"]["count_on_file"] == 0
    lila_headset_result = check_request_eligibility(
        connection, lila_headset, "E1009", "headset"
    )
    assert lila_headset_result["reason_code"] == "too_soon"
    assert lila_headset_result["evidence"]["due_on"] == "2028-03-01"
    lila_dock_result = check_request_eligibility(
        connection, lila_dock, "E1009", "docking_station"
    )
    assert lila_dock_result["reason_code"] == "within_policy"
    assert lila_dock_result["evidence"]["due_on"] == "2026-09-30"


def test_empty_escalation_reason_writes_no_review(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1002", "laptop", "My laptop was stolen. I need a replacement."
    )

    rejected = flag_for_human_review(
        connection, request_id, "E1002", "stolen laptop", "  "
    )

    assert rejected["ok"] is False
    assert rejected["error"] == "reason is required"
    assert read_entries(log_path(connection))[0] == []

    skipped = flag_for_human_review(
        connection, request_id, "E1002", "stolen laptop", "within_policy"
    )
    assert skipped["ok"] is False
    assert skipped["ticket_id"] is None
    assert read_entries(log_path(connection))[0] == []

    accepted = flag_for_human_review(
        connection, request_id, "E1002", "stolen laptop", "exception_claimed"
    )
    again = flag_for_human_review(
        connection, request_id, "E1002", "stolen laptop", "exception_claimed"
    )
    entries, _corrupt = read_entries(log_path(connection))
    assert accepted["ok"] is True
    assert accepted["ticket_id"].startswith("RVW-")
    assert again["duplicate"] is True
    assert again["ticket_id"] == accepted["ticket_id"]
    assert len(entries) == 1
    assert entries[0]["reason"] == "exception_claimed"
