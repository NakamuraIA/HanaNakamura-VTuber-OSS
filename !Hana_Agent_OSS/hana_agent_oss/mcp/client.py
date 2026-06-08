from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from hana_agent_oss.mcp.contracts import McpCallResult, McpServerConfig, McpToolInfo


class McpSdkUnavailable(RuntimeError):
    pass


class McpEnvMissing(RuntimeError):
    pass


ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _dump_model(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


def _content_to_dict(item: Any) -> dict[str, Any]:
    data = _dump_model(item)
    if data:
        return data
    return {"type": type(item).__name__, "text": str(item)}


class McpStdioClient:
    @staticmethod
    def _resolved_env(config_env: dict[str, str]) -> dict[str, str]:
        """Build the subprocess env while resolving ${VAR} references from the loaded process env."""
        resolved = {str(key): str(value) for key, value in os.environ.items()}
        for key, raw_value in (config_env or {}).items():
            value = str(raw_value)
            missing: list[str] = []

            def replace(match: re.Match[str]) -> str:
                name = match.group(1)
                env_value = os.environ.get(name)
                if env_value is None:
                    missing.append(name)
                    return ""
                return env_value

            next_value = ENV_REF_PATTERN.sub(replace, value)
            if missing:
                raise McpEnvMissing(f"mcp_env_missing:{missing[0]}")
            resolved[str(key)] = next_value
        return resolved

    async def list_tools(self, config: McpServerConfig) -> list[McpToolInfo]:
        async def work() -> list[McpToolInfo]:
            async with self._session(config) as session:
                await session.initialize()
                result = await session.list_tools()
                return [self._tool_info(config.id, tool) for tool in result.tools]

        return await asyncio.wait_for(work(), timeout=config.timeout)

    async def call_tool(self, config: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> McpCallResult:
        async def work() -> McpCallResult:
            async with self._session(config) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                return self._call_result(result)

        return await asyncio.wait_for(work(), timeout=config.timeout)

    def _session(self, config: McpServerConfig):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ModuleNotFoundError as exc:
            raise McpSdkUnavailable("mcp_sdk_missing") from exc

        kwargs: dict[str, Any] = {"command": config.command, "args": config.args, "env": self._resolved_env(config.env)}
        if config.cwd:
            kwargs["cwd"] = config.cwd
        try:
            server_params = StdioServerParameters(**kwargs)
        except TypeError:
            kwargs.pop("cwd", None)
            server_params = StdioServerParameters(**kwargs)

        class SessionContext:
            async def __aenter__(self):
                self._transport = stdio_client(server_params)
                read, write = await self._transport.__aenter__()
                self._session = ClientSession(read, write)
                return await self._session.__aenter__()

            async def __aexit__(self, exc_type, exc, tb):
                try:
                    await self._session.__aexit__(exc_type, exc, tb)
                finally:
                    await self._transport.__aexit__(exc_type, exc, tb)

        return SessionContext()

    def _tool_info(self, server_id: str, tool: Any) -> McpToolInfo:
        data = _dump_model(tool)
        return McpToolInfo(
            server_id=server_id,
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            input_schema=data.get("inputSchema") or data.get("input_schema") or {},
            output_schema=data.get("outputSchema") or data.get("output_schema") or {},
            annotations=data.get("annotations") or {},
        )

    def _call_result(self, result: Any) -> McpCallResult:
        raw = _dump_model(result)
        content = [_content_to_dict(item) for item in getattr(result, "content", raw.get("content", [])) or []]
        structured = (
            getattr(result, "structuredContent", None)
            or getattr(result, "structured_content", None)
            or raw.get("structuredContent")
            or raw.get("structured_content")
            or {}
        )
        is_error = bool(getattr(result, "isError", None) or getattr(result, "is_error", None) or raw.get("isError") or raw.get("is_error"))
        text_error = self._extract_error(content) if is_error else None
        return McpCallResult(
            ok=not is_error,
            content=content,
            structured_content=structured if isinstance(structured, dict) else {"value": structured},
            is_error=is_error,
            raw=raw,
            error=text_error,
        )

    @staticmethod
    def _extract_error(content: list[dict[str, Any]]) -> str:
        for item in content:
            text = item.get("text")
            if text:
                return str(text)
        return "mcp_tool_error"


def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import threading

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - cross-thread propagation.
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
