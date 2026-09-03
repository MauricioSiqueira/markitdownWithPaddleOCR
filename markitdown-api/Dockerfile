FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools && \
    # pyclipper: compila do fonte para evitar conflito de ABI do zlib nos wheels manylinux
    pip install --no-cache-dir --no-binary pyclipper pyclipper && \
    pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

# Cria usuário não-root e transfere ownership dos arquivos da aplicação
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Pré-baixa os modelos do PaddleOCR como appuser — os modelos ficam em
# /home/appuser/.paddleocr/, que é exatamente onde o runtime vai procurar.
# scipy é importado primeiro para garantir a ordem correta de carregamento do zlib.
RUN python -c "import scipy, scipy.ndimage; from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='pt', show_log=False)"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
