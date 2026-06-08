from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT / "!Hana_Agent_OSS"
CONTROL_PANEL_ROOT = ROOT / "control_panel"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8042"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:5173"


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:
            self.process.kill()


@dataclass
class ServiceTarget:
    name: str
    url: str
    external: bool = False


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    paths = [str(AGENT_ROOT)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("HANA_BACKEND_HOST", "127.0.0.1")
    env.setdefault("HANA_BACKEND_PORT", "8042")
    env.setdefault("HANA_FRONTEND_PORT", "5173")
    return env


def _start_backend() -> ManagedProcess:
    command = [sys.executable, "-m", "hana_agent_oss.api.server"]
    process = subprocess.Popen(
        command,
        cwd=str(AGENT_ROOT),
        env=_python_env(),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    return ManagedProcess("backend", process)


def _start_frontend() -> ManagedProcess:
    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    command = [npm_command, "run", "dev", "--", "--host", "127.0.0.1", "--port", os.environ.get("HANA_FRONTEND_PORT", "5173")]
    process = subprocess.Popen(
        command,
        cwd=str(CONTROL_PANEL_ROOT),
        env=os.environ.copy(),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    return ManagedProcess("control_panel", process)


def _http_json(url: str, *, method: str = "GET", timeout: float = 3.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 300, body
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, str(exc)


def _wait_http(url: str, *, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok, _body = _http_json(url, timeout=1.5)
        if ok:
            return True
        time.sleep(0.5)
    return False


def _is_http_ready(url: str) -> bool:
    ok, _body = _http_json(url, timeout=1.0)
    return ok


def healthcheck(url: str = DEFAULT_BACKEND_URL) -> int:
    ok, body = _http_json(f"{url}/api/health")
    print(body)
    return 0 if ok else 1


def shutdown(url: str = DEFAULT_BACKEND_URL) -> int:
    ok, body = _http_json(f"{url}/api/system/shutdown", method="POST")
    print(body)
    return 0 if ok else 1


def run_supervisor(*, backend: bool, frontend: bool) -> int:
    processes: list[ManagedProcess] = []
    targets: list[ServiceTarget] = []
    try:
        if backend:
            backend_health_url = f"{DEFAULT_BACKEND_URL}/api/health"
            if _is_http_ready(backend_health_url):
                print("Hana Agent OSS backend ja esta ativo em http://127.0.0.1:8042")
                targets.append(ServiceTarget("backend", backend_health_url, external=True))
            else:
                processes.append(_start_backend())
                targets.append(ServiceTarget("backend", backend_health_url))
                print("Hana Agent OSS backend iniciado em http://127.0.0.1:8042")
                if _wait_http(backend_health_url, timeout=30):
                    print("Backend pronto: /api/health respondeu OK.")
                else:
                    print("Backend ainda nao respondeu ao healthcheck; mantendo supervisor ativo.")
        if frontend:
            if _is_http_ready(DEFAULT_FRONTEND_URL):
                print("Hana Control Panel ja esta ativo em http://127.0.0.1:5173")
                targets.append(ServiceTarget("control_panel", DEFAULT_FRONTEND_URL, external=True))
                if os.environ.get("HANA_OPEN_BROWSER", "1").lower() not in {"0", "false", "no"}:
                    webbrowser.open(DEFAULT_FRONTEND_URL)
            else:
                processes.append(_start_frontend())
                targets.append(ServiceTarget("control_panel", DEFAULT_FRONTEND_URL))
                print("Hana Control Panel iniciado em http://127.0.0.1:5173")
                if _wait_http(DEFAULT_FRONTEND_URL, timeout=30):
                    print("Control Panel pronto em http://127.0.0.1:5173")
                    if os.environ.get("HANA_OPEN_BROWSER", "1").lower() not in {"0", "false", "no"}:
                        webbrowser.open(DEFAULT_FRONTEND_URL)
                else:
                    print("Control Panel ainda nao respondeu; mantendo supervisor ativo.")
        if not processes and not targets:
            return healthcheck()
        if not processes and targets:
            print("Servicos existentes reutilizados. Pressione Ctrl+C para sair do supervisor sem encerrar esses processos.")

        while True:
            for item in processes:
                code = item.process.poll()
                if code is not None:
                    print(f"{item.name} encerrou com codigo {code}.")
                    return int(code or 0)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Encerrando Hana...")
        return 0
    finally:
        for item in reversed(processes):
            item.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hana local supervisor.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Sobe backend e Control Panel.")
    sub.add_parser("backend-only", help="Sobe somente o backend Hana Agent OSS.")
    sub.add_parser("frontend-only", help="Sobe somente o Control Panel.")
    sub.add_parser("healthcheck", help="Verifica o backend local.")
    sub.add_parser("shutdown", help="Solicita shutdown do backend local.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "run"
    if command == "healthcheck":
        return healthcheck()
    if command == "shutdown":
        return shutdown()
    if command == "backend-only":
        return run_supervisor(backend=True, frontend=False)
    if command == "frontend-only":
        return run_supervisor(backend=False, frontend=True)
    return run_supervisor(backend=True, frontend=True)


if __name__ == "__main__":
    raise SystemExit(main())
