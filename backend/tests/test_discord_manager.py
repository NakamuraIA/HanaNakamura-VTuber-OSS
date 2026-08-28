from __future__ import annotations

from pathlib import Path

from backend.discord_bot import manager


class _FakeProcess:
    def __init__(self, pid: int, cwd: Path) -> None:
        self.info = {
            "pid": pid,
            "ppid": 1,
            "cmdline": ["python", "-m", "backend.discord_bot"],
        }
        self._cwd = cwd
        self.terminated = False

    def cwd(self) -> str:
        return str(self._cwd)

    def terminate(self) -> None:
        self.terminated = True


def test_limpeza_do_discord_nao_encerra_bot_de_outro_checkout(monkeypatch, tmp_path: Path) -> None:
    same_checkout = _FakeProcess(101, manager._AGENT_ROOT)
    other_checkout = _FakeProcess(102, tmp_path / "outra-hana")
    monkeypatch.setattr(manager.os, "getpid", lambda: 999)
    monkeypatch.setattr(manager.psutil, "process_iter", lambda _fields: [same_checkout, other_checkout])

    manager.DiscordBotManager._kill_orphan_bot_processes()

    assert same_checkout.terminated is True
    assert other_checkout.terminated is False
