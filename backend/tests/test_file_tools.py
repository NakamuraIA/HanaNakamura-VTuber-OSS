from pathlib import Path

from backend.tools.file_tools import file_write


def test_file_write_expande_desktop_do_usuario(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    result = file_write({"path": "~/Desktop/hana.md", "content": "# Hana\n"})

    assert result.ok is True
    assert (tmp_path / "Desktop" / "hana.md").read_text(encoding="utf-8") == "# Hana\n"


def test_file_write_devolve_erro_sem_derrubar_o_turno(monkeypatch, tmp_path: Path) -> None:
    def negar_escrita(*_args, **_kwargs):
        raise PermissionError(13, "Acesso negado")

    monkeypatch.setattr(Path, "write_text", negar_escrita)

    result = file_write({"path": str(tmp_path / "hana.md"), "content": "texto"})

    assert result.ok is False
    assert "PermissionError" in str(result.error)
    assert "Acesso negado" in str(result.error)
