"""Eligibility and an empty escalation reason."""

from pathlib import Path

from server.service import (
    check_request_eligibility,
    flag_for_human_review,
    get_employee_info,
    get_policy_limits,
)
from store.db import connect, create_schema
from store.repository import insert_request, list_audit_log, list_reviews
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
    assert limits["limits"][0]["max_count"] == 1
    assert limits["limits"][0]["refresh_years"] == 4
    assert eligibility["status"] == "eligible"
    assert eligibility["detail"] == "Count is 0 of 1."
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
    assert eligibility["next_eligible_on"] == "2027-11-01"
    assert "2027-11-01" in eligibility["detail"]
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

    assert tablet["status"] == "unknown"
    assert tablet["detail"] == "Item is not in the catalog."
    assert missing["status"] == "unknown"
    assert missing["detail"] == "Employee is not in the package."
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

    assert eligibility["status"] == "unknown"
    assert eligibility["detail"] == "Two current rules conflict for this item."
    assert eligibility["rule_id"] is None


def test_seeded_edge_cases(tmp_path: Path) -> None:
    connection, boundary_id = _request(tmp_path, "E1004", "monitor", "Refresh day.")
    leap_id = insert_request(
        connection,
        employee_id="E1005",
        item="monitor",
        reason="Leap day monitor.",
        submitted_on="2026-09-30",
    )
    under_cap_id = insert_request(
        connection,
        employee_id="E1006",
        item="monitor",
        reason="One monitor, cap is two.",
        submitted_on="2026-09-30",
    )
    priya_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="Stale higher cap is in the seed.",
        submitted_on="2026-09-30",
    )

    assert check_request_eligibility(connection, boundary_id, "E1004", "monitor")["detail"] == (
        "Refresh window is open. Next eligible was 2026-09-30."
    )
    leap_result = check_request_eligibility(connection, leap_id, "E1005", "monitor")
    assert leap_result["status"] == "ineligible"
    assert leap_result["next_eligible_on"] == "2027-02-28"
    assert check_request_eligibility(connection, under_cap_id, "E1006", "monitor")["detail"] == (
        "Count is 1 of 2."
    )
    priya_result = check_request_eligibility(connection, priya_id, "E1001", "monitor")
    assert priya_result["status"] == "ineligible"
    assert priya_result["next_eligible_on"] == "2027-11-01"

    mina_laptop = insert_request(
        connection,
        employee_id="E1007",
        item="laptop",
        reason="Laptop refresh day.",
        submitted_on="2026-09-30",
    )
    mina_keyboard = insert_request(
        connection,
        employee_id="E1007",
        item="keyboard",
        reason="Recent keyboard.",
        submitted_on="2026-09-30",
    )
    owen_laptop = insert_request(
        connection,
        employee_id="E1008",
        item="laptop",
        reason="Manager laptop refresh.",
        submitted_on="2026-09-30",
    )
    owen_monitor = insert_request(
        connection,
        employee_id="E1008",
        item="monitor",
        reason="No monitors yet.",
        submitted_on="2026-09-30",
    )
    lila_headset = insert_request(
        connection,
        employee_id="E1009",
        item="headset",
        reason="Recent headset.",
        submitted_on="2026-09-30",
    )
    lila_dock = insert_request(
        connection,
        employee_id="E1009",
        item="dock",
        reason="Dock refresh day.",
        submitted_on="2026-09-30",
    )

    assert check_request_eligibility(connection, mina_laptop, "E1007", "laptop")["detail"] == (
        "Refresh window is open. Next eligible was 2026-09-30."
    )
    mina_keyboard_result = check_request_eligibility(
        connection, mina_keyboard, "E1007", "keyboard"
    )
    assert mina_keyboard_result["next_eligible_on"] == "2028-01-15"
    assert check_request_eligibility(connection, owen_laptop, "E1008", "laptop")["detail"] == (
        "Refresh window is open. Next eligible was 2026-01-15."
    )
    assert check_request_eligibility(connection, owen_monitor, "E1008", "monitor")["detail"] == (
        "Count is 0 of 2."
    )
    lila_headset_result = check_request_eligibility(
        connection, lila_headset, "E1009", "headset"
    )
    assert lila_headset_result["next_eligible_on"] == "2028-03-01"
    assert check_request_eligibility(connection, lila_dock, "E1009", "dock")["detail"] == (
        "Refresh window is open. Next eligible was 2026-09-30."
    )


def test_empty_escalation_reason_writes_no_review(tmp_path: Path) -> None:
    connection, request_id = _request(
        tmp_path, "E1002", "laptop", "My laptop was stolen. I need a replacement."
    )

    rejected = flag_for_human_review(
        connection, request_id, "E1002", "stolen laptop", "  "
    )

    assert rejected == {"ok": False, "error": "reason is required"}
    assert list_reviews(connection) == []

    accepted = flag_for_human_review(
        connection,
        request_id,
        "E1002",
        "stolen laptop",
        "theft inside the refresh window",
    )
    reviews = list_reviews(connection)
    assert len(reviews) == 1
    assert reviews[0]["id"] == accepted["review_id"]
    assert reviews[0]["package_hash"]
    assert reviews[0]["reason"] == "theft inside the refresh window"
