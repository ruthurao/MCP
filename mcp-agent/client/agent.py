"""ReAct loop. Each turn the model reads the scratchpad and picks the next step."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable

from client.mcp_client import ToolSession
from store.db import connect
from store.repository import get_request

_MAX_TURNS = 8
_MODEL = "qwen3:8b"
# Warm qwen3:8b replies in about 6–7s. The cap leaves room for that plus a cold load.
_TURN_TIMEOUT = 30
Model = Callable[[list[dict], str, dict], str]


def react(
    db_path: str,
    row: sqlite3.Row,
    model: Model | None = None,
) -> tuple[str, dict]:
    return asyncio.run(_react(db_path, row, model or llm_turn))


async def _react(db_path: str, row: sqlite3.Row, model: Model) -> tuple[str, dict]:
    lines = _opening_scratchpad(row)
    content_hash = _content_hash(db_path, row["id"])
    request = {
        "employee_id": row["employee_id"],
        "item": row["item"],
        "reason": row["reason"],
        "submitted_on": row["submitted_on"],
    }
    async with ToolSession(db_path, row["id"]) as session:
        catalog = session.catalog
        for _ in range(_MAX_TURNS):
            turn = _parse(model(catalog, _model_view(lines), request))
            if turn is None:
                lines.append(
                    "Observation: Reply was not a tool call or a proposal. "
                    "Return one JSON object."
                )
                continue
            lines.append(f"Thought: {turn['thought']}")
            proposal = turn.get("proposal")
            if proposal is not None:
                finished = dict(proposal)
                finished["content_hash"] = content_hash
                lines.append("Proposal: " + json.dumps(finished))
                return "\n".join(lines), finished
            name = turn["action"]
            arguments = turn["arguments"]
            lines.append(_action_line(name, arguments))
            try:
                observation = await session.call_tool(name, arguments)
            except Exception as exc:
                observation = {"ok": False, "error": str(exc)}
            lines.append(f"Observation: {json.dumps(observation)}")
    unfinished = {
        "decision": None,
        "reason": "",
        "cited_ids": [],
        "content_hash": content_hash,
    }
    lines.append("Proposal: " + json.dumps(unfinished))
    return "\n".join(lines), unfinished


def llm_turn(catalog: list[dict], scratchpad: str, request: dict) -> str:
    model_name = os.environ.get("EQUIPMENT_MODEL", _MODEL)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _instructions(catalog)},
            {"role": "user", "content": _turn_input(request, scratchpad)},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {"temperature": 0},
    }
    http_request = urllib.request.Request(
        f"{_ollama_host()}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=_TURN_TIMEOUT) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"model call failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {_ollama_host()}. "
            f"Start it with `ollama serve`. The model is {model_name}."
        ) from exc
    return body["message"]["content"]


def _ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").rstrip("/")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host


def _instructions(catalog: list[dict]) -> str:
    tools = json.dumps(catalog, indent=2)
    return (
        "You are the IT equipment desk agent. The tool catalog below was loaded "
        "once from the MCP server. Choose the next step from that catalog and "
        "from the scratchpad. Reply with one JSON object and no other text.\n\n"
        "A tool step:\n"
        '{"thought": "...", "action": "tool_name", "arguments": {}}\n\n'
        "The final answer, with no tool call:\n"
        '{"thought": "...", "proposal": {"decision": "approve|deny|escalate", '
        '"reason": "...", "cited_ids": ["..."], "ticket_id": "RVW-...", '
        '"reason_code": "..."}}\n\n'
        "Rules: trust check_request_eligibility. eligible approves. ineligible denies. "
        "ambiguous escalates. Pass request_text. Escalate only after "
        "flag_for_human_review with that tool's reason_code, and copy ticket_id "
        "onto the proposal. Do not promise a ship date. "
        "Cite employee:{employee_id} when the lookup finds them, and memory_id "
        "values that appear in observations. The reason may state only facts "
        "that are already on the scratchpad.\n\n"
        f"Tools:\n{tools}"
    )


def _turn_input(request: dict, scratchpad: str) -> str:
    shown = scratchpad if scratchpad else "(empty)"
    return (
        f"employee_id: {request['employee_id']}\n"
        f"item: {request['item']}\n"
        f"reason: {request['reason']}\n"
        f"submitted_on: {request['submitted_on']}\n\n"
        f"Scratchpad:\n{shown}"
    )


def _parse(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    thought = body.get("thought")
    if not isinstance(thought, str) or not thought.strip():
        return None
    has_action = "action" in body
    has_proposal = "proposal" in body
    if has_action == has_proposal:
        return None
    if has_proposal:
        proposal = body["proposal"]
        if not isinstance(proposal, dict):
            return None
        return {"thought": thought.strip(), "proposal": proposal}
    name = body["action"]
    arguments = body.get("arguments", {})
    if not isinstance(name, str) or not name.strip() or not isinstance(arguments, dict):
        return None
    return {"thought": thought.strip(), "action": name.strip(), "arguments": arguments}


def _model_view(lines: list[str]) -> str:
    """Short observations for the model. The trace keeps the full text."""
    viewed: list[str] = []
    for line in lines:
        if line.startswith("Observation: {") or line.startswith("Observation: ["):
            raw = line.removeprefix("Observation: ")
            viewed.append("Observation: " + _summarize_observation(raw))
        else:
            viewed.append(line)
    return "\n".join(viewed)


def _summarize_observation(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict):
        return raw
    if "reason_code" in data:
        evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        summary = {
            "status": data.get("status"),
            "reason_code": data.get("reason_code"),
            "item": data.get("item"),
            "evidence": {"notes": evidence.get("notes"), "due_on": evidence.get("due_on")},
        }
    elif "limits" in data:
        summary = {key: data.get(key) for key in ("found", "role", "limits")}
    elif "ticket_id" in data or "duplicate" in data:
        summary = {key: data.get(key) for key in ("ok", "ticket_id", "duplicate", "error")}
    elif "tenure_days" in data or "equipment" in data:
        summary = {key: data.get(key) for key in ("found", "employee_id", "name", "role")}
    else:
        summary = data
    return json.dumps(summary)


def _opening_scratchpad(row: sqlite3.Row) -> list[str]:
    lines: list[str] = []
    if row["trace"]:
        lines.extend(row["trace"].splitlines())
    if row["last_error"]:
        lines.append(f"Observation: {row['last_error']}")
    return lines


def _action_line(name: str, arguments: dict) -> str:
    values = " ".join(str(value) for value in arguments.values())
    if values:
        return f"Action: {name} {values}"
    return f"Action: {name}"


def _content_hash(db_path: str, request_id: int) -> str:
    connection = connect(db_path)
    try:
        stored = get_request(connection, request_id)
    finally:
        connection.close()
    if stored is None or not stored["context_hash"]:
        raise RuntimeError("package hash is missing")
    return stored["context_hash"]
