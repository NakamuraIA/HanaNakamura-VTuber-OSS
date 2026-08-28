from __future__ import annotations

import asyncio
import os
import re
import threading
from concurrent.futures import Future as ThreadFuture
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Coroutine, TypeVar

from backend.mcp.contracts import McpCallResult, McpServerConfig, McpToolInfo


class McpSdkUnavailable(RuntimeError):
    pass


class McpEnvMissing(RuntimeError):
    pass


class McpSessionClosed(RuntimeError):
    pass


ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_T = TypeVar("_T")


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


@dataclass
class _McpCommand:
    kind: str
    result: asyncio.Future[Any]
    timeout: float
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class _McpWorker:
    config: McpServerConfig
    signature: tuple[Any, ...]
    queue: asyncio.Queue[_McpCommand]
    ready: asyncio.Future[None]
    task: asyncio.Task[None] | None = None


class McpStdioClient:
    """Cliente MCP com uma sessão persistente por servidor.

    As sessões vivem num único loop assíncrono em segundo plano. Isso permite
    reutilizá-las tanto nas rotas FastAPI quanto nos runners síncronos dos
    providers sem mover um transporte MCP entre loops ou threads.
    """

    def __init__(self) -> None:
        self._runtime_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._desired_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._workers: dict[str, _McpWorker] = {}
        self._server_locks: dict[str, asyncio.Lock] = {}
        self._statuses: dict[str, dict[str, str]] = {}
        self._desired_signatures: dict[str, tuple[Any, ...] | None] = {}
        self._closing = False

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

    @staticmethod
    def _signature(config: McpServerConfig) -> tuple[Any, ...]:
        """Only values that change the subprocess require a new session."""
        return (
            config.command,
            tuple(config.args),
            tuple(sorted((str(key), str(value)) for key, value in config.env.items())),
            config.cwd,
        )

    def runtime_status(self, server_id: str) -> dict[str, str]:
        with self._status_lock:
            return dict(self._statuses.get(server_id, {}))

    def mark_disabled(self, server_id: str) -> None:
        self._set_disabled(server_id)
        self._set_status(server_id, "disabled")

    def warmup_background(self, config: McpServerConfig) -> None:
        self._set_desired(config)
        if self.runtime_status(config.id).get("status") != "ready":
            self._set_status(config.id, "warming")
        self._consume_future(self._submit(self._ensure_worker(config)))

    def restart_background(self, config: McpServerConfig) -> None:
        self._set_desired(config)
        self._set_status(config.id, "warming")
        self._consume_future(self._submit(self._restart_worker(config)))

    def close_server_background(self, server_id: str) -> None:
        self._set_disabled(server_id)
        self._set_status(server_id, "disabled")
        loop = self._running_loop()
        if loop is not None:
            self._consume_future(asyncio.run_coroutine_threadsafe(self._stop_worker(server_id), loop))

    async def warmup(self, config: McpServerConfig) -> None:
        self._set_desired(config)
        await self._dispatch(self._ensure_worker(config))

    async def list_tools(self, config: McpServerConfig) -> list[McpToolInfo]:
        self._register_desired(config)
        result = await self._dispatch(self._list_tools(config))
        return [self._tool_info(config.id, tool) for tool in result.tools]

    async def call_tool(
        self,
        config: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult:
        self._register_desired(config)
        result = await self._dispatch(self._call_tool(config, tool_name, arguments))
        return self._call_result(result)

    async def close_server(self, server_id: str) -> None:
        self._set_disabled(server_id)
        loop = self._running_loop()
        if loop is None:
            self._set_status(server_id, "disabled")
            return
        await self._dispatch(self._stop_worker(server_id))
        self._set_status(server_id, "disabled")

    async def shutdown(self) -> None:
        with self._desired_lock:
            self._closing = True
            for server_id in self._desired_signatures:
                self._desired_signatures[server_id] = None
        loop = self._running_loop()
        if loop is None:
            return
        thread = self._thread
        try:
            await self._dispatch(self._stop_all_workers())
        finally:
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None and thread is not threading.current_thread():
                await asyncio.to_thread(thread.join, 5)
            with self._runtime_lock:
                if self._loop is loop:
                    self._loop = None
                    self._thread = None

    async def _list_tools(self, config: McpServerConfig) -> Any:
        try:
            return await self._request_once(config, "list_tools")
        except (McpEnvMissing, McpSdkUnavailable, McpSessionClosed, TimeoutError, asyncio.TimeoutError):
            raise
        except Exception:
            await self._recover(config)
            return await self._request_once(config, "list_tools")

    async def _call_tool(self, config: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> Any:
        try:
            return await self._request_once(
                config,
                "call_tool",
                tool_name=tool_name,
                arguments=arguments,
            )
        except (McpEnvMissing, McpSdkUnavailable, McpSessionClosed, asyncio.CancelledError):
            raise
        except BaseException:
            # A chamada pode ter chegado ao servidor. Reconecta para a próxima,
            # mas não repete esta automaticamente e evita efeitos duplicados.
            try:
                await self._recover(config)
            except BaseException:
                pass
            raise

    async def _request_once(
        self,
        config: McpServerConfig,
        kind: str,
        *,
        tool_name: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        self._assert_desired(config)
        worker = await self._ensure_worker(config)
        self._assert_desired(config)
        result = asyncio.get_running_loop().create_future()
        await worker.queue.put(
            _McpCommand(
                kind=kind,
                result=result,
                timeout=config.timeout,
                tool_name=tool_name,
                arguments=arguments or {},
            )
        )
        return await asyncio.shield(result)

    async def _recover(self, config: McpServerConfig) -> None:
        signature = self._signature(config)
        lock = self._server_locks.setdefault(config.id, asyncio.Lock())
        async with lock:
            worker = self._workers.get(config.id)
            if worker and worker.signature == signature:
                await self._discard_worker(worker)
        self._assert_desired(config)
        await self._ensure_worker(config)

    async def _restart_worker(self, config: McpServerConfig) -> None:
        await self._stop_worker(config.id)
        if config.enabled:
            await self._ensure_worker(config)

    async def _ensure_worker(self, config: McpServerConfig) -> _McpWorker:
        for attempt in range(2):
            self._assert_desired(config)
            worker = await self._get_or_create_worker(config)
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker.ready),
                    timeout=max(float(config.timeout), 0.1),
                )
                self._assert_desired(config)
                return worker
            except asyncio.CancelledError:
                # Cancelamento do caller ou desligamento explícito nunca abre
                # outra sessão por conta própria.
                raise
            except McpSessionClosed:
                await self._discard_if_current(worker)
                raise
            except (McpEnvMissing, McpSdkUnavailable, TimeoutError, asyncio.TimeoutError) as exc:
                await self._discard_if_current(worker)
                if self._is_desired(config):
                    self._set_status(config.id, "error", self._error_text(exc))
                raise
            except BaseException:
                await self._discard_if_current(worker)
                if attempt:
                    raise
                await asyncio.sleep(0.4)
        raise RuntimeError("mcp_worker_start_failed")

    async def _get_or_create_worker(self, config: McpServerConfig) -> _McpWorker:
        lock = self._server_locks.setdefault(config.id, asyncio.Lock())
        async with lock:
            self._assert_desired(config)
            current = self._workers.get(config.id)
            signature = self._signature(config)
            if current and current.signature == signature and current.task and not current.task.done():
                return current
            if current:
                await self._discard_worker(current)
            self._assert_desired(config)
            worker = self._new_worker(config, signature)
            self._workers[config.id] = worker
            self._set_status(config.id, "warming")
            return worker

    async def _discard_if_current(self, worker: _McpWorker) -> None:
        lock = self._server_locks.setdefault(worker.config.id, asyncio.Lock())
        async with lock:
            if self._workers.get(worker.config.id) is worker:
                await self._discard_worker(worker)

    def _new_worker(self, config: McpServerConfig, signature: tuple[Any, ...]) -> _McpWorker:
        loop = asyncio.get_running_loop()
        worker = _McpWorker(
            config=config,
            signature=signature,
            queue=asyncio.Queue(),
            ready=loop.create_future(),
        )
        worker.task = asyncio.create_task(self._worker_main(worker), name=f"mcp:{config.id}")
        worker.task.add_done_callback(self._consume_task)
        return worker

    async def _worker_main(self, worker: _McpWorker) -> None:
        server_id = worker.config.id
        try:
            async with self._session(worker.config) as session:
                await asyncio.wait_for(session.initialize(), timeout=worker.config.timeout)
                if not worker.ready.done():
                    worker.ready.set_result(None)
                if self._is_desired(worker.config):
                    self._set_status(server_id, "ready")
                while True:
                    command = await worker.queue.get()
                    try:
                        self._assert_desired(worker.config)
                        if command.kind == "list_tools":
                            value = await asyncio.wait_for(session.list_tools(), timeout=command.timeout)
                        else:
                            value = await asyncio.wait_for(
                                session.call_tool(command.tool_name, command.arguments),
                                timeout=command.timeout,
                            )
                        if not command.result.done():
                            command.result.set_result(value)
                    except asyncio.CancelledError:
                        if not command.result.done():
                            command.result.set_exception(McpSessionClosed("mcp_session_closed"))
                        raise
                    except BaseException as exc:
                        if not command.result.done():
                            command.result.set_exception(exc)
                        raise
        except asyncio.CancelledError:
            if not worker.ready.done():
                worker.ready.cancel()
            raise
        except BaseException as exc:
            if not worker.ready.done():
                worker.ready.set_exception(exc)
            if self._is_desired(worker.config):
                self._set_status(server_id, "error", self._error_text(exc))
        finally:
            while not worker.queue.empty():
                command = worker.queue.get_nowait()
                if not command.result.done():
                    command.result.set_exception(McpSessionClosed("mcp_session_closed"))
            current = self._workers.get(server_id)
            if current is worker:
                self._workers.pop(server_id, None)

    async def _stop_worker(self, server_id: str) -> None:
        lock = self._server_locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            worker = self._workers.get(server_id)
            if worker:
                await self._discard_worker(worker)

    async def _discard_worker(self, worker: _McpWorker) -> None:
        if self._workers.get(worker.config.id) is worker:
            self._workers.pop(worker.config.id, None)
        if worker.task and not worker.task.done():
            worker.task.cancel()
        if worker.task:
            await asyncio.gather(worker.task, return_exceptions=True)

    async def _stop_all_workers(self) -> None:
        for server_id in list(self._workers):
            await self._stop_worker(server_id)

    def _set_status(self, server_id: str, status: str, error: str = "") -> None:
        payload = {"status": status}
        if error:
            payload["error"] = error
        with self._status_lock:
            self._statuses[server_id] = payload

    def _set_desired(self, config: McpServerConfig) -> None:
        with self._desired_lock:
            if self._closing:
                raise McpSessionClosed("mcp_runtime_closed")
            self._desired_signatures[config.id] = self._signature(config)

    def _register_desired(self, config: McpServerConfig) -> None:
        with self._desired_lock:
            if self._closing:
                raise McpSessionClosed("mcp_runtime_closed")
            if config.id not in self._desired_signatures:
                self._desired_signatures[config.id] = self._signature(config) if config.enabled else None

    def _set_disabled(self, server_id: str) -> None:
        with self._desired_lock:
            self._desired_signatures[server_id] = None

    def _is_desired(self, config: McpServerConfig) -> bool:
        signature = self._signature(config)
        with self._desired_lock:
            return not self._closing and self._desired_signatures.get(config.id) == signature

    def _assert_desired(self, config: McpServerConfig) -> None:
        if not self._is_desired(config):
            raise McpSessionClosed("mcp_server_stopped_or_reconfigured")

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        text = str(exc).strip()
        return f"{type(exc).__name__}: {text}" if text else type(exc).__name__

    def _running_loop(self) -> asyncio.AbstractEventLoop | None:
        with self._runtime_lock:
            loop = self._loop
        return loop if loop is not None and loop.is_running() else None

    def _ensure_runtime(self) -> asyncio.AbstractEventLoop:
        with self._runtime_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            ready = threading.Event()

            def runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()

            thread = threading.Thread(target=runner, name="hana-mcp-runtime", daemon=True)
            self._thread = thread
            thread.start()
        if not ready.wait(timeout=5):
            raise RuntimeError("mcp_runtime_start_timeout")
        if self._loop is None:
            raise RuntimeError("mcp_runtime_start_failed")
        return self._loop

    def _submit(self, coro: Coroutine[Any, Any, _T]) -> ThreadFuture[_T]:
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_runtime())

    async def _dispatch(self, coro: Coroutine[Any, Any, _T]) -> _T:
        loop = self._ensure_runtime()
        if asyncio.get_running_loop() is loop:
            return await coro
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))

    @staticmethod
    def _consume_future(future: ThreadFuture[Any]) -> None:
        def consume(done: ThreadFuture[Any]) -> None:
            try:
                done.result()
            except BaseException:
                pass

        future.add_done_callback(consume)

    @staticmethod
    def _consume_task(task: asyncio.Task[Any]) -> None:
        try:
            task.exception()
        except BaseException:
            pass

    def _session(self, config: McpServerConfig):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ModuleNotFoundError as exc:
            raise McpSdkUnavailable("mcp_sdk_missing") from exc

        kwargs: dict[str, Any] = {
            "command": config.command,
            "args": config.args,
            "env": self._resolved_env(config.env),
        }
        if config.cwd:
            kwargs["cwd"] = config.cwd
        try:
            server_params = StdioServerParameters(**kwargs)
        except TypeError:
            kwargs.pop("cwd", None)
            server_params = StdioServerParameters(**kwargs)

        @asynccontextmanager
        async def session_context():
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    yield session

        return session_context()

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
        is_error = bool(
            getattr(result, "isError", None)
            or getattr(result, "is_error", None)
            or raw.get("isError")
            or raw.get("is_error")
        )
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
