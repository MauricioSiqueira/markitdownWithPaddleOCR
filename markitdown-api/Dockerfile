FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Configuração padrão do OCR (sobreposta via docker run -e ou docker-compose)
ENV OCR_ENABLED=true
ENV OCR_LANGUAGE=pt
ENV OCR_DPI=300
ENV OCR_MIN_TEXT_LENGTH=30
ENV OCR_MIN_IMAGE_RATIO=0.10
ENV OCR_PREPROCESSING=true

# Redis — sobrepor com a URL real via -e REDIS_URL=... ao rodar o container
ENV REDIS_URL=redis://redis:6379
ENV REDIS_TTL=86400

# Dependências de sistema:
#   libgl1, libglib2.0-0  → OpenCV (usado internamente pelo PaddleOCR)
#   libgomp1              → OpenMP runtime exigido pelo PaddlePaddle
#   build-essential       → compilação de extensões nativas
#   libpq-dev             → mantido da configuração original
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools && \
    # pyclipper: compila do fonte para evitar conflito de ABI do zlib nos wheels manylinux
    pip install --no-cache-dir --no-binary pyclipper pyclipper && \
    pip install --no-cache-dir -r requirements.txt

# Pré-baixa os modelos do PaddleOCR durante o build para evitar download em runtime.
# scipy é importado primeiro para garantir que seus Cython extensions sejam carregados
# antes do paddle carregar sua libz bundled (evita zlib.error -2 em arm64).
RUN python -c "import scipy, scipy.ndimage; from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='pt', show_log=False)"

COPY ./app ./app

# Cria usuário não-root e transfere ownership dos arquivos da aplicação
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
