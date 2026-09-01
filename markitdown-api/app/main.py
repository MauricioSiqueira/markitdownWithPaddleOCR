import logging
import os
import time
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import verify_api_key
from app.services.markitdown_service import prepare_upload, process_document
from app.services.metrics import (
    document_processing_seconds,
    documents_completed_total,
    documents_in_progress,
    documents_submitted_total,
    http_request_duration_seconds,
    http_requests_total,
)
from app.services.redis_service import get_markdown, get_status, save_markdown, save_status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware de métricas HTTP (ESC-10)
# ---------------------------------------------------------------------------


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Normaliza path para evitar cardinalidade infinita (ex.: /result/{id})
        path = request.url.path
        if path.startswith("/result/"):
            path = "/result/{doc_id}"

        http_requests_total.labels(
            method=request.method,
            endpoint=path,
            status_code=str(response.status_code),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=path,
        ).observe(duration)

        return response


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="MarkItDown API",
    version="2.0.0",
    description="Converte documentos (PDF, DOCX, PPTX, XLSX, XLS) para Markdown com suporte a OCR.",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(PrometheusMiddleware)


# ---------------------------------------------------------------------------
# Background task (ESC-01, ESC-02, ESC-05, ESC-06, ESC-10)
# ---------------------------------------------------------------------------


async def _process_and_store(doc_id: str, temp_path: str, ext: str) -> None:
    """
    Executa em background: converte o documento e persiste no Redis.
    Garante remoção do arquivo temporário em qualquer cenário (ESC-06).
    Instrumenta métricas de duração e documentos em progresso (ESC-10).
    """
    documents_in_progress.inc()
    start = time.perf_counter()
    try:
        markdown = await process_document(temp_path, ext)
        await save_markdown(doc_id, markdown)
        await save_status(doc_id, "done")
        documents_completed_total.labels(status="done", ext=ext).inc()
        logger.info("Processamento concluído: id=%s", doc_id)
    except Exception as exc:
        logger.error("Erro ao processar documento id=%s: %s", doc_id, exc)
        await save_status(doc_id, "error")
        documents_completed_total.labels(status="error", ext=ext).inc()
    finally:
        duration = time.perf_counter() - start
        document_processing_seconds.labels(ext=ext).observe(duration)
        documents_in_progress.dec()
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as exc:
                logger.error("Erro ao remover arquivo temporário %s: %s", temp_path, exc)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics():
    """Endpoint de scraping para o Prometheus. Não requer autenticação."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/convert", status_code=202)
@limiter.limit("10/minute")
async def convert(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _: str = Depends(verify_api_key),
):
    """
    Recebe o arquivo, valida e enfileira processamento em background.
    Retorna imediatamente com o ID e status "processing".
    Use GET /result/{id} para acompanhar o resultado.
    """
    temp_path, ext = await prepare_upload(file)

    doc_id = str(uuid.uuid4())
    await save_status(doc_id, "processing")

    documents_submitted_total.labels(ext=ext).inc()
    background_tasks.add_task(_process_and_store, doc_id, temp_path, ext)

    return {"id": doc_id, "status": "processing"}


@app.get("/result/{doc_id}")
@limiter.limit("10/minute")
async def get_result(
    request: Request,
    doc_id: str,
    _: str = Depends(verify_api_key),
):
    """
    Retorna o resultado da conversão.
    - status "processing" → ainda em andamento.
    - status "done"       → markdown disponível no campo "markdown".
    - status "error"      → falha no processamento.
    - 404                 → ID inexistente ou expirado (TTL esgotado).
    """
    status = await get_status(doc_id)

    if status is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado ou expirado.")

    if status == "processing":
        return {"id": doc_id, "status": "processing"}

    if status == "error":
        return {"id": doc_id, "status": "error", "detail": "Falha ao processar o documento."}

    # status == "done"
    markdown = await get_markdown(doc_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado ou expirado.")

    return {"id": doc_id, "status": "done", "markdown": markdown}
