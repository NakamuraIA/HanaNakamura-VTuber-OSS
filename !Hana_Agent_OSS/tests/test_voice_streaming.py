from __future__ import annotations

from hana_agent_oss.modules.voice.runtime import clamp_tts_text, extract_speakable_chunks, strip_xml_for_tts


def test_clamp_disabled_returns_full() -> None:
    text = "uma frase qualquer. " * 20
    assert clamp_tts_text(text, 0) == text


def test_clamp_cuts_at_sentence_boundary() -> None:
    text = "Primeira frase aqui. Segunda frase aqui. Terceira frase que estoura o limite."
    out = clamp_tts_text(text, 45)
    # mantem o maximo de frases inteiras que cabem no limite, sem cortar palavra
    assert out == "Primeira frase aqui. Segunda frase aqui."
    assert len(out) <= 45
    assert not out.endswith("Terceira")


def test_clamp_short_text_untouched() -> None:
    assert clamp_tts_text("curtinha.", 350) == "curtinha."


def test_splits_on_sentence_boundaries() -> None:
    chunks, rest = extract_speakable_chunks("Oi Operador. Tudo bem? Bora")
    assert chunks == ["Oi Operador.", "Tudo bem?"]
    assert rest == " Bora"  # frase incompleta fica no buffer


def test_does_not_split_decimals() -> None:
    chunks, rest = extract_speakable_chunks("custa 0.098 por")
    assert chunks == []  # o "." de 0.098 nao e fim de frase (seguido de digito)
    assert "0.098" in rest


def test_holds_at_open_tag_until_flush() -> None:
    # enquanto streama, nao emite nada a partir de um '<' (pode ser tag)
    chunks, rest = extract_speakable_chunks("Pronto. <gerar_imagem prompt=")
    assert chunks == ["Pronto."]
    assert rest.startswith(" <gerar_imagem")
    # no flush, o tail sai (a limpeza de XML e feita pelo chamador)
    chunks2, rest2 = extract_speakable_chunks(rest, flush=True)
    assert rest2 == ""
    assert chunks2  # algo sai no flush


def test_flush_emits_remaining_tail() -> None:
    chunks, rest = extract_speakable_chunks("Sem ponto final aqui", flush=True)
    assert chunks == ["Sem ponto final aqui"]
    assert rest == ""


def test_strip_xml_removes_action_blocks() -> None:
    text = 'Olha. <gerar_imagem prompt="gato">x</gerar_imagem> Pronto.'
    out = strip_xml_for_tts(text)
    assert "gerar_imagem" not in out
    assert "gato" not in out
    assert "Olha." in out and "Pronto." in out


def test_strip_xml_removes_stray_tags() -> None:
    assert "<" not in strip_xml_for_tts("a <b> c </b> d")


def test_newline_is_a_boundary() -> None:
    chunks, _ = extract_speakable_chunks("linha um\nlinha dois\n")
    assert chunks == ["linha um", "linha dois"]
