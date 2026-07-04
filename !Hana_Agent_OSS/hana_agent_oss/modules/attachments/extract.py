"""Extração de TEXTO de anexos de documento (texto puro e PDF).

Ponto único usado por TODOS os canais (chat, Discord, voz): o backend recebe um
anexo, e se ele for um documento (não-imagem) vira texto injetado no prompt. Imagem
continua indo como visão pelo caminho normal — nunca passa por aqui.

Fácil de estender: pra suportar um formato novo (docx, etc.), basta tratar o mime
em ``extract_document_text``; nenhum canal precisa mudar.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Documentos que viram TEXTO pro modelo ler.
_TEXT_MIME_EXACT = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
    "application/csv",
}
_PDF_MIME = "application/pdf"

# Teto por documento. O chat ainda trunca o TOTAL do prompt depois (12k), então
# isto é só pra um único anexo gigante não dominar o contexto sozinho.
MAX_DOC_CHARS = 12000


def is_document_attachment(attachment: dict[str, Any]) -> bool:
    """True para anexos de texto/PDF. Imagem e tipos desconhecidos: False."""
    mime = str(attachment.get("type") or "").lower()
    if mime.startswith("image/"):
        return False
    return mime.startswith("text/") or mime in _TEXT_MIME_EXACT or mime == _PDF_MIME


def _read_bytes(attachment: dict[str, Any]) -> bytes | None:
    """Lê os bytes do anexo, do arquivo salvo (``path``) ou do base64 (``data``)."""
    path = str(attachment.get("path") or "")
    if path:
        try:
            return Path(path).read_bytes()
        except OSError:
            logger.warning("Falha ao ler anexo do disco: %s", path, exc_info=True)
            return None
    raw = str(attachment.get("data") or "")
    if not raw:
        return None
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw)
    except (ValueError, TypeError):
        return None


def _extract_pdf(data: bytes) -> str:
    """Extrai texto de um PDF com pypdf (dependência já presente no ambiente)."""
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_document_text(attachment: dict[str, Any]) -> str | None:
    """Texto de um anexo de documento. None se não for doc ou não der pra ler.

    Nunca levanta: qualquer falha vira None pra um anexo ruim não quebrar o turno.
    """
    if not is_document_attachment(attachment):
        return None
    data = _read_bytes(attachment)
    if not data:
        return None
    mime = str(attachment.get("type") or "").lower()
    try:
        text = _extract_pdf(data) if mime == _PDF_MIME else data.decode("utf-8", errors="replace")
    except Exception:
        logger.warning("Falha ao extrair texto do anexo %s", attachment.get("name"), exc_info=True)
        return None
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > MAX_DOC_CHARS:
        text = text[:MAX_DOC_CHARS].rstrip() + "\n[... documento truncado ...]"
    return text


def split_document_attachments(
    attachments: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Separa documentos de imagens.

    Devolve ``(contexto, sem_documentos)``: o bloco de texto pronto pra concatenar
    no prompt e a lista de anexos SEM os documentos (só o que o provider trata como
    visão). Assim o provider nunca recebe um PDF e erra ``attachment_type_not_supported``.
    """
    context_blocks: list[str] = []
    non_documents: list[dict[str, Any]] = []
    for attachment in attachments or []:
        if not is_document_attachment(attachment):
            non_documents.append(attachment)
            continue
        extracted = extract_document_text(attachment)
        if extracted:
            name = str(attachment.get("name") or "documento")
            context_blocks.append(f"[Anexo: {name}]\n{extracted}")
    return "\n\n".join(context_blocks), non_documents
