import os


class Settings:
    OCR_ENABLED: bool = os.getenv("OCR_ENABLED", "true").lower() == "true"
    OCR_LANGUAGE: str = os.getenv("OCR_LANGUAGE", "pt")
    OCR_DPI: int = int(os.getenv("OCR_DPI", "300"))
    OCR_MIN_TEXT_LENGTH: int = int(os.getenv("OCR_MIN_TEXT_LENGTH", "30"))
    OCR_MIN_IMAGE_RATIO: float = float(os.getenv("OCR_MIN_IMAGE_RATIO", "0.10"))
    OCR_PREPROCESSING: bool = os.getenv("OCR_PREPROCESSING", "true").lower() == "true"

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379")
    # TTL em segundos: padrão 24 horas
    REDIS_TTL: int = int(os.getenv("REDIS_TTL", "86400"))

    # Limite de páginas processadas por documento (ESC-08)
    OCR_MAX_PAGES: int = int(os.getenv("OCR_MAX_PAGES", "100"))

    # Timeout em segundos para processamento de um documento (ESC-05)
    PROCESSING_TIMEOUT: int = int(os.getenv("PROCESSING_TIMEOUT", "300"))


settings = Settings()
