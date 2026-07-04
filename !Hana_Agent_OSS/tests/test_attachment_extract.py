"""Extração de texto de anexos de documento (PDF/texto) para o prompt."""

from __future__ import annotations

import base64

from hana_agent_oss.modules.attachments.extract import (
    extract_document_text,
    is_document_attachment,
    split_document_attachments,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _text_attachment(text: str, *, mime: str = "text/plain", name: str = "rel.txt") -> dict:
    return {"type": mime, "name": name, "data": f"data:{mime};base64,{_b64(text.encode())}"}


def test_plain_text_is_extracted():
    att = _text_attachment("Vendas subiram 20% no Q2.")
    assert extract_document_text(att) == "Vendas subiram 20% no Q2."


def test_image_is_not_a_document():
    img = {"type": "image/png", "name": "x.png", "data": "data:image/png;base64,AAAA"}
    assert is_document_attachment(img) is False
    assert extract_document_text(img) is None


def test_split_separates_docs_from_images():
    doc = _text_attachment("conteudo do anexo")
    img = {"type": "image/jpeg", "name": "foto.jpg", "data": "data:image/jpeg;base64,AAAA"}
    context, non_documents = split_document_attachments([doc, img])
    assert "conteudo do anexo" in context
    assert "[Anexo: rel.txt]" in context
    assert non_documents == [img]  # imagem segue pro caminho de visão


def test_bad_attachment_never_raises():
    broken = {"type": "application/pdf", "name": "x.pdf", "data": "not-base64!!"}
    assert extract_document_text(broken) is None


def test_oversized_doc_is_truncated():
    huge = _text_attachment("a" * 20000)
    out = extract_document_text(huge)
    assert out is not None and len(out) < 20000 and out.endswith("truncado ...]")
