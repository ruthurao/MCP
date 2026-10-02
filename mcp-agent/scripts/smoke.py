"""One-tool stdio connection proof."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
script_dir = ROOT / "scripts"
sys.path = [
    entry
    for entry in sys.path
    if not entry or Path(entry).resolve() != script_dir
]
sys.path.insert(0, str(ROOT))

from mcp import Client

from server.mcp import stdio_parameters
from store.db import connect, create_schema
from store.repository import insert_request
from store.seed import seed


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "equipment.db"
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

        async with Client(stdio_parameters(str(db_path), request_id)) as client:
            listed = await client.list_tools()
            result = await client.call_tool(
                "get_employee_info",
                {"employee_id": "E1001"},
            )

    names = [tool.name for tool in listed.tools]
    print("tools:", ", ".join(names))
    if result.is_error:
        raise SystemExit(result.content)
    print(json.dumps(result.structured_content, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
