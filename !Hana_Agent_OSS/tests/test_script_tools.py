from __future__ import annotations

from pathlib import Path

from hana_agent_oss.tools import script_tools


def test_create_script_writes_into_own_dir(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)

    result = script_tools.create_script("youtube_download.py", "print('oi')")

    assert result["ok"]
    created = scripts_dir / "youtube_download.py"
    assert created.exists()
    assert "print('oi')" in created.read_text(encoding="utf-8")


def test_create_script_defaults_to_py(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)

    result = script_tools.create_script("sem_extensao", "print(1)")

    assert result["ok"]
    assert result["script"] == "sem_extensao.py"


def test_create_script_ignores_guessed_absolute_path(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)

    result = script_tools.create_script(
        r"C:\\Users\\Operador\\Desktop\\bot_dc\\.agent\\scripts\\youtube_download.py",
        "print(1)",
    )

    assert result["ok"]
    assert scripts_dir.resolve() in Path(result["path"]).resolve().parents
    assert "bot_dc" not in result["path"]
    assert (scripts_dir / "youtube_download.py").exists()


def test_create_script_rejects_disallowed_extension(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)

    # .exe is not allowed -> collapses to default .py stem
    result = script_tools.create_script("malware.exe", "print(1)")

    assert result["ok"]
    assert result["script"] == "malware.py"


def test_create_script_refuses_clobber_without_overwrite(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "ja.py").write_text("original", encoding="utf-8")
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)

    blocked = script_tools.create_script("ja.py", "novo")
    assert not blocked["ok"]
    assert blocked["error"] == "script_already_exists"
    assert "original" in (scripts_dir / "ja.py").read_text(encoding="utf-8")

    forced = script_tools.create_script("ja.py", "novo", overwrite=True)
    assert forced["ok"]
    assert "novo" in (scripts_dir / "ja.py").read_text(encoding="utf-8")


def test_list_and_read_scripts(tmp_path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    monkeypatch.setattr(script_tools, "SCRIPTS_DIR", scripts_dir)
    script_tools.create_script("a.py", "print('a')")

    names = {s["name"] for s in script_tools.list_scripts()}
    assert "a.py" in names

    read = script_tools.read_script("a.py")
    assert read["ok"]
    assert "print('a')" in read["content"]

    missing = script_tools.read_script("nao_existe.py")
    assert not missing["ok"]
    assert missing["error"] == "script_not_found"


def test_script_tools_registered() -> None:
    from hana_agent_oss.core.registry import ToolRegistry

    reg = ToolRegistry()
    script_tools.register_script_tools(reg)
    names = {t.name for t in reg.list()}
    assert {"script.create", "script.list", "script.read"} <= names
