"""One tool over stdio, before the other three exist."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import Client

from server.mcp import stdio_parameters
from store.db import connect, create_schema
from store.repository import insert_request, list_audit_log
from store.seed import seed


def test_stdio_returns_the_request_subject(tmp_path: Path) -> None:
    db_path = tmp_path / "equipment.db"
    connection = connect(db_path)
    create_schema(connection)
    seed(connection)
    request_id = insert_request(
        connection,
        employee_id="E1001",
        item="monitor",
        reason="Smoke proof.",
        submitted_on="2026-09-30",
    )
    connection.close()

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
        return listed, priya, jordan

    listed, priya, jordan = asyncio.run(call())

    assert [tool.name for tool in listed.tools] == ["get_employee_info"]
    assert priya.is_error is False
    assert priya.structured_content == {
        "found": True,
        "employee_id": "E1001",
        "role": "ic",
        "start_date": "2021-03-01",
        "equipment": [
            {"item": "laptop", "issued_on": "2021-04-01"},
            {"item": "monitor", "issued_on": "2024-11-01"},
        ],
    }
    assert jordan.structured_content == {"found": False}

    audit = connect(db_path)
    actions = [row["action"] for row in list_audit_log(audit, request_id)]
    assert actions == ["get_employee_info", "get_employee_info"]
