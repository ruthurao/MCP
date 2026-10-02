"""Four tools on stdio, and the same eligibility result over HTTP."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.types import PromptReference

from server import mcp as mcp_module
from server.mcp import _employee_ids, _matches, _roles, stdio_parameters
from store.db import connect, create_schema
from store.repository import insert_request, list_audit_log
from store.seed import seed

_TOOLS = [
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "flag_for_human_review",
]


def _database(tmp_path: Path) -> tuple[Path, int]:
    db_path = tmp_path / "equipment.db"
    connection = connect(db_path)
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="Please replace my monitor.",
        submitted_on="2026-09-30",
    )
    connection.close()
    return db_path, request_id


def test_stdio_returns_the_request_subject(tmp_path: Path) -> None:
    db_path, request_id = _database(tmp_path)

    async def call():
        async with Client(stdio_parameters(str(db_path), request_id)) as client:
            listed = await client.list_tools()
            priya = await client.call_tool(
                "get_employee_info",
                {"employee_id": "E1001"},
            )
            jordan = await client.call_tool(
                "get_employee_info",
                {"employee_id": "E1002"},
            )
            limits = await client.call_tool("get_policy_limits", {"role": "ic"})
            rejected = await client.call_tool(
                "flag_for_human_review",
                {"employee_id": "E1001", "request": "second monitor", "reason": "  "},
            )
        return listed, priya, jordan, limits, rejected

    listed, priya, jordan, limits, rejected = asyncio.run(call())

    assert [tool.name for tool in listed.tools] == _TOOLS
    assert priya.is_error is False
    priya_body = priya.structured_content
    assert priya_body["found"] is True
    assert priya_body["employee_id"] == "E1001"
    assert priya_body["name"] == "Priya Shah"
    assert priya_body["role"] == "ic"
    assert priya_body["start_date"] == "2021-03-01"
    assert priya_body["tenure_days"] == (date(2026, 9, 30) - date(2021, 3, 1)).days
    assert priya_body["equipment"] == [
        {"item": "laptop", "issued_on": "2021-04-01"},
        {"item": "monitor", "issued_on": "2024-11-01"},
    ]
    assert jordan.structured_content["found"] is False
    assert limits.structured_content["found"] is True
    monitor = limits.structured_content["limits"]["monitor"]
    assert monitor["max_count"] == 1
    assert monitor["refresh_years"] == 3
    assert monitor["memory_id"].startswith("policy:")
    assert rejected.structured_content["ok"] is False
    assert rejected.structured_content["error"] == "reason is required"
    annotations = {tool.name: tool.annotations for tool in listed.tools}
    assert annotations["get_employee_info"].read_only_hint is True
    assert annotations["get_policy_limits"].read_only_hint is True
    assert annotations["check_request_eligibility"].read_only_hint is True
    assert annotations["flag_for_human_review"].read_only_hint is False
    assert annotations["flag_for_human_review"].idempotent_hint is True

    audit = connect(db_path)
    actions = [row["action"] for row in list_audit_log(audit, request_id)]
    assert actions == [
        "get_employee_info",
        "get_employee_info",
        "get_policy_limits",
        "flag_for_human_review",
    ]


def test_stdio_and_http_return_the_same_eligibility(tmp_path: Path) -> None:
    db_path, request_id = _database(tmp_path)
    arguments = {"employee_id": "E1001", "item": "monitor"}

    async def over_stdio():
        async with Client(stdio_parameters(str(db_path), request_id)) as client:
            result = await client.call_tool("check_request_eligibility", arguments)
        return result.structured_content

    stdio_result = asyncio.run(over_stdio())
    http_result = asyncio.run(_over_http(db_path, request_id, arguments))

    assert stdio_result == http_result
    assert stdio_result["status"] == "ineligible"
    assert stdio_result["reason_code"] == "too_soon"
    assert stdio_result["evidence"]["due_on"] == "2027-11-01"


def test_completions_offer_ids_items_and_roles(tmp_path: Path) -> None:
    db_path, request_id = _database(tmp_path)

    async def complete():
        async with Client(stdio_parameters(str(db_path), request_id)) as client:
            employees = await client.complete(
                PromptReference(name="investigate_request"),
                {"name": "employee_id", "value": "E1001"},
            )
            items = await client.complete(
                PromptReference(name="investigate_request"),
                {"name": "item", "value": "head"},
            )
            roles = await client.complete(
                PromptReference(name="investigate_request"),
                {"name": "role", "value": "exec"},
            )
        return employees, items, roles

    employees, items, roles = asyncio.run(complete())
    assert "E1001" in employees.completion.values
    assert employees.completion.values == ["E1001"]
    assert items.completion.values == ["headset"]
    assert roles.completion.values == ["executive"]


def test_registered_tools_run_in_process_and_report_results(tmp_path: Path) -> None:
    db_path, request_id = _database(tmp_path)
    server = mcp_module.build_server(str(db_path), request_id)
    messages: list[tuple[str, str]] = []

    class Context:
        async def info(self, message: str) -> None:
            messages.append(("info", message))

        async def error(self, message: str) -> None:
            messages.append(("error", message))

    async def call_tools():
        tools = server._tool_manager
        employee = await tools.get_tool("get_employee_info").fn(
            employee_id="E1001", ctx=Context()
        )
        limits = await tools.get_tool("get_policy_limits").fn(role="ic", ctx=Context())
        eligibility = await tools.get_tool("check_request_eligibility").fn(
            employee_id="E1001",
            item="monitor",
            ctx=Context(),
            request_text="Please replace my monitor.",
        )
        review = await tools.get_tool("flag_for_human_review").fn(
            employee_id="E1001",
            request="Please replace my monitor.",
            reason="exception_claimed",
            ctx=Context(),
        )
        return employee, limits, eligibility, review

    employee, limits, eligibility, review = asyncio.run(call_tools())

    assert employee.found is True
    assert limits.found is True
    assert eligibility.status == "ineligible"
    assert review.ok is True
    assert review.ticket_id.startswith("RVW-")
    assert len([entry for entry in messages if entry[0] == "info"]) == 4


def test_registered_tool_logs_and_reraises_operation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, request_id = _database(tmp_path)
    server = mcp_module.build_server(str(db_path), request_id)
    errors: list[str] = []

    class Context:
        async def error(self, message: str) -> None:
            errors.append(message)

    def fail(*_args, **_kwargs):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(mcp_module.service, "get_employee_info", fail)
    tool = server._tool_manager.get_tool("get_employee_info")

    with pytest.raises(RuntimeError, match="service unavailable"):
        asyncio.run(tool.fn(employee_id="E1001", ctx=Context()))

    assert errors == ["get_employee_info failed: service unavailable"]


def test_registered_resources_and_prompts_run_in_process(tmp_path: Path) -> None:
    db_path, request_id = _database(tmp_path)
    server = mcp_module.build_server(str(db_path), request_id)
    resources = server._resource_manager
    prompts = server._prompt_manager

    rules = resources._resources["policy://rules"].fn()
    catalog = resources._resources["policy://catalog"].fn()
    dossier = resources._templates["employee://{employee_id}"].fn("E1001")
    queue = resources._resources["review://queue"].fn()
    investigate = prompts._prompts["investigate_request"].fn(
        employee_id="E1001", request_text="Please replace my monitor."
    )
    review = prompts._prompts["human_review_brief"].fn(
        employee_id="E1001",
        request_text="Please replace my monitor.",
        reason_code="exception_claimed",
    )
    reflection = prompts._prompts["reflect_on_draft"].fn(draft="Decision: Deny")

    assert "within_policy" in rules
    assert "monitor" in catalog
    assert "Priya Shah" in dossier
    assert isinstance(queue, str)
    assert "E1001" in investigate
    assert "exception_claimed" in review
    assert "Decision: Deny" in reflection


def test_completion_helpers_and_main_transport_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, _request_id = _database(tmp_path)
    assert _employee_ids(str(db_path))[0] == "E1001"
    assert _roles(str(db_path)) == ["executive", "ic", "manager"]
    assert _matches(["Laptop", "monitor"], "la") == ["Laptop"]

    connection = connect(tmp_path / "empty.db")
    create_schema(connection)
    connection.close()
    assert _roles(str(tmp_path / "empty.db")) == ["ic", "manager", "executive"]

    calls: list[dict] = []
    fake_server = SimpleNamespace(run=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(mcp_module, "build_server", lambda *_args: fake_server)
    monkeypatch.setenv("EQUIPMENT_DB", str(db_path))
    monkeypatch.setenv("EQUIPMENT_REQUEST_ID", "1")

    monkeypatch.setenv("EQUIPMENT_TRANSPORT", "stdio")
    mcp_module.main()
    monkeypatch.setenv("EQUIPMENT_TRANSPORT", "streamable-http")
    monkeypatch.setenv("EQUIPMENT_HTTP_PORT", "8123")
    mcp_module.main()

    assert calls == [
        {"transport": "stdio"},
        {"transport": "streamable-http", "host": "127.0.0.1", "port": 8123},
    ]

    monkeypatch.setenv("EQUIPMENT_TRANSPORT", "invalid")
    with pytest.raises(SystemExit, match="Unknown EQUIPMENT_TRANSPORT: invalid"):
        mcp_module.main()

    monkeypatch.delenv("EQUIPMENT_DB")
    with pytest.raises(SystemExit, match="EQUIPMENT_DB and EQUIPMENT_REQUEST_ID are required"):
        mcp_module.main()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _over_http(db_path: Path, request_id: int, arguments: dict) -> dict:
    port = _free_port()
    root = str(Path(__file__).resolve().parents[2])
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": root,
            "EQUIPMENT_DB": str(db_path),
            "EQUIPMENT_REQUEST_ID": str(request_id),
            "EQUIPMENT_TRANSPORT": "streamable-http",
            "EQUIPMENT_HTTP_PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "server.mcp"],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_until_listening(port, process)
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            result = await client.call_tool("check_request_eligibility", arguments)
        if result.is_error:
            raise AssertionError(result.content)
        return result.structured_content
    finally:
        process.terminate()
        process.wait(timeout=5)


def _wait_until_listening(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            error = process.stderr.read().decode() if process.stderr else ""
            raise RuntimeError(error)
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("HTTP server did not listen")
