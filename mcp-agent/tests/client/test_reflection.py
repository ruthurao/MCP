"""Draft versus the hashed package."""

from pathlib import Path

from client.intake import open_database, submit
from client.reflection import reflect
from client.worker import run
from server.context import build_package
from store.repository import get_request


def test_reflection_confirms_a_draft_that_stays_inside_the_package(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")

    finished = run(connection)
    stored = get_request(connection, request_id)

    assert finished[0]["status"] == "approved"
    assert "Reflection: confirmed. The draft uses only included facts." in stored["trace"]


def test_reflection_rewrites_a_draft_that_names_someone_outside_the_package(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1001: I want a bigger second monitor.")
    package = build_package(connection, request_id)

    note, proposal = reflect(
        package,
        {
            "decision": "deny",
            "reason": (
                "Newest monitor is inside the 3-year window. "
                "Next eligible 2027-11-01. Jordan Lee can spare a monitor."
            ),
            "cited_ids": ["employee:E1001", "policy:2"],
            "content_hash": package["content_hash"],
        },
    )

    assert note.startswith("Reflection: rewritten.")
    assert "Jordan" not in proposal["reason"]
    assert "2027-11-01" in proposal["reason"]
