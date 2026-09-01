"""
Serviço principal de conversão de documentos.

Roteia o arquivo recebido:
  - PDF  → pdf_processor.process_pdf (processamento página por página)
  - Outros formatos (.docx, .pptx, .xlsx, .xls) → MarkItDown diretamente
"""
import logging
import os
import tempfile

import magic
from fastapi import HTTPException, UploadFile
from markitdown import MarkItDown

from app.services.pdf_processor import process_pdf

logger = logging.getLogger(__name__)

# Instância reutilizável para formatos não-PDF
_md = MarkItDown(enable_plugins=False)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".xls"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# MIME types permitidos por extensão — validados pelo python-magic
_ALLOWED_MIMES: dict[str, set[str]] = {
    ".pdf":  {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".xls":  {"application/vnd.ms-excel"},
}


def _validate_mime(ext: str, content: bytes) -> bool:
    """Detecta o MIME type real do conteúdo via python-magic e valida contra o esperado."""
    detected = magic.from_buffer(content[:2048], mime=True)
    return detected in _ALLOWED_MIMES.get(ext, set())


async def convert_file_to_markdown(file: UploadFile) -> str:
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado: {ext}. Formatos permitidos: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    temp_path = None
    try:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail="O arquivo excedeu o limite de tamanho permitido (50 MB).",
            )

        if not _validate_mime(ext, content):
            raise HTTPException(
                status_code=400,
                detail="O conteúdo do arquivo não corresponde ao formato declarado.",
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        logger.info("Processando arquivo: %s", filename)

        try:
            if ext == ".pdf":
                return process_pdf(temp_path)
            else:
                result = _md.convert(temp_path)
                return (result.text_content or "").strip()
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Erro ao converter arquivo %s: %s", filename, exc)
            raise HTTPException(
                status_code=500,
                detail="Ocorreu um erro interno ao processar a conversão do documento.",
            )

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as exc:
                logger.error("Erro ao remover arquivo temporário %s: %s", temp_path, exc)
