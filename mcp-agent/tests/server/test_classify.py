"""Sentence classification on top of the frozen package."""

from datetime import date
from pathlib import Path

from server.policy import check_eligibility
from server.service import check_request_eligibility
from store.db import connect, create_schema
from store.repository import insert_request
from store.seed import seed


def _employee() -> dict:
    return {
        "employee_id": "E1001",
        "name": "Priya Shah",
        "role": "ic",
        "start_date": "2021-03-01",
        "equipment": [{"item": "laptop", "issued_on": "2021-04-01"}],
    }


def _policy() -> dict:
    return {
        "item": "laptop",
        "max_count": 1,
        "refresh_years": 4,
        "memory_id": "policy:1",
    }


def _check(text: str, item: str = "laptop", **overrides) -> dict:
    employee = overrides.pop("employee", _employee())
    return check_eligibility(
        overrides.pop("employee_id", "E1001"),
        item,
        text,
        as_of=overrides.pop("as_of", date(2026, 9, 30)),
        employee=employee,
        policy=overrides.pop("policy", _policy()),
        conflict=overrides.pop("conflict", False),
    )


def test_aliases_negation_role_claim_and_id_shape() -> None:
    headphones = _check(
        "I need headphones.",
        item="headset",
        policy={**_policy(), "item": "headset"},
        employee={**_employee(), "equipment": []},
    )
    assert headphones["item"] == "headset"
    assert headphones["reason_code"] == "within_policy"

    mismatch = _check("I need a monitor.")
    assert mismatch["reason_code"] == "item_mismatch"

    screen = _check("I need a new screen.", item="monitor", policy={**_policy(), "item": "monitor"})
    assert screen["item"] == "monitor"
    assert screen["reason_code"] == "within_policy"

    dock = _check(
        "I need a dock.",
        item="docking_station",
        policy={**_policy(), "item": "docking_station"},
        employee={**_employee(), "equipment": []},
    )
    assert dock["item"] == "docking_station"
    assert dock["reason_code"] == "within_policy"

    negated = _check("The laptop is not stolen. Please replace it.")
    assert negated["reason_code"] == "within_policy"
    assert negated["evidence"]["exception_words"] == []

    claim = _check("I am a manager and I need to replace my laptop.")
    assert claim["reason_code"] == "role_claim_mismatch"

    invalid = _check("I need a laptop.", employee_id="E12")
    assert invalid["reason_code"] == "invalid_input"

    future = _check(
        "Please replace my laptop.",
        employee={**_employee(), "start_date": "2027-01-01"},
    )
    assert future["reason_code"] == "data_error"


def test_borderline_stands_when_the_laptop_is_cracked() -> None:
    # Due 2026-12-01 is 62 days after 2026-09-30, inside the 180-day window.
    result = _check(
        "My laptop is cracked. Please replace it.",
        employee={
            **_employee(),
            "equipment": [{"item": "laptop", "issued_on": "2022-12-01"}],
        },
    )
    assert result["status"] == "ambiguous"
    assert result["reason_code"] == "borderline_cadence"
    assert "cracked" in result["evidence"]["exception_words"]


def test_additional_at_the_cap_ignores_a_due_unit() -> None:
    result = _check("I need a second laptop.")
    assert result["status"] == "ineligible"
    assert result["reason_code"] == "at_cap"
    assert result["evidence"]["issued_on"] == "2021-04-01"


def test_two_items_and_executive_role(tmp_path: Path) -> None:
    both = _check("I need a headset or a dock.", item="headset")
    assert both["reason_code"] == "multiple_items"

    connection = connect(tmp_path / "equipment.db")
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id="E1010",
        item="laptop",
        reason="Please replace my laptop.",
        submitted_on="2026-09-30",
    )
    result = check_request_eligibility(connection, request_id, "E1010", "laptop")
    assert result["evidence"]["role"] == "executive"
    assert result["reason_code"] == "too_soon"
    info_days = (
        connection.execute("SELECT start_date FROM employees WHERE employee_id = 'E1010'")
        .fetchone()["start_date"]
    )
    assert info_days == "2016-01-04"
