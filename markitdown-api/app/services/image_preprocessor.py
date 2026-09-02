"""
Pré-processamento de imagem para maximizar a qualidade do OCR.

Otimizado para documentos jurídicos brasileiros digitalizados:
  - scans com iluminação irregular ou amarelados
  - páginas levemente inclinadas (deskew)
  - documentos com fundo texturizado (carimbos, guilloche de identidade)
  - documentos com texto colorido sobre fundo colorido

Pipeline:
  1. Melhor canal de cor    (seleciona o canal BGR com mais contraste)
  2. Gamma adaptativo       (corrige sub/super exposição)
  3. Top-hat morfológico    (remove fundos texturizados, isola texto)
  4. CLAHE                  (contraste local adaptativo)
  5. Denoising              (reduz ruído sem borrar bordas)
  6. Deskew                 (corrige inclinação de até ±15°)
  7. Sharpening             (realça bordas de caracteres)
  8. Fechamento morfológico (reconecta traços quebrados)
  9. Retorno BGR            (formato esperado pelo PaddleOCR)

LIMITAÇÕES CONHECIDAS:
  - Assinaturas manuscritas: requerem modelo HTR (Handwritten Text Recognition)
    dedicado — nenhum preprocessamento resolve no PaddleOCR.
  - Texto curvado em carimbos circulares: requer detecção + unwrap de texto
    curvo, o que está fora do escopo deste pipeline.
"""
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_DESKEW_MIN_ANGLE_DEG = 0.5

# Tamanho do kernel top-hat: controla o que é considerado "fundo".
# 40px a 400 DPI ≈ ~2.5 mm — maior que qualquer caractere, menor que padrões
# de fundo (guilloche, malha de segurança de documentos de identidade).
_TOPHAT_KERNEL_SIZE = 40


def preprocess_for_ocr(img_bgr: np.ndarray) -> np.ndarray:
    """
    Aplica pipeline completo de pré-processamento.
    Entrada/saída: imagem BGR (formato nativo do OpenCV).
    """
    try:
        gray = _best_channel(img_bgr)
        gray = _gamma_correction(gray)
        gray = _tophat_background_removal(gray)
        gray = _clahe(gray)
        gray = _denoise(gray)
        gray = _deskew(gray)
        gray = _sharpen(gray)
        gray = _morph_close(gray)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    except Exception as exc:
        logger.warning("Erro no pré-processamento; usando imagem original. %s", exc)
        return img_bgr


# ---------------------------------------------------------------------------
# Etapas individuais
# ---------------------------------------------------------------------------


def _best_channel(img: np.ndarray) -> np.ndarray:
    """
    Seleciona o canal BGR com maior contraste (desvio padrão).

    Em documentos coloridos (carteira de identidade azul, formulários rosas,
    carimbos vermelhos) o canal com maior stddev separa melhor o texto do fundo
    do que a conversão padrão BGR→gray (que é uma média ponderada fixa).
    """
    if img.ndim == 2:
        return img.copy()
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    channels = cv2.split(img)
    stds = [float(np.std(c)) for c in channels]
    best = int(np.argmax(stds))

    if max(stds) - min(stds) < 5.0:
        # Canais muito similares → usa conversão padrão BGR2GRAY
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    logger.debug("Canal selecionado: %d (stds: %s)", best, [f'{s:.1f}' for s in stds])
    return channels[best]


def _gamma_correction(gray: np.ndarray) -> np.ndarray:
    """
    Gamma adaptativo baseado na luminosidade média.
    Scans escuros recebem gamma < 1 (clareia); lavados recebem gamma > 1.
    """
    mean = float(np.mean(gray))
    if mean < 50:
        gamma = 0.5
    elif mean < 100:
        gamma = 0.7
    elif mean < 150:
        gamma = 0.85
    elif mean > 220:
        gamma = 1.3
    else:
        return gray

    lut = np.array(
        [min(255, int((i / 255.0) ** gamma * 255)) for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(gray, lut)


def _tophat_background_removal(gray: np.ndarray) -> np.ndarray:
    """
    Top-hat morfológico: preserva apenas objetos menores que o kernel
    (letras, traços) e remove o fundo texturizado (guilloche, malhas de
    segurança, padrões periódicos de carimbos).

    Funciona porque o top-hat = imagem − erosão_dilatada, que efetivamente
    subtrai variações de longa frequência (fundo) e mantém as de alta
    frequência (bordas de caracteres).
    """
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (_TOPHAT_KERNEL_SIZE, _TOPHAT_KERNEL_SIZE)
    )
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    # Normaliza para usar a faixa completa de 0-255
    _, tophat = cv2.threshold(tophat, 10, 255, cv2.THRESH_TOZERO)
    tophat_norm = cv2.normalize(tophat, None, 0, 255, cv2.NORM_MINMAX)

    # Combina 60% original + 40% top-hat para não perder contexto de
    # caracteres que tenham baixo contraste com o fundo
    combined = cv2.addWeighted(gray, 0.6, tophat_norm.astype(np.uint8), 0.4, 0)
    return combined


def _clahe(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(4, 4))
    return clahe.apply(gray)


def _denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """
    Detecta e corrige inclinação usando HoughLinesP nas linhas de texto.
    """
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=gray.shape[1] // 5,
        maxLineGap=20,
    )

    if lines is None:
        return gray

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if -15 < angle < 15:
            angles.append(angle)

    if not angles:
        return gray

    median_angle = float(np.median(angles))
    if abs(median_angle) < _DESKEW_MIN_ANGLE_DEG:
        return gray

    logger.debug("Deskew: corrigindo %.2f°", median_angle)
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _sharpen(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    sharpened = cv2.addWeighted(gray, 1.8, blurred, -0.8, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def _morph_close(gray: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1))
    return cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
