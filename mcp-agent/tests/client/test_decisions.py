"""Approve, deny, escalate, and one retry after a bad reply."""

from pathlib import Path

from client.intake import open_database, submit
from client.worker import run
from tests.client.scripted_model import scripted_model
from server.context import build_package
from server.reviews import log_path, read_entries
from store.repository import get_request, list_audit_log


def _bad_proposal(db_path: str, row) -> tuple[str, dict]:
    return (
        "Thought: Skip the package.\nAction: none\nObservation: none",
        {
            "decision": "approve",
            "reason": "not from the tools",
            "cited_ids": ["employee:missing"],
            "content_hash": "wrong",
        },
    )


def test_stolen_laptop_and_unknown_item_escalate(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    stolen = submit(connection, "E1002: My laptop was stolen. I need a replacement.")
    tablet = submit(connection, "E1003: I need a drawing tablet for design work.")

    finished = run(connection, model=scripted_model)

    by_id = {row["id"]: row for row in finished}
    assert by_id[stolen]["status"] == "escalated"
    assert by_id[stolen]["decision"] == "escalate"
    assert by_id[tablet]["status"] == "escalated"
    assert by_id[tablet]["decision"] == "escalate"
    entries, _corrupt = read_entries(log_path(connection))
    reasons = sorted(entry["reason"] for entry in entries)
    assert reasons == ["borderline_cadence", "invalid_input"]


def test_bad_reply_is_queued_once_then_escalated(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")
    digest = build_package(connection, request_id)["content_hash"]

    finished = run(connection, propose=_bad_proposal)
    stored = get_request(connection, request_id)

    assert [row["id"] for row in finished] == [request_id]
    assert stored["status"] == "escalated"
    assert stored["attempt"] == 1
    assert stored["context_hash"] == digest
    assert build_package(connection, request_id)["content_hash"] == digest
    assert stored["last_error"] == (
        "content hash does not match the package; "
        "content hash does not match the package"
    )
    entries, _corrupt = read_entries(log_path(connection))
    assert len(entries) == 1
    assert entries[0]["reason"] == "agent_stuck"
    assert entries[0]["ticket_id"].startswith("RVW-")
    details = [row["detail"] for row in list_audit_log(connection, request_id)]
    assert details.count("content hash does not match the package") == 1
    assert "reply failed validation twice" in details
