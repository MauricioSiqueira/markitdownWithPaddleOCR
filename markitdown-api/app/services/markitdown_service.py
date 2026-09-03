"""
Serviço principal de conversão de documentos.

Divide responsabilidades em duas etapas:
  1. prepare_from_uri()  — baixa, valida e persiste o arquivo em disco (síncrona com o request)
  2. process_document()  — converte para Markdown em thread pool (executada em background)

Formatos suportados: .pdf, .docx, .pptx, .xlsx, .xls
"""
import asyncio
import logging
import os
import tempfile
from urllib.parse import urlparse

import httpx
import magic
from fastapi import HTTPException
from markitdown import MarkItDown

from app.config import settings
from app.services.pdf_processor import process_pdf

logger = logging.getLogger(__name__)

_md = MarkItDown(enable_plugins=False)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
CHUNK_SIZE = 1 * 1024 * 1024       # 1 MB por chunk

_ALLOWED_MIMES: dict[str, set[str]] = {
    ".pdf":  {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".xls":  {"application/vnd.ms-excel"},
}


def _validate_mime(ext: str, content: bytes) -> bool:
    detected = magic.from_buffer(content[:2048], mime=True)
    return detected in _ALLOWED_MIMES.get(ext, set())


def _ext_from_uri(uri: str) -> str:
    """Extrai a extensão do path da URI, ignorando query string."""
    path = urlparse(uri).path
    return os.path.splitext(path)[1].lower()


async def prepare_from_uri(uri: str) -> tuple[str, str]:
    """
    Baixa o arquivo da URI, valida (extensão + MIME) e salva em disco.
    Retorna (temp_path, ext).
    O chamador é responsável por remover temp_path após o processamento.
    """
    ext = _ext_from_uri(uri)

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado: '{ext}'. Formatos permitidos: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    chunks: list[bytes] = []
    total = 0

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", uri) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Não foi possível baixar o arquivo da URI (HTTP {response.status_code}).",
                    )
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    total += len(chunk)
                    if total > MAX_FILE_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail="O arquivo excedeu o limite de tamanho permitido (500 MB).",
                        )
                    chunks.append(chunk)
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao acessar a URI: {exc}",
        )

    content = b"".join(chunks)

    if not _validate_mime(ext, content):
        raise HTTPException(
            status_code=400,
            detail="O conteúdo do arquivo não corresponde ao formato declarado pela URI.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        temp_path = tmp.name

    logger.info("Arquivo baixado e salvo temporariamente: ext=%s tamanho=%dB", ext, total)
    return temp_path, ext


async def process_document(temp_path: str, ext: str) -> list:
    """
    Converte o documento para Markdown em thread pool (não bloqueia o event loop).
    Aplica timeout configurável via PROCESSING_TIMEOUT (padrão: 300s).

    Returns:
        Lista de dicts por página: [{"page": 1, "markitdown": "...", "noises": [...]}, ...]
        Formatos não-PDF retornam lista com uma única entrada (page=1, noises=[]).
    """
    try:
        async with asyncio.timeout(settings.PROCESSING_TIMEOUT):
            if ext == ".pdf":
                return await asyncio.to_thread(process_pdf, temp_path)
            else:
                result = await asyncio.to_thread(_md.convert, temp_path)
                text = (result.text_content or "").strip()
                return [{"page": 1, "markitdown": text, "noises": []}]
    except TimeoutError:
        logger.error("Timeout ao processar documento (limite: %ds)", settings.PROCESSING_TIMEOUT)
        raise Exception(f"Timeout: processamento excedeu {settings.PROCESSING_TIMEOUT}s.")
    except Exception as exc:
        logger.error("Erro ao processar documento: %s", exc)
        raise
