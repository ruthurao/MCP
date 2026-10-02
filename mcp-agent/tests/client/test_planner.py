"""The scratchpad chooses the steps when the model is off."""

from pathlib import Path

from client.intake import open_database, submit
from client.planner import deterministic
from client.reflection import reflect
from client.worker import run
from server.context import build_package
from server.prompts import UNVERIFIED_SHIP_SENTENCE


def test_deterministic_approve_rewrites_the_ship_promise(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")

    finished = run(connection, propose=deterministic)
    stored = connection.execute(
        "SELECT trace, status FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()

    assert finished[0]["status"] == "approved"
    assert "Prompt: investigate_request" in stored["trace"]
    assert "Resource: policy://catalog" in stored["trace"]
    assert UNVERIFIED_SHIP_SENTENCE in stored["trace"]
    assert "Reflection: fail" in stored["trace"]
    assert "Reflection: pass" in stored["trace"]
    assert stored["status"] == "approved"


def test_ship_promise_that_survives_rewrite_escalates(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")
    package = build_package(connection, request_id)

    note, proposal = reflect(
        package,
        {
            "decision": "approve",
            "reason": UNVERIFIED_SHIP_SENTENCE,
            "cited_ids": ["employee:E1003"],
            "content_hash": package["content_hash"],
        },
    )

    assert note.startswith("Reflection: failed. Escalated as draft_unverified.")
    assert proposal["decision"] == "escalate"
    assert proposal["reason_code"] == "draft_unverified"
