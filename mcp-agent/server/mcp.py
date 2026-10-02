"""Four MCP tools on stdio and HTTP."""

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


class PolicyLimit(TypedDict):
    item: str
    max_count: int
    refresh_years: int
    memory_id: str


class PolicyLimits(TypedDict, total=False):
    found: bool
    role: str
    limits: list[PolicyLimit]


class Eligibility(TypedDict, total=False):
    status: str
    rule_id: str | None
    detail: str
    next_eligible_on: str


class ReviewFlag(TypedDict, total=False):
    ok: bool
    error: str
    review_id: int


def build_server(db_path: str, request_id: int) -> MCPServer:
    mcp = MCPServer(
        "equipment-desk",
        instructions=(
            "Use only the employee, equipment, and policy in this request's package. "
            "Anyone else returns found false."
        ),
    )

    def call(operation):
        connection = connect(db_path)
        try:
            return operation(connection)
        finally:
            connection.close()

    @mcp.tool()
    def get_employee_info(employee_id: str) -> EmployeeInfo:
        """Role, start date, and equipment when this id is the request subject."""
        return call(
            lambda connection: service.get_employee_info(
                connection, request_id, employee_id
            )
        )

    @mcp.tool()
    def get_policy_limits(role: str) -> PolicyLimits:
        """Max count and refresh years for the included policy rows of this role."""
        return call(
            lambda connection: service.get_policy_limits(connection, request_id, role)
        )

    @mcp.tool()
    def check_request_eligibility(employee_id: str, item: str) -> Eligibility:
        """Eligible, ineligible, or unknown from the frozen package."""
        return call(
            lambda connection: service.check_request_eligibility(
                connection, request_id, employee_id, item
            )
        )

    @mcp.tool()
    def flag_for_human_review(employee_id: str, request: str, reason: str) -> ReviewFlag:
        """Open a review. An empty reason is rejected."""
        return call(
            lambda connection: service.flag_for_human_review(
                connection, request_id, employee_id, request, reason
            )
        )

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
    server = build_server(db_path, int(request_raw))
    transport = os.environ.get("EQUIPMENT_TRANSPORT", "stdio")
    if transport == "stdio":
        server.run(transport="stdio")
        return
    if transport == "streamable-http":
        server.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=int(os.environ.get("EQUIPMENT_HTTP_PORT", "8000")),
        )
        return
    raise SystemExit(f"Unknown EQUIPMENT_TRANSPORT: {transport}")


if __name__ == "__main__":
    main()
