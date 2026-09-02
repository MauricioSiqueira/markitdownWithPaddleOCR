"""
Serviço de OCR usando PaddleOCR.

Responsabilidades:
  - Singleton thread-safe do PaddleOCR (carregado uma única vez por processo).
  - Execução do OCR em uma imagem de página (arquivo PNG/JPEG).
  - Coleta de tokens de baixa confiança e padrões garbage para métricas de acertividade.
  - Reconstrução do layout: agrupa tokens em linhas e parágrafos, preservando
    a ordem de leitura (top → bottom, left → right) e detectando colunas básicas.

NOTA SOBRE IMPORTAÇÃO:
  scipy deve ser importado ANTES do paddle para evitar conflito de zlib bundled.
  paddlepaddle carrega sua própria libz.so em memória; se scipy for importado
  depois, o Cython extension _ccallback_c usa a libz errada → zlib.error -2.
  Importamos scipy dentro de _get_ocr(), imediatamente antes do PaddleOCR,
  garantindo a ordem correta sem penalizar o tempo de startup da aplicação.
"""
import logging
import re
import threading
from typing import Dict, List, Optional, Tuple

import cv2

from app.config import settings

logger = logging.getLogger(__name__)

_ocr_lock = threading.Lock()
_ocr: Optional[object] = None

# Detecta strings compostas apenas por caracteres não alfanuméricos (ex: "@#$|///")
_GARBAGE_RE = re.compile(r'^[^a-zA-ZÀ-ÿ0-9\s]{2,}$')


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def _get_ocr():
    """Inicializa PaddleOCR de forma lazy e thread-safe (double-checked locking)."""
    global _ocr
    if _ocr is None:
        with _ocr_lock:
            if _ocr is None:
                # scipy DEVE ser importado antes do paddle (veja docstring do módulo)
                import scipy          # noqa: F401
                import scipy.ndimage  # noqa: F401

                from paddleocr import PaddleOCR

                logger.info("Inicializando PaddleOCR (lang=%s)...", settings.OCR_LANGUAGE)
                _ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=settings.OCR_LANGUAGE,
                    show_log=False,
                )
                logger.info("PaddleOCR inicializado com sucesso.")
    return _ocr


# ---------------------------------------------------------------------------
# Processamento de página
# ---------------------------------------------------------------------------


def process_page_image(image_path: str, page_num: int = 0) -> Tuple[str, List[Dict]]:
    """
    Executa OCR em uma imagem de página e retorna (texto, itens_de_ruído).

    Args:
        image_path: caminho para o arquivo PNG/JPEG da página renderizada.
        page_num: número da página (1-based), incluído nos registros de ruído.

    Returns:
        Tupla (texto_extraído, lista_de_ruído).
        Cada item de ruído: {"page": int, "text": str, "confidence": float, "reason": str}
    """
    from app.services.image_preprocessor import preprocess_for_ocr

    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        logger.error("Não foi possível carregar imagem: %s", image_path)
        return "", []

    if settings.OCR_PREPROCESSING:
        img_bgr = preprocess_for_ocr(img_bgr)

    ocr = _get_ocr()
    # Lock garante inferência serial — PaddleOCR não é thread-safe (ESC-03)
    with _ocr_lock:
        result = ocr.ocr(img_bgr, cls=True)

    if not result or not result[0]:
        return "", []

    return reconstruct_layout(result[0], page_num=page_num)


# ---------------------------------------------------------------------------
# Reconstrução de layout
# ---------------------------------------------------------------------------


def reconstruct_layout(ocr_lines: List, page_num: int = 0) -> Tuple[str, List[Dict]]:
    """
    Reconstrói o layout de leitura e coleta tokens de baixa confiança/garbage.

    Formato de entrada (por linha detectada):
        [ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (texto, confiança) ]

    Returns:
        (texto_reconstruído, lista_de_ruído)
    """
    blocks, noise_items = _extract_blocks(ocr_lines, page_num=page_num)
    if not blocks:
        return "", noise_items

    avg_height = _avg_height(blocks)
    blocks.sort(key=lambda b: b["y_center"])
    lines = _group_into_lines(blocks, avg_height)
    lines = _handle_columns(lines, avg_height)
    paragraphs = _group_into_paragraphs(lines, avg_height)

    return _render_paragraphs(paragraphs), noise_items


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _extract_blocks(ocr_lines: List, page_num: int = 0) -> Tuple[List[Dict], List[Dict]]:
    """
    Converte saída bruta do PaddleOCR em blocos posicionais.
    Separa tokens de baixa confiança e padrões garbage nos noise_items.
    """
    blocks: List[Dict] = []
    noise_items: List[Dict] = []
    threshold = settings.OCR_CONFIDENCE_THRESHOLD

    for item in ocr_lines:
        if not item or len(item) < 2 or not item[1]:
            continue
        bbox = item[0]
        text_info = item[1]
        if not text_info or not text_info[0]:
            continue

        text = text_info[0].strip()
        confidence = float(text_info[1]) if len(text_info) > 1 else 1.0

        if not text:
            continue

        # Classifica como ruído antes de adicionar ao layout
        is_garbage = bool(_GARBAGE_RE.match(text))
        is_low_conf = confidence < threshold

        if is_garbage:
            noise_items.append({
                "page": page_num,
                "text": text,
                "confidence": round(confidence, 4),
                "reason": "garbage_pattern",
            })
            continue  # não inclui no texto final

        if is_low_conf:
            noise_items.append({
                "page": page_num,
                "text": text,
                "confidence": round(confidence, 4),
                "reason": "low_confidence",
            })
            # inclui no texto mesmo assim, mas registra para métrica

        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        y_top = min(ys)
        y_bottom = max(ys)

        blocks.append({
            "text": text,
            "x_left": min(xs),
            "x_right": max(xs),
            "y_top": y_top,
            "y_bottom": y_bottom,
            "y_center": (y_top + y_bottom) / 2,
            "height": y_bottom - y_top,
        })

    return blocks, noise_items


def _avg_height(blocks: List[Dict]) -> float:
    heights = [b["height"] for b in blocks if b["height"] > 0]
    if not heights:
        return 20.0
    return sum(heights) / len(heights)


def _group_into_lines(blocks: List[Dict], avg_height: float) -> List[List[Dict]]:
    if not blocks:
        return []

    threshold = avg_height * 0.6
    lines: List[List[Dict]] = []
    current: List[Dict] = [blocks[0]]

    for block in blocks[1:]:
        line_y_center = sum(b["y_center"] for b in current) / len(current)
        if abs(block["y_center"] - line_y_center) <= threshold:
            current.append(block)
        else:
            lines.append(sorted(current, key=lambda b: b["x_left"]))
            current = [block]

    lines.append(sorted(current, key=lambda b: b["x_left"]))
    return lines


def _handle_columns(lines: List[List[Dict]], avg_height: float) -> List[List[Dict]]:
    if len(lines) < 4:
        return lines

    all_x_right = [b["x_right"] for line in lines for b in line]
    all_x_left = [b["x_left"] for line in lines for b in line]
    if not all_x_right or not all_x_left:
        return lines

    page_width = max(all_x_right) - min(all_x_left)
    if page_width <= 0:
        return lines

    col_gap_threshold = page_width * 0.15
    two_col_count = 0
    for line in lines:
        if len(line) < 2:
            continue
        for i in range(len(line) - 1):
            gap = line[i + 1]["x_left"] - line[i]["x_right"]
            if gap > col_gap_threshold:
                two_col_count += 1
                break

    multi_block_lines = sum(1 for l in lines if len(l) > 1)
    if multi_block_lines == 0 or (two_col_count / multi_block_lines) < 0.4:
        return lines

    logger.debug("Layout de duas colunas detectado.")
    midpoint = min(all_x_left) + page_width / 2

    left_col_lines: List[List[Dict]] = []
    right_col_lines: List[List[Dict]] = []

    for line in lines:
        left_blocks = [b for b in line if b["x_left"] < midpoint]
        right_blocks = [b for b in line if b["x_left"] >= midpoint]
        if left_blocks:
            left_col_lines.append(left_blocks)
        if right_blocks:
            right_col_lines.append(right_blocks)

    return left_col_lines + right_col_lines


def _group_into_paragraphs(
    lines: List[List[Dict]], avg_height: float
) -> List[List[List[Dict]]]:
    if not lines:
        return []

    para_gap = avg_height * 1.5
    paragraphs: List[List[List[Dict]]] = []
    current_para: List[List[Dict]] = [lines[0]]

    for i in range(1, len(lines)):
        prev_y_bottom = max(b["y_bottom"] for b in lines[i - 1])
        curr_y_top = min(b["y_top"] for b in lines[i])
        gap = curr_y_top - prev_y_bottom

        if gap > para_gap:
            paragraphs.append(current_para)
            current_para = [lines[i]]
        else:
            current_para.append(lines[i])

    paragraphs.append(current_para)
    return paragraphs


def _render_paragraphs(paragraphs: List[List[List[Dict]]]) -> str:
    rendered = []
    for para in paragraphs:
        lines_text = []
        for line in para:
            lines_text.append(" ".join(b["text"] for b in line))
        rendered.append("\n".join(lines_text))
    return "\n\n".join(rendered)
