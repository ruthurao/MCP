"""Scratchpad planner. It does not call the model."""

from __future__ import annotations

import json
import sqlite3

from client.mcp_client import ToolSession
from server.prompts import UNVERIFIED_SHIP_SENTENCE, draft_has_unverified_promise
from server.resources import read_catalog
from store.db import connect
from store.repository import get_request

_DECISION = {"eligible": "approve", "ineligible": "deny", "ambiguous": "escalate"}


def deterministic(db_path: str, row: sqlite3.Row) -> tuple[str, dict]:
    import asyncio

    return asyncio.run(_investigate(db_path, row))


async def _investigate(db_path: str, row: sqlite3.Row) -> tuple[str, dict]:
    lines: list[str] = []
    async with ToolSession(db_path, row["id"]) as session:
        await _note(
            session,
            lines,
            "Load the investigation instructions before classifying the request.",
            "prompt",
            "investigate_request",
            {"employee_id": row["employee_id"], "request_text": row["reason"]},
        )
        catalog = await _note(
            session,
            lines,
            "Read the catalog before guessing an item.",
            "resource",
            "policy://catalog",
            {},
        )
        rules = await _note(
            session,
            lines,
            "Read the policy rules that the draft is allowed to quote.",
            "resource",
            "policy://rules",
            {},
        )
        info = await _note(
            session,
            lines,
            "Look up the employee record.",
            "action",
            "get_employee_info",
            {"employee_id": row["employee_id"]},
        )
        await _note(
            session,
            lines,
            "Read the employee dossier so the draft can quote it.",
            "resource",
            f"employee://{row['employee_id']}",
            {},
        )
        limits: dict = {}
        if info.get("found"):
            limits = await _note(
                session,
                lines,
                "Look up policy limits for the role on the employee record.",
                "action",
                "get_policy_limits",
                {"role": info["role"]},
            )
        item = _guess_item(row["reason"], catalog if isinstance(catalog, str) else read_catalog())
        if not item:
            item = row["item"] if row["item"] in _catalog_items(catalog) else row["item"]
        eligibility = await _note(
            session,
            lines,
            "Check eligibility and trust the tool status.",
            "action",
            "check_request_eligibility",
            {
                "employee_id": row["employee_id"],
                "item": item if isinstance(item, str) else row["item"],
                "request_text": row["reason"],
            },
        )
        status = eligibility.get("status")
        reason_code = eligibility.get("reason_code") or "agent_stuck"
        if status not in _DECISION:
            status = "ambiguous"
            reason_code = "agent_stuck"
        ticket_id = None
        if status == "ambiguous" or not info.get("found"):
            if not info.get("found"):
                reason_code = "unknown_employee"
                status = "ambiguous"
            ticket_id = await _flag(session, lines, row, reason_code)
        decision = _DECISION[status]
        draft = _draft(decision, info, eligibility, limits, rules, reason_code, ticket_id)
        if decision == "approve":
            draft = draft + "\n" + UNVERIFIED_SHIP_SENTENCE
        await _note(
            session,
            lines,
            "Check the draft against the reflection checklist.",
            "prompt",
            "reflect_on_draft",
            {"draft": draft},
        )
        passed, note = _review(draft)
        lines.append(f"Draft:\n{draft}")
        lines.append(f"Reflection: {'pass' if passed else 'fail'}")
        lines.append(f"Note: {note}")
        if not passed:
            revised = "\n".join(
                line for line in draft.splitlines() if not draft_has_unverified_promise(line)
            ).strip()
            passed, note = _review(revised)
            lines.append(f"Revised draft:\n{revised}")
            lines.append(f"Reflection: {'pass' if passed else 'fail'}")
            lines.append(f"Note: {note}")
            draft = revised
        if not passed:
            ticket_id = await _flag(session, lines, row, "draft_unverified")
            decision = "escalate"
            reason_code = "draft_unverified"
            draft = "\n".join(
                [
                    "Decision: Escalate",
                    "Reason code: draft_unverified",
                    f"Review ticket: {ticket_id}.",
                    "The draft was not sent.",
                ]
            )
            lines.append("Final response withheld because reflection failed.")
        proposal = _proposal(db_path, row, decision, draft, info, limits, reason_code, ticket_id)
        lines.append("Proposal: " + json.dumps(proposal))
        return "\n".join(lines), proposal


async def _flag(
    session: ToolSession, lines: list[str], row: sqlite3.Row, reason: str
) -> str | None:
    await _note(
        session,
        lines,
        "Load the human-review brief for this escalation.",
        "prompt",
        "human_review_brief",
        {
            "employee_id": row["employee_id"],
            "request_text": row["reason"],
            "reason_code": reason,
        },
    )
    flag = await _note(
        session,
        lines,
        "Flag the request for human review once.",
        "action",
        "flag_for_human_review",
        {"employee_id": row["employee_id"], "request": row["reason"], "reason": reason},
    )
    await _note(
        session,
        lines,
        "Confirm the review ticket is on the queue.",
        "resource",
        "review://queue",
        {},
    )
    ticket = flag.get("ticket_id") if isinstance(flag, dict) else None
    return ticket if isinstance(ticket, str) else None


async def _note(session, lines, thought, kind, name, payload):
    lines.append(f"Thought: {thought}")
    if kind == "prompt":
        lines.append(f"Prompt: {name}")
        body = await session.get_prompt(name, payload)
    elif kind == "resource":
        lines.append(f"Resource: {name}")
        body = await session.read_resource(name)
    else:
        lines.append(_action_line(name, payload))
        body = await session.call_tool(name, payload)
    shown = body if isinstance(body, str) else json.dumps(body)
    lines.append(f"Observation: {shown}")
    return body


def _action_line(name: str, arguments: dict) -> str:
    values = " ".join(str(value) for value in arguments.values())
    if values:
        return f"Action: {name} {values}"
    return f"Action: {name}"


def _guess_item(request_text: str, catalog_text: str) -> str:
    from server.policy import classify_items

    del catalog_text
    found = classify_items(request_text)
    if len(found) == 1:
        return found[0]
    if found:
        return found[0]
    return ""


def _catalog_items(catalog: object) -> set[str]:
    if not isinstance(catalog, str):
        return set()
    return {
        line.removeprefix("Item: ").strip()
        for line in catalog.splitlines()
        if line.startswith("Item: ")
    }


def _draft(decision, info, eligibility, limits, rules, reason_code, ticket_id) -> str:
    label = {"approve": "Approve", "deny": "Deny", "escalate": "Escalate"}[decision]
    lines = [f"Decision: {label}"]
    if info.get("found"):
        lines.append(
            f"{info['name']} ({info['employee_id']}), role {info['role']}, "
            f"hired {info['start_date']}."
        )
        for unit in info.get("equipment") or []:
            lines.append(f"Equipment {unit['item']} issued on {unit['issued_on']}.")
    else:
        lines.append(f"Employee {eligibility.get('item') or ''} is not on file.")
    item = eligibility.get("item")
    if item:
        lines.append(f"Item: {item}.")
    if reason_code:
        lines.append(f"Reason code: {reason_code}.")
    row = (limits.get("limits") or {}).get(item) if item else None
    if row:
        lines.append(f"Refresh cadence: {row['refresh_years']} years.")
    quote = _quote(rules if isinstance(rules, str) else "", reason_code)
    if quote:
        lines.append(quote)
    if ticket_id:
        lines.append(f"Review ticket: {ticket_id}.")
    return "\n".join(lines)


def _quote(rules: str, reason_code: str) -> str | None:
    prefix = f"{reason_code}:"
    for line in rules.splitlines():
        if line.startswith(prefix):
            return line
    return None


def _review(draft: str) -> tuple[bool, str]:
    if draft_has_unverified_promise(draft):
        return False, "draft promises a ship date, a model, or a cost"
    return True, "draft matches the observations"


def _proposal(db_path, row, decision, draft, info, limits, reason_code, ticket_id) -> dict:
    cited: list[str] = []
    if info.get("found"):
        cited.append(f"employee:{info['employee_id']}")
    item = None
    memory = None
    if limits.get("found"):
        for item_name, row_limit in (limits.get("limits") or {}).items():
            item = item_name
            memory = row_limit.get("memory_id")
            break
    if memory:
        cited.append(memory)
    del item
    proposal = {
        "decision": decision,
        "reason": draft,
        "reason_code": reason_code,
        "cited_ids": cited,
        "content_hash": _content_hash(db_path, row["id"]),
    }
    if ticket_id:
        proposal["ticket_id"] = ticket_id
    return proposal


def _content_hash(db_path: str, request_id: int) -> str:
    connection = connect(db_path)
    try:
        stored = get_request(connection, request_id)
    finally:
        connection.close()
    if stored is None or not stored["context_hash"]:
        raise RuntimeError("package hash is missing")
    return stored["context_hash"]
