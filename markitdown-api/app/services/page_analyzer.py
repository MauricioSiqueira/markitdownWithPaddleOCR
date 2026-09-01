"""
Analisa cada página de um PDF para decidir o mecanismo de extração.

Decisão por página (não por documento):
  - texto extraível suficiente  → MarkItDown
  - poucos chars + imagem       → PaddleOCR
  - sem nada (página em branco) → MarkItDown (retornará vazio)
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def analyze_page(page) -> Tuple[int, float]:
    """
    Analisa uma página PyMuPDF e retorna métricas de conteúdo.

    Returns:
        (char_count, image_ratio):
            char_count   — número de caracteres de texto extraível
            image_ratio  — proporção [0-1] da área da página coberta por imagens
    """
    # --- texto extraível ---
    text = page.get_text("text")
    char_count = len(text.strip())

    # --- área de imagens ---
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return char_count, 0.0

    image_area = _estimate_image_area(page, page_area)
    image_ratio = min(image_area / page_area, 1.0)

    logger.debug(
        f"Análise de página: {char_count} chars, "
        f"cobertura de imagem {image_ratio:.1%}"
    )
    return char_count, image_ratio


def _estimate_image_area(page, page_area: float) -> float:
    """
    Estima a área ocupada por imagens na página.

    Estratégia:
      1. Verifica blocos de imagem via get_text("blocks") — captura posição real.
      2. Se não encontrar blocos de imagem mas a página tiver XObjects de imagem,
         usa estimativa conservadora de 50 % da área.
    """
    try:
        blocks = page.get_text("blocks")
        image_blocks = [b for b in blocks if b[6] == 1]  # type 1 == image
        if image_blocks:
            return sum((b[2] - b[0]) * (b[3] - b[1]) for b in image_blocks)
    except Exception as exc:
        logger.debug(f"get_text('blocks') falhou: {exc}")

    # Fallback: usa get_images para detectar presença
    try:
        images = page.get_images(full=True)
        if images:
            # Não temos posição exata; assume 50 % da área como estimativa conservadora
            return page_area * 0.5
    except Exception as exc:
        logger.debug(f"get_images() falhou: {exc}")

    return 0.0


def should_use_ocr(
    page,
    min_text_length: int = 30,
    min_image_ratio: float = 0.10,
) -> bool:
    """
    Retorna True se a página deve ser processada por PaddleOCR.

    Regras:
      1. Texto suficiente (>= min_text_length chars) → MarkItDown (sem OCR).
      2. Poucos chars + imagem significativa (>= min_image_ratio) → OCR.
      3. Sem texto E sem imagem (página em branco) → MarkItDown.

    Exemplos:
      0 chars + 80 % imagem  → OCR
      15 chars + 70 % imagem → OCR
      50 chars + 60 % imagem → MarkItDown  (texto suficiente)
      0 chars + 2 % imagem   → MarkItDown  (provavelmente em branco)
    """
    char_count, image_ratio = analyze_page(page)

    if char_count >= min_text_length:
        logger.debug(f"Página com texto suficiente ({char_count} chars) → MarkItDown")
        return False

    if image_ratio >= min_image_ratio:
        logger.debug(
            f"Página com poucos chars ({char_count}) "
            f"+ imagem significativa ({image_ratio:.1%}) → OCR"
        )
        return True

    logger.debug(
        f"Página sem texto suficiente e sem imagem significativa "
        f"({char_count} chars, {image_ratio:.1%} imagem) → MarkItDown"
    )
    return False
