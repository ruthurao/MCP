"""MCP client. Lists the server tools once, then calls the tool the model names."""

from __future__ import annotations

from mcp import Client

from server.mcp import stdio_parameters


class ToolSession:
    def __init__(self, db_path: str, request_id: int) -> None:
        self._client = Client(stdio_parameters(db_path, request_id))
        self.catalog: list[dict] = []

    async def __aenter__(self) -> ToolSession:
        await self._client.__aenter__()
        listed = await self._client.list_tools()
        self.catalog = [_tool_record(tool) for tool in listed.tools]
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.__aexit__(*exc)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        result = await self._client.call_tool(name, arguments)
        if result.is_error or result.structured_content is None:
            return {"ok": False, "error": _error_text(result.content)}
        return result.structured_content

    async def read_resource(self, uri: str) -> str:
        result = await self._client.read_resource(uri)
        parts: list[str] = []
        for block in result.contents:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif getattr(block, "content", None):
                parts.append(str(block.content))
        return "\n".join(parts)

    async def get_prompt(self, name: str, arguments: dict) -> str:
        payload = {key: str(value) for key, value in arguments.items()}
        result = await self._client.get_prompt(name, payload)
        parts: list[str] = []
        for message in result.messages:
            content = message.content
            if isinstance(content, str):
                parts.append(content)
                continue
            text = getattr(content, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts)


def _tool_record(tool: object) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema,
    }


def _error_text(content: object) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        parts.append(text if isinstance(text, str) else str(block))
    return " ".join(parts) or "tool call failed"
