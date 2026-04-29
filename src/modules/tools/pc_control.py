from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any, Callable

import psutil

from src.config.config_loader import CONFIG
from src.modules.tools.pc_action_popup import confirm_pc_action_popup
from src.modules.tools.inbox_manager import InboxManager

logger = logging.getLogger(__name__)

try:
    import keyboard
except ImportError:  # pragma: no cover - optional dependency path
    keyboard = None


AUDIT_LOG_PATH = os.path.join("data", "logs", "pc_control_audit.jsonl")
LOW_RISK_ACTIONS = {
    "open_url",
    "open_path",
    "read_text_file",
    "view_image",
    "list_processes",
    "start_process",
    "type_text",
    "move_mouse",
    "set_volume",
    "media_key",
}
MEDIUM_RISK_ACTIONS = set()
HIGH_RISK_ACTIONS = {"kill_process", "run_command"}
ALLOWED_ACTIONS = LOW_RISK_ACTIONS | MEDIUM_RISK_ACTIONS | HIGH_RISK_ACTIONS
ACTION_FIELD_CANDIDATES = ("action", "type", "name", "tool")
ACTION_ALIASES = {
    "type": "type_text",
    "write": "type_text",
    "write_text": "type_text",
    "input_text": "type_text",
    "typewrite": "type_text",
    "paste": "type_text",
    "paste_text": "type_text",
    "colar": "type_text",
    "colar_texto": "type_text",
    "mouse_move": "move_mouse",
    "move_cursor": "move_mouse",
    "cursor_move": "move_mouse",
    "open_notepad": "start_process",
    "abrir_bloco_de_notas": "start_process",
    "open_bloco_de_notas": "start_process",
    "start_notepad": "start_process",
    "volume_up": "set_volume",
    "increase_volume": "set_volume",
    "raise_volume": "set_volume",
    "volume_down": "set_volume",
    "decrease_volume": "set_volume",
    "lower_volume": "set_volume",
    "mute_volume": "set_volume",
}
NOTEPAD_ALIASES = {
    "open_notepad",
    "abrir_bloco_de_notas",
    "open_bloco_de_notas",
    "start_notepad",
}

VK_MEDIA = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
}
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9

_LAST_STARTED_PROCESS: dict[str, Any] = {"pid": None, "target": "", "timestamp": 0.0}
PROJECT_ROOT = os.path.abspath(os.getcwd()).lower()
CRITICAL_PROCESS_NAMES = {
    "system",
    "system idle process",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "lsaiso.exe",
    "fontdrvhost.exe",
    "dwm.exe",
}
GENERIC_KILL_TARGETS = {
    "",
    "*",
    "all",
    "tudo",
    "todos",
    "everything",
    "processos",
    "processes",
    "os processos",
}


@dataclass(frozen=True)
class PCActionRequest:
    action: str
    payload: dict[str, Any]
    risk: str
    summary: str


def get_pc_control_settings() -> dict:
    block = CONFIG.get("PC_CONTROL", {})
    if not isinstance(block, dict):
        block = {}
    block.setdefault("brave_path", "")
    CONFIG["PC_CONTROL"] = block
    return block


def _extract_action_name(payload: dict[str, Any]) -> tuple[str, str]:
    for field in ACTION_FIELD_CANDIDATES:
        candidate = str(payload.get(field) or "").strip().lower()
        if candidate:
            return candidate, field
    return "", ""


def _normalize_pc_action_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_action, source_field = _extract_action_name(payload)
    normalized = dict(payload)
    action = ACTION_ALIASES.get(raw_action, raw_action)
    normalized["action"] = action

    if source_field and source_field != "action":
        normalized.pop(source_field, None)

    if raw_action in NOTEPAD_ALIASES:
        normalized.setdefault("command", "notepad.exe")

    if action == "type_text":
        if raw_action in {"paste", "paste_text", "colar", "colar_texto"}:
            normalized.setdefault("method", "paste")
        for fallback_field in ("text", "value", "content", "message"):
            value = normalized.get(fallback_field)
            if value:
                normalized["text"] = str(value)
                break

    if action == "move_mouse":
        if normalized.get("dx") is None and normalized.get("delta_x") is not None:
            normalized["dx"] = normalized.get("delta_x")
        if normalized.get("dy") is None and normalized.get("delta_y") is not None:
            normalized["dy"] = normalized.get("delta_y")
        if normalized.get("distance") is None:
            for fallback_field in ("amount", "pixels", "offset", "delta"):
                value = normalized.get(fallback_field)
                if value is not None:
                    normalized["distance"] = value
                    break
        if not normalized.get("direction") and normalized.get("dir"):
            normalized["direction"] = normalized.get("dir")

    if action == "set_volume":
        normalized = _normalize_set_volume_payload(normalized, raw_action)

    if action == "list_processes":
        if normalized.get("sort_by") is None:
            for field in ("order_by", "sort", "metric"):
                if normalized.get(field) is not None:
                    normalized["sort_by"] = normalized.get(field)
                    break

    if action == "kill_process":
        if normalized.get("pid") is None:
            for field in ("process_id", "processId"):
                if normalized.get(field) is not None:
                    normalized["pid"] = normalized.get(field)
                    break
        if not normalized.get("name"):
            for field in ("target", "process", "process_name", "exe", "image"):
                value = normalized.get(field)
                if value:
                    normalized["name"] = str(value)
                    break
        if normalized.get("names") is None and isinstance(normalized.get("name"), list):
            normalized["names"] = normalized.get("name")
            normalized.pop("name", None)

    return action, normalized


def _normalize_set_volume_payload(payload: dict[str, Any], raw_action: str) -> dict[str, Any]:
    normalized = dict(payload)

    if raw_action in {"volume_up", "increase_volume", "raise_volume"} and normalized.get("delta") is None:
        normalized["delta"] = 6
    if raw_action in {"volume_down", "decrease_volume", "lower_volume"} and normalized.get("delta") is None:
        normalized["delta"] = -6
    if raw_action in {"mute_volume"} and normalized.get("mute") is None:
        normalized["mute"] = True

    level = normalized.get("level")
    if isinstance(level, str):
        match = re.search(r"(-?\d{1,3})", level)
        if match:
            normalized["level"] = int(match.group(1))

    delta = normalized.get("delta")
    if isinstance(delta, str):
        match = re.search(r"(-?\d{1,3})", delta)
        if match:
            normalized["delta"] = int(match.group(1))

    if normalized.get("level") is not None or normalized.get("delta") is not None or normalized.get("mute") is not None:
        return normalized

    amount = normalized.get("amount")
    if amount is None:
        amount = normalized.get("step")
    if amount is None:
        amount = normalized.get("value")
    amount_value = None
    if amount is not None:
        try:
            amount_value = int(float(str(amount).replace("%", "").strip()))
        except (TypeError, ValueError):
            amount_value = None

    for candidate_field in ("direction", "mode", "operation", "intent", "query", "text", "instruction", "command", "value"):
        raw_value = normalized.get(candidate_field)
        if raw_value is None:
            continue
        lowered = str(raw_value).strip().lower()
        if not lowered:
            continue

        if re.search(r"(-?\d{1,3})\s*%", lowered):
            normalized["level"] = int(re.search(r"(-?\d{1,3})\s*%", lowered).group(1))
            return normalized

        if any(token in lowered for token in ("mute", "silenc", "mutar")):
            normalized["mute"] = True
            return normalized

        if any(token in lowered for token in ("down", "lower", "decrease", "quieter", "abaix", "diminu", "reduz", "menos volume")):
            normalized["delta"] = -abs(amount_value or 6)
            return normalized

        if any(token in lowered for token in ("up", "raise", "increase", "louder", "aument", "sobe", "mais volume")):
            normalized["delta"] = abs(amount_value or 6)
            return normalized

        if any(token in lowered for token in ("full volume", "volume total")) or re.search(r"\bmax(?:im[oa]?|imum)?\b", lowered):
            normalized["level"] = 100
            return normalized

        if any(token in lowered for token in ("zero volume", "sem volume")) or re.search(r"\bmin(?:im[oa]?|imum)?\b", lowered):
            normalized["level"] = 0
            return normalized

    return normalized


def parse_pc_action_payload(raw_payload: str | dict[str, Any]) -> PCActionRequest:
    payload = raw_payload
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except Exception as exc:
            raise ValueError(f"JSON invalido em <acao_pc>: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("O payload de <acao_pc> precisa ser um objeto JSON.")

    action, normalized = _normalize_pc_action_payload(payload)
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Acao de PC nao suportada: {action or '(vazia)'}")
    if action == "kill_process":
        has_target = any(normalized.get(field) for field in ("pid", "name", "pids", "names"))
        target_text = str(normalized.get("name") or normalized.get("target") or "").strip().lower()
        target_names = normalized.get("names") if isinstance(normalized.get("names"), list) else []
        if not has_target:
            raise ValueError("Informe 'pid' ou 'name' especifico para encerrar processo. Nunca use alvo generico.")
        if (target_text and target_text in GENERIC_KILL_TARGETS) or any(str(item).strip().lower() in GENERIC_KILL_TARGETS for item in target_names):
            raise ValueError("Alvo generico recusado. Liste processos primeiro e escolha PID ou nome exato.")

    return PCActionRequest(
        action=action,
        payload=normalized,
        risk=get_action_risk(action),
        summary=summarize_pc_action(normalized),
    )


def get_action_risk(action: str) -> str:
    if action in HIGH_RISK_ACTIONS:
        return "alto"
    if action in MEDIUM_RISK_ACTIONS:
        return "medio"
    return "baixo"


def summarize_pc_action(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "").strip().lower()
    if action == "open_url":
        return f"Abrir URL: {payload.get('url', '')}"
    if action == "open_path":
        return f"Abrir caminho: {payload.get('path', '')}"
    if action == "read_text_file":
        return f"Ler arquivo: {payload.get('path', '')}"
    if action == "view_image":
        return f"Abrir imagem: {payload.get('path', '')}"
    if action == "list_processes":
        query = str(payload.get("query") or "").strip()
        return f"Listar processos{' com filtro ' + query if query else ''}"
    if action == "start_process":
        return f"Iniciar processo: {payload.get('path') or payload.get('command') or ''}"
    if action == "kill_process":
        target = payload.get("pid") or payload.get("name") or payload.get("pids") or payload.get("names") or ""
        return f"Encerrar processo: {target}"
    if action == "run_command":
        return f"Executar comando: {payload.get('command', '')}"
    if action == "type_text":
        text = str(payload.get("text") or "")
        preview = text[:80] + ("..." if len(text) > 80 else "")
        return f"Digitar texto: {preview}"
    if action == "move_mouse":
        if payload.get("x") is not None and payload.get("y") is not None:
            return f"Mover mouse para ({payload.get('x')}, {payload.get('y')})"
        if payload.get("dx") is not None or payload.get("dy") is not None:
            return f"Mover mouse relativamente por dx={payload.get('dx', 0)}, dy={payload.get('dy', 0)}"
        direction = str(payload.get("direction") or "").strip().lower()
        if direction:
            return f"Mover mouse para {direction} por {payload.get('distance', 120)}px"
        return f"Mover mouse para ({payload.get('x')}, {payload.get('y')})"
    if action == "set_volume":
        if payload.get("mute") is not None:
            return "Alternar mute do sistema"
        if payload.get("level") is not None:
            return f"Ajustar volume para {payload.get('level')}%"
        return f"Ajustar volume por delta {payload.get('delta')}"
    if action == "media_key":
        return f"Enviar tecla de midia: {payload.get('key', '')}"
    return f"Acao de PC: {action}"


def append_pc_action_audit(entry: dict[str, Any]):
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
    payload = dict(entry)
    payload.setdefault("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _remember_started_process(pid: int | None, target: str):
    _LAST_STARTED_PROCESS["pid"] = int(pid) if pid else None
    _LAST_STARTED_PROCESS["target"] = str(target or "")
    _LAST_STARTED_PROCESS["timestamp"] = time.time()


def _safe_proc_attr(proc: psutil.Process, name: str, default=None):
    try:
        return getattr(proc, name)()
    except Exception:
        return default


def _safe_proc_info(proc: psutil.Process, field: str, default=None):
    try:
        if hasattr(proc, "info") and field in proc.info:
            return proc.info.get(field, default)
    except Exception:
        pass
    return _safe_proc_attr(proc, field, default)


def _proc_cmdline_text(proc: psutil.Process) -> str:
    cmdline = _safe_proc_info(proc, "cmdline", []) or []
    if isinstance(cmdline, (list, tuple)):
        return " ".join(str(item) for item in cmdline)
    return str(cmdline or "")


def _get_protected_pids() -> set[int]:
    protected = {os.getpid()}
    try:
        current = psutil.Process(os.getpid())
        protected.update(parent.pid for parent in current.parents())
        protected.update(child.pid for child in current.children(recursive=True))
    except Exception:
        pass
    if _LAST_STARTED_PROCESS.get("pid"):
        try:
            protected.add(int(_LAST_STARTED_PROCESS["pid"]))
        except Exception:
            pass
    return protected


def _is_hana_process(proc: psutil.Process) -> bool:
    try:
        if int(proc.pid) in _get_protected_pids():
            return True
    except Exception:
        pass
    cmdline = _proc_cmdline_text(proc).lower()
    if PROJECT_ROOT and PROJECT_ROOT in cmdline:
        return True
    return any(token in cmdline for token in ("main.py", "hana_gui.py", "run_hana_gui_hidden.vbs"))


def _is_critical_process(proc: psutil.Process) -> bool:
    try:
        if int(proc.pid) <= 4:
            return True
    except Exception:
        pass
    name = str(_safe_proc_info(proc, "name", "") or "").strip().lower()
    return name in CRITICAL_PROCESS_NAMES


def _classify_process(proc: psutil.Process) -> tuple[bool, str]:
    if _is_hana_process(proc):
        return True, "HANA/PROTEGIDO"
    if _is_critical_process(proc):
        return True, "SISTEMA/PROTEGIDO"
    return False, "USUARIO"


def _memory_mb(proc: psutil.Process) -> float:
    memory_info = _safe_proc_info(proc, "memory_info")
    rss = getattr(memory_info, "rss", 0) if memory_info is not None else 0
    return round(float(rss or 0) / 1024 / 1024, 1)


def _cpu_percent(proc: psutil.Process) -> float:
    try:
        return round(float(proc.cpu_percent(interval=None)), 1)
    except Exception:
        return 0.0


def _get_cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return int(point.x), int(point.y)


def _iter_visible_windows() -> list[tuple[int, int, str]]:
    windows: list[tuple[int, int, str]] = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append((int(hwnd), int(pid.value), title_buffer.value))
        return True

    user32.EnumWindows(_callback, 0)
    return windows


def _find_window_handle(*, pid: int | None = None, process_name: str = "", title_contains: str = "") -> int | None:
    process_name = process_name.strip().lower()
    title_contains = title_contains.strip().lower()
    for hwnd, window_pid, title in _iter_visible_windows():
        if pid is not None and window_pid != int(pid):
            continue
        if title_contains and title_contains not in title.lower():
            continue
        if process_name:
            try:
                current_name = psutil.Process(window_pid).name().lower()
            except Exception:
                continue
            if current_name != process_name:
                continue
        return hwnd
    return None


def _focus_window_handle(hwnd: int | None) -> bool:
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    return int(user32.GetForegroundWindow()) == int(hwnd)


def _focus_window_for_payload(payload: dict[str, Any]) -> bool:
    pid = payload.get("pid")
    title = str(payload.get("window_title") or payload.get("title") or "").strip()
    process_name = str(payload.get("process_name") or "").strip().lower()
    focus_last_started = bool(payload.get("focus_last_started", False))
    recent_started = time.time() - float(_LAST_STARTED_PROCESS.get("timestamp") or 0.0) <= 12.0

    if not pid and not title and not process_name and not focus_last_started and not recent_started:
        return False

    if pid is None and (focus_last_started or recent_started):
        pid = _LAST_STARTED_PROCESS.get("pid")

    hwnd = None
    if pid is not None:
        hwnd = _find_window_handle(pid=int(pid), title_contains=title)
    if hwnd is None and process_name:
        hwnd = _find_window_handle(process_name=process_name, title_contains=title)
    if hwnd is None and title:
        hwnd = _find_window_handle(title_contains=title)
    if hwnd is None and (focus_last_started or recent_started) and _LAST_STARTED_PROCESS.get("pid"):
        hwnd = _find_window_handle(pid=int(_LAST_STARTED_PROCESS["pid"]))

    return _focus_window_handle(hwnd)


def confirm_pc_action(request: PCActionRequest) -> bool:
    return confirm_pc_action_popup(
        title="Confirmar ação no PC",
        body=request.summary,
        risk_label=request.risk,
        timeout_seconds=15,
        parent=None,
    )


def execute_pc_action(
    raw_payload: str | dict[str, Any],
    *,
    confirm_callback: Callable[[PCActionRequest], bool] | None = None,
) -> dict[str, Any]:
    try:
        request = parse_pc_action_payload(raw_payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "action": "parse_pc_action",
            "risk": "baixo",
            "summary": "Interpretar acao no PC",
            "message": str(exc),
        }
    confirm_callback = confirm_callback or confirm_pc_action

    if request.risk in {"medio", "alto"}:
        allowed = bool(confirm_callback(request))
        append_pc_action_audit(
            {
                "action": request.action,
                "risk": request.risk,
                "decision": "allowed" if allowed else "denied",
                "summary": request.summary,
            }
        )
        if not allowed:
            return {
                "ok": False,
                "status": "denied",
                "action": request.action,
                "risk": request.risk,
                "summary": request.summary,
                "message": "Ação negada pelo usuário.",
            }

    try:
        result = _dispatch_pc_action(request)
        append_pc_action_audit(
            {
                "action": request.action,
                "risk": request.risk,
                "decision": "executed",
                "summary": request.summary,
                "details": result,
            }
        )
        return {
            "ok": True,
            "status": "executed",
            "action": request.action,
            "risk": request.risk,
            "summary": request.summary,
            **result,
        }
    except Exception as exc:
        logger.exception("[PC CONTROL] Falha ao executar %s", request.action)
        append_pc_action_audit(
            {
                "action": request.action,
                "risk": request.risk,
                "decision": "failed",
                "summary": request.summary,
                "error": str(exc),
            }
        )
        return {
            "ok": False,
            "status": "failed",
            "action": request.action,
            "risk": request.risk,
            "summary": request.summary,
            "message": str(exc),
        }


def _dispatch_pc_action(request: PCActionRequest) -> dict[str, Any]:
    action = request.action
    payload = request.payload

    if action == "open_url":
        return _open_url(payload)
    if action == "open_path":
        return _open_path(payload)
    if action == "read_text_file":
        return _read_text_file(payload)
    if action == "view_image":
        return _view_image(payload)
    if action == "list_processes":
        return _list_processes(payload)
    if action == "start_process":
        return _start_process(payload)
    if action == "kill_process":
        return _kill_process(payload)
    if action == "run_command":
        return _run_command(payload)
    if action == "type_text":
        return _type_text(payload)
    if action == "move_mouse":
        return _move_mouse(payload)
    if action == "set_volume":
        return _set_volume(payload)
    if action == "media_key":
        return _media_key(payload)
    raise RuntimeError(f"Ação não implementada: {action}")


def _require_path(payload: dict[str, Any], field: str = "path") -> str:
    path = os.path.abspath(str(payload.get(field) or "").strip())
    if not path:
        raise ValueError(f"O campo '{field}' é obrigatório.")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Caminho não encontrado: {path}")
    return path


def _open_url(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("A URL precisa começar com http:// ou https://")

    brave_path = str(get_pc_control_settings().get("brave_path") or "").strip()
    if brave_path and os.path.exists(brave_path):
        subprocess.Popen([brave_path, url])
        return {"message": f"URL aberta no Brave: {url}", "target": url}

    webbrowser.open(url)
    return {"message": f"URL aberta: {url}", "target": url}


def _open_path(payload: dict[str, Any]) -> dict[str, Any]:
    path = _require_path(payload)
    os.startfile(path)
    return {"message": f"Caminho aberto: {path}", "target": path}


def _read_text_file(payload: dict[str, Any]) -> dict[str, Any]:
    path = _require_path(payload)
    max_chars = int(payload.get("max_chars") or 4000)
    ext = os.path.splitext(path)[1].lower()
    inbox = InboxManager()
    if ext == ".pdf":
        content = inbox.read_pdf(path, max_chars=max_chars)
    else:
        content = inbox.read_text_like(path, max_chars=max_chars)
    return {
        "message": f"Arquivo lido: {path}",
        "target": path,
        "content": content,
    }


def _view_image(payload: dict[str, Any]) -> dict[str, Any]:
    path = _require_path(payload)
    os.startfile(path)
    return {"message": f"Imagem aberta: {path}", "target": path}


def _list_processes(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip().lower()
    limit = max(1, min(int(payload.get("limit") or 25), 100))
    sort_by = str(payload.get("sort_by") or payload.get("sort") or "memory").strip().lower()
    include_system = bool(payload.get("include_system", False))
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline", "username", "status"]):
        name = str(_safe_proc_info(proc, "name", "") or "")
        cmdline = _proc_cmdline_text(proc)
        haystack = f"{name} {cmdline}".lower()
        if query and query not in haystack:
            continue
        protected, protection = _classify_process(proc)
        if protected and not include_system and protection == "SISTEMA/PROTEGIDO":
            continue
        rows.append(
            {
                "pid": int(_safe_proc_info(proc, "pid", getattr(proc, "pid", 0)) or 0),
                "name": name,
                "memory_mb": _memory_mb(proc),
                "cpu_percent": _cpu_percent(proc),
                "protected": protected,
                "protection": protection,
                "safe_to_kill": not protected,
                "cmdline": cmdline[:160],
            }
        )

    if sort_by in {"cpu", "cpu_percent"}:
        rows.sort(key=lambda row: row["cpu_percent"], reverse=True)
    elif sort_by in {"pid"}:
        rows.sort(key=lambda row: row["pid"])
    elif sort_by in {"name"}:
        rows.sort(key=lambda row: row["name"].lower())
    else:
        rows.sort(key=lambda row: row["memory_mb"], reverse=True)
    rows = rows[:limit]

    content = "\n".join(
        [
            f"{row['pid']} - {row['name']} | RAM {row['memory_mb']} MB | CPU {row['cpu_percent']}% | {row['protection']}"
            for row in rows
        ]
    ) or "(nenhum processo encontrado)"
    return {
        "message": f"{len(rows)} processo(s) listado(s).",
        "content": content,
        "count": len(rows),
        "processes": rows,
    }


def _start_process(payload: dict[str, Any]) -> dict[str, Any]:
    args = payload.get("args") or []
    cwd = str(payload.get("cwd") or "").strip() or None

    if payload.get("path"):
        path = str(payload.get("path")).strip()
        if not os.path.exists(path):
            raise FileNotFoundError(f"Executável não encontrado: {path}")
        if not isinstance(args, list):
            raise ValueError("O campo 'args' precisa ser uma lista.")
        proc = subprocess.Popen([path, *[str(item) for item in args]], cwd=cwd)
        target = path
    else:
        command = payload.get("command")
        if not command:
            raise ValueError("Use 'path' ou 'command' para iniciar processo.")
        if isinstance(command, list):
            proc = subprocess.Popen([str(item) for item in command], cwd=cwd)
        else:
            proc = subprocess.Popen(str(command), cwd=cwd, shell=True)
        target = str(command)

    _remember_started_process(proc.pid, target)
    focus_requested = payload.get("focus_window", True)
    focus_ok = False
    if focus_requested:
        for _ in range(20):
            time.sleep(0.15)
            if _focus_window_handle(_find_window_handle(pid=proc.pid)):
                focus_ok = True
                break

    return {
        "message": f"Processo iniciado: {target}",
        "target": target,
        "pid": proc.pid,
        "window_focused": focus_ok,
    }


def _kill_process(payload: dict[str, Any]) -> dict[str, Any]:
    pid = payload.get("pid")
    name = str(payload.get("name") or "").strip().lower()
    pids = payload.get("pids") if isinstance(payload.get("pids"), list) else []
    names = payload.get("names") if isinstance(payload.get("names"), list) else []

    if not pid and not name and not pids and not names:
        raise ValueError("Informe 'pid' ou 'name' especifico para encerrar processo. Nunca use alvo generico.")
    if (name and name in GENERIC_KILL_TARGETS) or any(str(item).strip().lower() in GENERIC_KILL_TARGETS for item in names):
        raise ValueError("Alvo generico recusado. Liste processos primeiro e escolha PID ou nome exato.")

    targets: list[psutil.Process] = []
    if pid is not None:
        targets.append(psutil.Process(int(pid)))
    for item in pids:
        targets.append(psutil.Process(int(item)))
    if name:
        matches = [proc for proc in psutil.process_iter(["pid", "name", "cmdline"]) if str(_safe_proc_info(proc, "name", "") or "").lower() == name]
        if not matches:
            raise RuntimeError(f"Nenhum processo encontrado com nome exato: {name}")
        if len(matches) > 1 and not payload.get("allow_multiple"):
            raise RuntimeError(f"Mais de um processo com nome '{name}'. Informe o PID.")
        targets.extend(matches)
    for raw_name in names:
        target_name = str(raw_name or "").strip().lower()
        if not target_name or target_name in GENERIC_KILL_TARGETS:
            continue
        targets.extend(
            proc
            for proc in psutil.process_iter(["pid", "name", "cmdline"])
            if str(_safe_proc_info(proc, "name", "") or "").lower() == target_name
        )

    unique: dict[int, psutil.Process] = {}
    for proc in targets:
        unique[int(proc.pid)] = proc
    targets = list(unique.values())
    if not targets:
        raise RuntimeError("Nenhum processo valido encontrado para encerrar.")

    blocked = []
    killed = []
    for proc in targets:
        protected, protection = _classify_process(proc)
        proc_name = str(_safe_proc_info(proc, "name", "") or "")
        if protected:
            blocked.append(f"{proc.pid} - {proc_name} ({protection})")
            continue

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
        killed.append({"pid": proc.pid, "name": proc_name})

    if blocked and not killed:
        raise RuntimeError("Processo protegido recusado: " + "; ".join(blocked))

    message = f"{len(killed)} processo(s) encerrado(s)."
    if blocked:
        message += " Protegidos recusados: " + "; ".join(blocked)
    return {
        "message": message,
        "killed": killed,
        "blocked": blocked,
        "target": ", ".join(f"{item['pid']}:{item['name']}" for item in killed),
    }


def _run_command(payload: dict[str, Any]) -> dict[str, Any]:
    command = payload.get("command")
    if not command:
        raise ValueError("O campo 'command' é obrigatório.")

    cwd = str(payload.get("cwd") or "").strip() or None
    timeout_seconds = max(1, min(int(payload.get("timeout") or 20), 60))

    if isinstance(command, list):
        completed = subprocess.run(
            [str(item) for item in command],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        command_text = " ".join([str(item) for item in command])
    else:
        command_text = str(command)
        completed = subprocess.run(
            command_text,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=True,
        )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return {
        "message": f"Comando executado com código {completed.returncode}.",
        "target": command_text,
        "returncode": completed.returncode,
        "stdout": stdout[:4000],
        "stderr": stderr[:2000],
    }


def _set_clipboard_text(text: str):
    try:
        import pyperclip

        pyperclip.copy(text)
        return
    except Exception:
        pass

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()


def _type_text(payload: dict[str, Any]) -> dict[str, Any]:
    if keyboard is None:
        raise RuntimeError("Biblioteca 'keyboard' não está disponível para digitação automatizada.")
    text = str(payload.get("text") or "")
    if not text:
        raise ValueError("O campo 'text' é obrigatório para type_text.")
    delay = float(payload.get("delay") or 0)
    focus_ok = _focus_window_for_payload(payload)
    focus_delay = max(0.0, min(float(payload.get("focus_delay") or 0.35), 3.0))
    if focus_delay:
        time.sleep(focus_delay)
    method = str(payload.get("method") or "").strip().lower()
    should_paste = method in {"paste", "clipboard", "ctrl_v"} or len(text) > 280 or "\n" in text
    if should_paste:
        _set_clipboard_text(text)
        keyboard.press_and_release("ctrl+v")
        typed_method = "clipboard"
    else:
        keyboard.write(text, delay=delay)
        typed_method = "keyboard"
    if payload.get("press_enter"):
        keyboard.press_and_release("enter")
    return {
        "message": "Texto digitado no sistema.",
        "chars": len(text),
        "window_focused": focus_ok,
        "method": typed_method,
    }


def _move_mouse(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("x") is not None and payload.get("y") is not None:
        x_pos = int(payload["x"])
        y_pos = int(payload["y"])
    else:
        current_x, current_y = _get_cursor_pos()
        if payload.get("dx") is not None or payload.get("dy") is not None:
            dx = int(payload.get("dx") or 0)
            dy = int(payload.get("dy") or 0)
        else:
            direction = str(payload.get("direction") or "").strip().lower()
            distance = int(payload.get("distance") or 120)
            direction_map = {
                "right": (distance, 0),
                "left": (-distance, 0),
                "up": (0, -distance),
                "down": (0, distance),
                "upright": (distance, -distance),
                "up_right": (distance, -distance),
                "upleft": (-distance, -distance),
                "up_left": (-distance, -distance),
                "downright": (distance, distance),
                "down_right": (distance, distance),
                "downleft": (-distance, distance),
                "down_left": (-distance, distance),
            }
            if direction not in direction_map:
                raise ValueError("Use 'x'/'y', 'dx'/'dy' ou 'direction'/'distance' para move_mouse.")
            dx, dy = direction_map[direction]
        x_pos = current_x + dx
        y_pos = current_y + dy
    ctypes.windll.user32.SetCursorPos(x_pos, y_pos)
    return {
        "message": f"Mouse movido para ({x_pos}, {y_pos}).",
        "x": x_pos,
        "y": y_pos,
    }


def _send_vk(vk_code: int, count: int = 1):
    for _ in range(max(1, count)):
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def _set_volume(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mute") is not None:
        _send_vk(VK_VOLUME_MUTE)
        return {"message": "Mute alternado."}

    if payload.get("level") is not None:
        level = max(0, min(int(payload["level"]), 100))
        _send_vk(VK_VOLUME_DOWN, 60)
        _send_vk(VK_VOLUME_UP, round(level / 2))
        return {"message": f"Volume aproximado ajustado para {level}%."}

    if payload.get("delta") is None:
        raise ValueError("Use 'level', 'delta' ou 'mute' em set_volume.")

    delta = int(payload["delta"])
    if delta > 0:
        _send_vk(VK_VOLUME_UP, min(abs(delta), 20))
    elif delta < 0:
        _send_vk(VK_VOLUME_DOWN, min(abs(delta), 20))
    return {"message": f"Volume ajustado por delta {delta}."}


def _media_key(payload: dict[str, Any]) -> dict[str, Any]:
    key = str(payload.get("key") or "").strip().lower()
    vk_code = VK_MEDIA.get(key)
    if vk_code is None:
        raise ValueError("Use media_key com 'play_pause', 'next', 'previous' ou 'stop'.")
    _send_vk(vk_code)
    return {"message": f"Tecla de mídia enviada: {key}.", "target": key}
