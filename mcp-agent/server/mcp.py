"""One MCP tool on stdio: get_employee_info."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TypedDict

from mcp import StdioServerParameters
from mcp.server import MCPServer

from server import service
from store.db import connect


class IssuedEquipment(TypedDict):
    item: str
    issued_on: str


class EmployeeInfo(TypedDict, total=False):
    found: bool
    employee_id: str
    role: str
    start_date: str
    equipment: list[IssuedEquipment]


def build_server(db_path: str, request_id: int) -> MCPServer:
    mcp = MCPServer(
        "equipment-desk",
        instructions=(
            "Look up the employee on this request. "
            "Anyone else returns found false."
        ),
    )

    @mcp.tool()
    def get_employee_info(employee_id: str) -> EmployeeInfo:
        """Role, start date, and equipment when this id is the request subject."""
        connection = connect(db_path)
        try:
            return service.get_employee_info(connection, request_id, employee_id)
        finally:
            connection.close()

    return mcp


def stdio_parameters(db_path: str, request_id: int) -> StdioServerParameters:
    root = str(Path(__file__).resolve().parents[1])
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.mcp"],
        env={
            "PYTHONPATH": root,
            "EQUIPMENT_DB": db_path,
            "EQUIPMENT_REQUEST_ID": str(request_id),
        },
    )


def main() -> None:
    db_path = os.environ.get("EQUIPMENT_DB")
    request_raw = os.environ.get("EQUIPMENT_REQUEST_ID")
    if not db_path or not request_raw:
        raise SystemExit("EQUIPMENT_DB and EQUIPMENT_REQUEST_ID are required")
    build_server(db_path, int(request_raw)).run(transport="stdio")


if __name__ == "__main__":
    main()
