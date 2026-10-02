"""Four MCP tools, resources, prompts, and completions on stdio and HTTP."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from mcp import StdioServerParameters
from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import (
    Completion,
    PromptReference,
    ResourceTemplateReference,
    ToolAnnotations,
)
from pydantic import BaseModel, ConfigDict

from server import service
from server.policy import CATALOG, ROLES
from server.prompts import human_review_brief, investigate_request, reflect_on_draft
from server.resources import (
    read_catalog,
    read_employee_dossier,
    read_policy_rules,
    read_review_queue,
)
from store.db import connect

_LOG = logging.getLogger("equipment.desk")

_READ = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    destructive_hint=False,
    open_world_hint=False,
)
_FLAG = ToolAnnotations(
    read_only_hint=False,
    idempotent_hint=True,
    destructive_hint=False,
    open_world_hint=False,
)


class IssuedEquipment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: str
    issued_on: str


class EmployeeInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool
    employee_id: str | None = None
    name: str | None = None
    role: str | None = None
    start_date: str | None = None
    tenure_days: int | None = None
    equipment: list[IssuedEquipment] | None = None


class PolicyLimit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_count: int
    refresh_years: int
    memory_id: str


class PolicyLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool
    role: str | None = None
    limits: dict[str, PolicyLimit] | None = None


class Eligibility(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    reason_code: str
    item: str | None = None
    intent: str | None = None
    evidence: dict


class ReviewFlag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool
    error: str | None = None
    ticket_id: str | None = None
    duplicate: bool | None = None


def build_server(db_path: str, request_id: int) -> MCPServer:
    mcp = MCPServer(
        "equipment-desk",
        instructions=(
            "Investigate one equipment request. Tools decide eligibility. "
            "Ambiguous results escalate through flag_for_human_review. "
            "Use only the employee, equipment, and policy in this request's package."
        ),
    )

    def call(operation):
        connection = connect(db_path)
        try:
            return operation(connection)
        finally:
            connection.close()

    async def timed(ctx: Context, name: str, operation, model: type[BaseModel]):
        started = time.perf_counter()
        try:
            raw = operation()
            result = model.model_validate(raw)
        except Exception as exc:
            message = f"{name} failed: {exc}"
            _LOG.error(message)
            await _client_log(ctx, "error", message)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        message = f"{name} completed in {elapsed_ms:.1f}ms"
        _LOG.info(message)
        await _client_log(ctx, "info", message)
        return result

    @mcp.tool(annotations=_READ)
    async def get_employee_info(employee_id: str, ctx: Context) -> EmployeeInfo:
        """Role, tenure in days, start date, and equipment when this id is the subject."""
        return await timed(
            ctx,
            "get_employee_info",
            lambda: call(
                lambda connection: service.get_employee_info(connection, request_id, employee_id)
            ),
            EmployeeInfo,
        )

    @mcp.tool(annotations=_READ)
    async def get_policy_limits(role: str, ctx: Context) -> PolicyLimits:
        """Max count and refresh years for the included policy rows of this role."""
        return await timed(
            ctx,
            "get_policy_limits",
            lambda: call(
                lambda connection: service.get_policy_limits(connection, request_id, role)
            ),
            PolicyLimits,
        )

    @mcp.tool(annotations=_READ)
    async def check_request_eligibility(
        employee_id: str,
        item: str,
        ctx: Context,
        request_text: str = "",
    ) -> Eligibility:
        """Status, reason code, and evidence from the sentence and the frozen package."""
        return await timed(
            ctx,
            "check_request_eligibility",
            lambda: call(
                lambda connection: service.check_request_eligibility(
                    connection, request_id, employee_id, item, request_text
                )
            ),
            Eligibility,
        )

    @mcp.tool(annotations=_FLAG)
    async def flag_for_human_review(
        employee_id: str,
        request: str,
        reason: str,
        ctx: Context,
    ) -> ReviewFlag:
        """Open one review when the reason is an escalation code. Repeats return the same ticket."""
        return await timed(
            ctx,
            "flag_for_human_review",
            lambda: call(
                lambda connection: service.flag_for_human_review(
                    connection, request_id, employee_id, request, reason
                )
            ),
            ReviewFlag,
        )

    @mcp.resource("policy://rules", mime_type="text/markdown")
    def policy_rules() -> str:
        return read_policy_rules()

    @mcp.resource("policy://catalog", mime_type="text/markdown")
    def policy_catalog() -> str:
        return read_catalog()

    @mcp.resource("employee://{employee_id}", mime_type="text/markdown")
    def employee_dossier(employee_id: str) -> str:
        return call(
            lambda connection: read_employee_dossier(connection, request_id, employee_id)
        )

    @mcp.resource("review://queue", mime_type="text/markdown")
    def review_queue() -> str:
        return call(read_review_queue)

    @mcp.prompt(name="investigate_request")
    def investigate_request_prompt(employee_id: str, request_text: str) -> str:
        return investigate_request(employee_id, request_text)

    @mcp.prompt(name="human_review_brief")
    def human_review_brief_prompt(employee_id: str, request_text: str, reason_code: str) -> str:
        return human_review_brief(employee_id, request_text, reason_code)

    @mcp.prompt(name="reflect_on_draft")
    def reflect_on_draft_prompt(draft: str) -> str:
        return reflect_on_draft(draft)

    @mcp.completion()
    async def complete(ref: PromptReference | ResourceTemplateReference, argument, context):
        """Offer known employee ids, catalog items, and roles."""
        del ref, context
        name = getattr(argument, "name", "") or ""
        partial = getattr(argument, "value", "") or ""
        if name == "employee_id":
            values = _matches(_employee_ids(db_path), partial)
        elif name == "item":
            values = _matches(sorted(CATALOG), partial)
        elif name == "role":
            values = _matches(_roles(db_path), partial)
        else:
            values = []
        return Completion(values=values[:100], total=len(values), has_more=len(values) > 100)

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


def _employee_ids(db_path: str) -> list[str]:
    connection = connect(db_path)
    try:
        rows = connection.execute(
            "SELECT employee_id FROM employees ORDER BY employee_id"
        ).fetchall()
    finally:
        connection.close()
    return [row["employee_id"] for row in rows]


def _roles(db_path: str) -> list[str]:
    connection = connect(db_path)
    try:
        rows = connection.execute("SELECT DISTINCT role FROM policies ORDER BY role").fetchall()
    finally:
        connection.close()
    found = [row["role"] for row in rows]
    return found or list(ROLES)


def _matches(values: list[str], partial: str) -> list[str]:
    needle = partial.lower()
    return [value for value in values if value.lower().startswith(needle)]


async def _client_log(ctx: Context, level: str, message: str) -> None:
    try:
        await getattr(ctx, level)(message)
    except Exception:
        return


if __name__ == "__main__":
    main()
