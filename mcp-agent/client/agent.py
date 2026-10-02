"""ReAct loop. The worker checks the proposal."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from mcp import Client

from client.decisions import expected_decision
from server.mcp import stdio_parameters
from store.db import connect
from store.repository import get_request


def react(db_path: str, row: sqlite3.Row) -> tuple[str, dict]:
    return asyncio.run(_react(db_path, row))


async def _react(db_path: str, row: sqlite3.Row) -> tuple[str, dict]:
    lines: list[str] = []
    if row["last_error"]:
        lines.append(f"Observation: {row['last_error']}")

    employee_id = row["employee_id"]
    item = row["item"]
    async with Client(stdio_parameters(db_path, row["id"])) as client:
        lines.append("Thought: Look up the employee on this request.")
        lines.append(f"Action: get_employee_info {employee_id}")
        info = await _tool(client, "get_employee_info", {"employee_id": employee_id})
        lines.append(f"Observation: {json.dumps(info)}")

        if info.get("found"):
            role = info["role"]
            lines.append("Thought: Read the policy for this role.")
            lines.append(f"Action: get_policy_limits {role}")
            limits = await _tool(client, "get_policy_limits", {"role": role})
            lines.append(f"Observation: {json.dumps(limits)}")

        lines.append("Thought: Check eligibility against the package.")
        lines.append(f"Action: check_request_eligibility {employee_id} {item}")
        eligibility = await _tool(
            client,
            "check_request_eligibility",
            {"employee_id": employee_id, "item": item},
        )
        lines.append(f"Observation: {json.dumps(eligibility)}")

        decision = expected_decision(eligibility["status"], row["reason"])
        review_id = None
        if decision == "escalate":
            lines.append("Thought: A person should review this request.")
            lines.append(f"Action: flag_for_human_review {employee_id}")
            review = await _tool(
                client,
                "flag_for_human_review",
                {
                    "employee_id": employee_id,
                    "request": row["reason"],
                    "reason": eligibility["detail"],
                },
            )
            lines.append(f"Observation: {json.dumps(review)}")
            if not review.get("ok"):
                raise RuntimeError(review)
            review_id = review["review_id"]

    connection = connect(db_path)
    try:
        stored = get_request(connection, row["id"])
    finally:
        connection.close()
    if stored is None or not stored["context_hash"]:
        raise RuntimeError("package hash is missing")

    cited: list[str] = []
    if info.get("found"):
        cited.append(f"employee:{employee_id}")
    if eligibility.get("rule_id"):
        cited.append(eligibility["rule_id"])
    proposal = {
        "decision": decision,
        "reason": eligibility["detail"],
        "cited_ids": cited,
        "content_hash": stored["context_hash"],
    }
    if review_id is not None:
        proposal["review_id"] = review_id
    lines.append("Proposal: " + json.dumps(proposal))
    return "\n".join(lines), proposal


async def _tool(client: Client, name: str, arguments: dict) -> dict:
    result = await client.call_tool(name, arguments)
    if result.is_error or result.structured_content is None:
        raise RuntimeError(result.content)
    return result.structured_content
