"""Claim a request, check the proposal, retry once, then escalate."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from client.agent import react
from client.decisions import expected_decision
from client.reflection import reflect
from server.context import build_package
from server.reviews import ticket_on_file
from server.service import check_request_eligibility, flag_for_human_review
from store.repository import (
    claim_next,
    get_request,
    insert_audit,
    update_request,
)

_STATUS = {"approve": "approved", "deny": "denied", "escalate": "escalated"}
_ACTOR = "worker"


def run(
    connection: sqlite3.Connection,
    propose: Callable[[str, sqlite3.Row], tuple[str, dict]] | None = None,
    model: Callable[..., str] | None = None,
) -> list[sqlite3.Row]:
    if propose is None:
        def propose(db_path: str, row: sqlite3.Row) -> tuple[str, dict]:
            return react(db_path, row, model=model)
    finished: list[sqlite3.Row] = []
    while True:
        row = claim_next(connection)
        if row is None:
            return finished
        package = build_package(connection, row["id"])
        trace, proposal = propose(_database_path(connection), row)
        note, proposal = reflect(package, proposal)
        trace = f"{trace}\n{note}"
        error = _validate(connection, row, proposal, package)
        if error is None:
            _finish(connection, row, trace, proposal)
        elif row["attempt"] == 0:
            _requeue(connection, row, trace, error)
        else:
            _escalate_twice(connection, row, trace, error)
        stored = get_request(connection, row["id"])
        if stored is None:
            raise RuntimeError(f"request {row['id']} disappeared after claim")
        if stored["status"] != "queued":
            finished.append(stored)


def _validate(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    proposal: dict,
    package: dict,
) -> str | None:
    decision = proposal.get("decision")
    reason = proposal.get("reason")
    cited_ids = proposal.get("cited_ids")
    if (
        decision not in _STATUS
        or not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(cited_ids, list)
    ):
        return "decision, reason, and cited_ids are required"
    if proposal.get("content_hash") != package["content_hash"]:
        return "content hash does not match the package"
    included = {fact["memory_id"] for fact in package["included"]}
    for cited in cited_ids:
        if cited not in included:
            return f"cited id {cited} is not in the package"
    eligibility = check_request_eligibility(
        connection, row["id"], row["employee_id"], row["item"]
    )
    reason_code = proposal.get("reason_code")
    if not isinstance(reason_code, str):
        reason_code = ""
    if decision != expected_decision(eligibility["status"], reason_code):
        return "decision does not match eligibility"
    if decision == "escalate":
        ticket_id = proposal.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_on_file(connection, ticket_id):
            return "escalate requires a review ticket"
    return None


def _finish(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    trace: str,
    proposal: dict,
) -> None:
    decision = proposal["decision"]
    update_request(
        connection,
        row["id"],
        status=_STATUS[decision],
        trace=trace,
        attempt=row["attempt"],
        last_error=None,
        decision=decision,
    )
    insert_audit(
        connection,
        request_id=row["id"],
        actor=_ACTOR,
        action="decide",
        detail=decision,
    )


def _requeue(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    trace: str,
    error: str,
) -> None:
    update_request(
        connection,
        row["id"],
        status="queued",
        trace=trace,
        attempt=1,
        last_error=error,
        decision=None,
    )
    insert_audit(
        connection,
        request_id=row["id"],
        actor=_ACTOR,
        action="validation_failed",
        detail=error,
    )


def _escalate_twice(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    trace: str,
    error: str,
) -> None:
    combined = error if not row["last_error"] else f"{row['last_error']}; {error}"
    flag_for_human_review(
        connection,
        row["id"],
        row["employee_id"],
        row["reason"],
        "agent_stuck",
    )
    update_request(
        connection,
        row["id"],
        status="escalated",
        trace=trace,
        attempt=row["attempt"],
        last_error=combined,
        decision="escalate",
    )
    insert_audit(
        connection,
        request_id=row["id"],
        actor=_ACTOR,
        action="validation_failed",
        detail="reply failed validation twice",
    )


def _database_path(connection: sqlite3.Connection) -> str:
    path = connection.execute("PRAGMA database_list").fetchone()["file"]
    if not path:
        raise RuntimeError("worker needs a database file")
    return path
