"""A sentence is queued, then one worker marks it running and records the lookup."""

import json
from pathlib import Path

from client.intake import open_database, parse_sentence, submit
from client.worker import run
from store.repository import get_request, list_audit_log


def test_parse_catalog_item_and_free_text() -> None:
    assert parse_sentence("E1003: I need a laptop for my desk.") == (
        "E1003",
        "laptop",
        "I need a laptop for my desk.",
    )
    assert parse_sentence("E1001: I want a bigger second monitor.")[1] == "monitor"
    assert parse_sentence("E1002: My laptop was stolen. I need a replacement.")[1] == "laptop"
    tablet = "E1003: I need a drawing tablet for design work."
    assert parse_sentence(tablet) == (
        "E1003",
        "I need a drawing tablet for design work.",
        "I need a drawing tablet for design work.",
    )


def test_sentence_is_queued_then_one_worker_claims_it(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")

    queued = get_request(connection, request_id)
    assert queued["status"] == "queued"
    assert queued["employee_id"] == "E1003"
    assert queued["item"] == "laptop"
    assert queued["submitted_on"] == "2026-09-30"

    claimed = run(connection)
    again = run(connection)

    assert [row["id"] for row in claimed] == [request_id]
    assert claimed[0]["status"] == "running"
    assert get_request(connection, request_id)["status"] == "running"
    assert again == []


def test_worker_claims_the_oldest_row_first(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    first = submit(connection, "E1003: I need a laptop for my desk.")
    second = submit(connection, "E1001: I want a bigger second monitor.")

    claimed = run(connection)

    assert [row["id"] for row in claimed] == [first, second]
    assert [row["status"] for row in claimed] == ["running", "running"]


def test_worker_records_the_real_employee_observation(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")

    claimed = run(connection)
    stored = get_request(connection, request_id)
    trace = stored["trace"]
    observation = json.loads(trace.split("Observation: ", 1)[1])

    assert claimed[0]["status"] == "running"
    assert trace.startswith(
        "Thought: Look up the employee on this request.\n"
        "Action: get_employee_info E1003\n"
        "Observation: "
    )
    assert observation == {
        "found": True,
        "employee_id": "E1003",
        "role": "ic",
        "start_date": "2024-08-01",
        "equipment": [],
    }
    assert [row["action"] for row in list_audit_log(connection, request_id)] == [
        "get_employee_info"
    ]
