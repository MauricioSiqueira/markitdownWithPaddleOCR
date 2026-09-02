"""
Serviço principal de conversão de documentos.

Divide responsabilidades em duas etapas:
  1. prepare_upload()   — lê, valida e persiste o arquivo em disco (síncrona com o request)
  2. process_document() — converte para Markdown em thread pool (executada em background)

Formatos suportados: .pdf, .docx, .pptx, .xlsx, .xls
"""
import asyncio
import logging
import os
import tempfile

import magic
from fastapi import HTTPException, UploadFile
from markitdown import MarkItDown

from app.config import settings
from app.services.pdf_processor import process_pdf

logger = logging.getLogger(__name__)

# Instância compartilhada para formatos não-PDF (ESC-09)
_md = MarkItDown(enable_plugins=False)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
CHUNK_SIZE = 1 * 1024 * 1024       # lê 1 MB por vez

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


async def _read_chunked(file: UploadFile) -> bytes:
    """Lê o arquivo em chunks de 1 MB, rejeitando imediatamente se exceder 500 MB."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="O arquivo excedeu o limite de tamanho permitido (500 MB).",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def prepare_upload(file: UploadFile) -> tuple[str, str]:
    """
    Valida e salva o arquivo em disco. Retorna (temp_path, ext).
    Deve ser chamado dentro do contexto do request (antes de retornar a resposta).
    O chamador é responsável por remover temp_path após o processamento.
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado: {ext}. Formatos permitidos: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await _read_chunked(file)

    if not _validate_mime(ext, content):
        raise HTTPException(
            status_code=400,
            detail="O conteúdo do arquivo não corresponde ao formato declarado.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        temp_path = tmp.name

    safe_name = filename.replace("\n", "").replace("\r", "")[:255]
    logger.info("Arquivo validado e salvo temporariamente: %s", safe_name)

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
