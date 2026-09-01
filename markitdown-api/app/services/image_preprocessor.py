"""
Pré-processamento de imagem para melhorar a qualidade do OCR.

Otimizado para documentos administrativos e jurídicos brasileiros:
portarias, ofícios, leis, contratos, memorandos — incluindo scans antigos
com papel amarelado, baixo contraste ou leve inclinação.
"""
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def preprocess_for_ocr(img_bgr: np.ndarray) -> np.ndarray:
    """
    Aplica pipeline de pré-processamento para maximizar a qualidade do OCR.

    Entrada/saída: imagem BGR (formato nativo do OpenCV).

    Pipeline (moderado — sem transformações que destruam caracteres):
      1. Grayscale
      2. Redução de ruído (fast NL means)
      3. Melhoria de contraste adaptativa (CLAHE)
      4. Nitidez leve (unsharp mask)
      5. Retorna como BGR para compatibilidade com PaddleOCR via OpenCV
    """
    try:
        # 1. Grayscale
        if img_bgr.ndim == 3 and img_bgr.shape[2] in (3, 4):
            code = cv2.COLOR_BGR2GRAY if img_bgr.shape[2] == 3 else cv2.COLOR_BGRA2GRAY
            gray = cv2.cvtColor(img_bgr, code)
        else:
            gray = img_bgr.copy()

        # 2. Redução de ruído — preserva bordas de caracteres
        # h=8 é conservador; valores maiores suavizam demais
        denoised = cv2.fastNlMeansDenoising(
            gray, h=8, templateWindowSize=7, searchWindowSize=21
        )

        # 3. Contraste adaptativo (CLAHE)
        # Funciona bem com documentos amarelados e scans com iluminação irregular
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 4. Nitidez suave (unsharp mask com kernel 3x3)
        # Evitamos kernels agressivos que criam artefatos nos caracteres
        blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
        sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
        sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

        # 5. Retorna como BGR (3 canais) — padrão esperado pelo PaddleOCR via cv2
        result = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)
        return result

    except Exception as exc:
        logger.warning(
            f"Erro no pré-processamento de imagem; usando imagem original. Detalhe: {exc}"
        )
        return img_bgr
