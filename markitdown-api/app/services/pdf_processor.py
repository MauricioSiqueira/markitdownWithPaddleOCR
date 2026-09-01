"""
Processa PDFs página por página.

Para cada página:
  1. Analisa o conteúdo (page_analyzer.should_use_ocr).
  2. Se a página tem texto nativo suficiente → extrai como PDF de página única
     e processa com MarkItDown.
  3. Se a página é um scan → renderiza como imagem e processa com PaddleOCR.
  4. Junta os resultados em ordem (markdown_builder.assemble_pages).

MarkItDown é instanciado uma única vez (_md_pdf) e reutilizado por todas as
páginas para evitar overhead de inicialização.
"""
import logging
import os
import tempfile

import fitz  # PyMuPDF
from markitdown import MarkItDown

from app.config import settings
from app.services.markdown_builder import assemble_pages
from app.services.ocr_service import process_page_image
from app.services.page_analyzer import should_use_ocr

logger = logging.getLogger(__name__)

# Instância reutilizável de MarkItDown para páginas com texto nativo
_md_pdf = MarkItDown(enable_plugins=False)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def process_pdf(pdf_path: str) -> str:
    """
    Processa um arquivo PDF página por página e retorna Markdown.

    Args:
        pdf_path: caminho para o PDF no disco.

    Returns:
        Texto Markdown com o conteúdo completo do documento.

    Raises:
        Exception: propaga erros de abertura do PDF; erros individuais de página
                   são registrados mas não interrompem o processamento.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.error("Erro ao abrir PDF %s: %s", pdf_path, exc)
        raise

    total_pages = len(doc)

    if total_pages == 0:
        logger.warning("PDF não contém páginas: %s", pdf_path)
        doc.close()
        return ""

    page_count = min(total_pages, settings.OCR_MAX_PAGES)
    if total_pages > settings.OCR_MAX_PAGES:
        logger.warning(
            "PDF com %d páginas excede o limite de %d. Processando apenas as primeiras %d.",
            total_pages, settings.OCR_MAX_PAGES, page_count,
        )

    logger.info("PDF com %d página(s). Iniciando processamento por página.", page_count)
    page_results = []

    try:
        for page_num in range(page_count):
            page = doc[page_num]
            label = f"Página {page_num + 1}/{page_count}"

            use_ocr = settings.OCR_ENABLED and should_use_ocr(
                page,
                min_text_length=settings.OCR_MIN_TEXT_LENGTH,
                min_image_ratio=settings.OCR_MIN_IMAGE_RATIO,
            )

            if use_ocr:
                logger.info("%s → OCR (PaddleOCR)", label)
                text = _process_page_with_ocr(page, page_num)
            else:
                logger.info("%s → texto nativo (MarkItDown)", label)
                text = _process_page_with_markitdown(doc, page_num)

            page_results.append(text)

    finally:
        doc.close()

    return assemble_pages(page_results)


# ---------------------------------------------------------------------------
# Processamento individual de página
# ---------------------------------------------------------------------------


def _process_page_with_markitdown(doc: fitz.Document, page_num: int) -> str:
    """
    Extrai uma página como PDF temporário de página única e processa com MarkItDown.

    Fallback: se MarkItDown falhar, extrai texto diretamente com PyMuPDF.
    """
    temp_path = None
    page_doc = None
    try:
        page_doc = fitz.open()
        page_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            temp_path = tmp.name
            page_doc.save(temp_path)

        result = _md_pdf.convert(temp_path)
        return (result.text_content or "").strip()

    except Exception as exc:
        logger.error(
            "Erro ao processar página %d com MarkItDown: %s. "
            "Tentando extração direta.",
            page_num + 1,
            exc,
        )
        try:
            return doc[page_num].get_text("text").strip()
        except Exception:
            return ""
    finally:
        if page_doc is not None:
            try:
                page_doc.close()
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as exc:
                logger.error("Erro ao remover PDF temporário %s: %s", temp_path, exc)


def _process_page_with_ocr(page: fitz.Page, page_num: int) -> str:
    """
    Renderiza a página em alta resolução e executa PaddleOCR.

    A resolução é controlada pela variável de ambiente OCR_DPI (padrão: 300).
    A imagem temporária é removida imediatamente após o OCR.
    """
    img_temp_path = None
    try:
        scale = settings.OCR_DPI / 72.0
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            img_temp_path = tmp.name
            pix.save(img_temp_path)

        del pix  # libera memória antes do OCR

        return process_page_image(img_temp_path)

    except Exception as exc:
        logger.error("Erro ao processar página %d com OCR: %s", page_num + 1, exc)
        return ""
    finally:
        if img_temp_path and os.path.exists(img_temp_path):
            try:
                os.remove(img_temp_path)
            except OSError as exc:
                logger.error(
                    "Erro ao remover imagem temporária %s: %s", img_temp_path, exc
                )
