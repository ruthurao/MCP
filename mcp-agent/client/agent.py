"""One MCP lookup. The trace records the observation."""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from server.mcp import stdio_parameters


def lookup_employee(db_path: str, request_id: int, employee_id: str) -> str:
    observation = asyncio.run(_lookup(db_path, request_id, employee_id))
    return (
        "Thought: Look up the employee on this request.\n"
        f"Action: get_employee_info {employee_id}\n"
        f"Observation: {json.dumps(observation)}"
    )


async def _lookup(db_path: str, request_id: int, employee_id: str) -> dict:
    async with Client(stdio_parameters(db_path, request_id)) as client:
        result = await client.call_tool(
            "get_employee_info",
            {"employee_id": employee_id},
        )
    if result.is_error or result.structured_content is None:
        raise RuntimeError(result.content)
    return result.structured_content
