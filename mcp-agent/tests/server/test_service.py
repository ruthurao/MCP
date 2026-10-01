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
