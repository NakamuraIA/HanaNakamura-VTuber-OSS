"""Trava o bug do vazamento entre canais.

Incidente real: a Hana respondeu no Discord citando uma conversa de voz de mais
de uma hora antes. Causa: `build_unified_history` recebia `channel` mas so usava
pra escolher o limite — o filtro era `if event_channel not in ALL_CHANNELS`, uma
tautologia que nao filtrava nada.

Roda com:  python -m backend.tests.test_vazamento_canal
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backend.api.services.unified_history import build_unified_history, channels_visible_to
from backend.memory.store import MemoryStore


def _store(tmp: str) -> MemoryStore:
    return MemoryStore(str(Path(tmp) / "m.db"), events_path=str(Path(tmp) / "e.jsonl"))


def test_discord_nao_ve_conversa_de_voz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = _store(tmp)
        mem.append_event("user", "SEGREDO falado na call", channel="voice")
        mem.append_event("hana", "entendi o SEGREDO", channel="terminal_agent")
        mem.append_event("user", "oi pelo discord", channel="discord")

        texto = json.dumps(build_unified_history(mem, channel="discord"), ensure_ascii=False)
        assert "SEGREDO" not in texto, "conversa de voz vazou pro Discord"
        assert "discord" in texto


def test_control_center_nao_ve_discord() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = _store(tmp)
        mem.append_event("user", "MENSAGEM_PRIVADA no discord", channel="discord")
        mem.append_event("user", "oi pelo painel", channel="control_center")

        texto = json.dumps(build_unified_history(mem, channel="control_center"), ensure_ascii=False)
        assert "MENSAGEM_PRIVADA" not in texto, "Discord vazou pro painel"
        assert "painel" in texto


def test_voz_e_terminal_compartilham_a_mesma_conversa() -> None:
    # De proposito: e o mesmo lugar fisico. Voce fala, depois digita, e a
    # conversa continua — separar cortaria o assunto no meio.
    with tempfile.TemporaryDirectory() as tmp:
        mem = _store(tmp)
        mem.append_event("user", "falei isso na call", channel="voice")
        mem.append_event("user", "e digitei isso no terminal", channel="terminal_agent")

        for canal in ("voice", "terminal_agent"):
            texto = json.dumps(build_unified_history(mem, channel=canal), ensure_ascii=False)
            assert "na call" in texto and "no terminal" in texto, f"quebrou em {canal}"


def test_canal_desconhecido_nao_ve_tudo() -> None:
    # O erro seguro e ver de menos. Um canal novo sem mapeamento nao pode
    # herdar acesso a todo o historico so por nao estar na lista.
    assert "discord" not in channels_visible_to("canal_que_nao_existe")


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {nome}")
    print("\nok: vazamento entre canais travado")
