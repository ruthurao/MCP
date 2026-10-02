"""The model chooses each step. The MCP client only lists tools and calls them."""

import json
import urllib.request
from pathlib import Path

from client.agent import _TURN_TIMEOUT, _parse, llm_turn
from client.intake import open_database, submit
from client.worker import run
from store.repository import get_request


def test_model_thought_is_copied_onto_the_scratchpad_and_its_tool_is_called(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1003: I need a laptop for my desk.")
    catalogs: list[list[dict]] = []
    pads: list[str] = []

    def model(catalog: list[dict], scratchpad: str, request: dict) -> str:
        catalogs.append(catalog)
        pads.append(scratchpad)
        if "Action: get_policy_limits" not in scratchpad:
            return json.dumps(
                {
                    "thought": "Policy first, because the scratchpad is empty.",
                    "action": "get_policy_limits",
                    "arguments": {"role": "ic"},
                }
            )
        limits = json.loads(
            next(
                line.removeprefix("Observation: ")
                for line in scratchpad.splitlines()
                if line.startswith("Observation: ")
            )
        )
        laptop = limits["limits"]["laptop"]
        return json.dumps(
            {
                "thought": "The policy row is enough to approve the first laptop.",
                "proposal": {
                    "decision": "approve",
                    "reason": "Count is 0 of 1.",
                    "cited_ids": [f"employee:{request['employee_id']}", laptop["memory_id"]],
                },
            }
        )

    finished = run(connection, model=model)
    stored = get_request(connection, request_id)

    assert finished[0]["status"] == "approved"
    assert catalogs[0] is catalogs[1]
    assert [tool["name"] for tool in catalogs[0]] == [
        "get_employee_info",
        "get_policy_limits",
        "check_request_eligibility",
        "flag_for_human_review",
    ]
    assert pads[0] == ""
    assert pads[1].startswith("Thought: Policy first, because the scratchpad is empty.\n")
    assert "Action: get_policy_limits ic\n" in pads[1]
    assert stored["trace"].startswith(
        "Thought: Policy first, because the scratchpad is empty.\n"
        "Action: get_policy_limits ic\n"
        "Observation: "
    )


def test_a_rejected_proposal_returns_as_the_next_observation(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "equipment.db")
    request_id = submit(connection, "E1001: I want a bigger second monitor.")
    pads: list[str] = []

    def model(catalog: list[dict], scratchpad: str, request: dict) -> str:
        pads.append(scratchpad)
        if "decision does not match eligibility" not in scratchpad:
            return json.dumps(
                {
                    "thought": "Approve it before checking the window.",
                    "proposal": {
                        "decision": "approve",
                        "reason": "A second monitor would help.",
                        "cited_ids": [f"employee:{request['employee_id']}"],
                    },
                }
            )
        return json.dumps(
            {
                "thought": "The last observation says that approval does not match.",
                "proposal": {
                    "decision": "deny",
                    "reason": (
                        "Newest monitor is inside the 3-year window. "
                        "Next eligible 2027-11-01."
                    ),
                    "cited_ids": [f"employee:{request['employee_id']}"],
                },
            }
        )

    finished = run(connection, model=model)
    stored = get_request(connection, request_id)

    assert finished[0]["status"] == "denied"
    assert pads[0] == ""
    assert "Observation: decision does not match eligibility" in pads[1]
    assert stored["attempt"] == 1


def test_llm_turn_posts_the_catalog_and_the_scratchpad(monkeypatch) -> None:
    captured: dict = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"message": {"role": "assistant", "content": "{\"thought\":\"next\"}"}}
            ).encode()

    def fake_urlopen(request: urllib.request.Request, timeout: int = 0) -> _Response:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.delenv("EQUIPMENT_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    catalog = [
        {"name": "get_employee_info", "description": "Look up a person.", "input_schema": {}}
    ]
    reply = llm_turn(
        catalog,
        "Thought: start",
        {
            "employee_id": "E1003",
            "item": "laptop",
            "reason": "desk",
            "submitted_on": "2026-09-30",
        },
    )

    assert reply == '{"thought":"next"}'
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == _TURN_TIMEOUT
    assert _TURN_TIMEOUT > 7
    assert captured["body"]["model"] == "qwen3:8b"
    assert captured["body"]["think"] is False
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"]["temperature"] == 0
    system = captured["body"]["messages"][0]["content"]
    user = captured["body"]["messages"][1]["content"]
    assert "get_employee_info" in system
    assert "Thought: start" in user
    assert "E1003" in user


def test_parse_accepts_a_fenced_tool_call_and_rejects_both_shapes() -> None:
    parsed = _parse(
        '```json\n{"thought": "Look up the person.", "action": "get_employee_info", '
        '"arguments": {"employee_id": "E1003"}}\n```'
    )
    assert parsed == {
        "thought": "Look up the person.",
        "action": "get_employee_info",
        "arguments": {"employee_id": "E1003"},
    }
    assert _parse('{"thought": "both", "action": "get_employee_info", "proposal": {}}') is None
