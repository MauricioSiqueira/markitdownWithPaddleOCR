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
from app.schemas import ConvertResponse, HealthResponse, ResultResponse
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
# Middleware de métricas HTTP
# ---------------------------------------------------------------------------


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

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

_TAGS = [
    {
        "name": "Conversão",
        "description": "Envio de documentos e recuperação do Markdown gerado.",
    },
    {
        "name": "Observabilidade",
        "description": "Health check e métricas de monitoramento.",
    },
]

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="MarkItDown API",
    version="2.0.0",
    description=(
        "Converte documentos (**PDF, DOCX, PPTX, XLSX, XLS**) para Markdown.\n\n"
        "PDFs são processados página por página: páginas com texto nativo usam "
        "**MarkItDown**, páginas escaneadas usam **PaddleOCR** automaticamente.\n\n"
        "O processamento ocorre em background — `POST /convert` retorna imediatamente "
        "e o resultado é recuperado via `GET /result/{id}`.\n\n"
        "### Autenticação\n"
        "Todas as rotas (exceto `/health` e `/metrics`) exigem `?api_key=SUA_CHAVE`.\n\n"
        "### Rate limit\n"
        "10 requisições por minuto por IP. Excedido o limite, o IP é bloqueado por 1 minuto."
    ),
    openapi_tags=_TAGS,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(PrometheusMiddleware)


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _process_and_store(doc_id: str, temp_path: str, ext: str) -> None:
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


@app.get(
    "/health",
    tags=["Observabilidade"],
    summary="Health check",
    response_model=HealthResponse,
)
async def health_check():
    """Verifica se a API está online e aceitando requisições."""
    return {"status": "ok"}


@app.get(
    "/metrics",
    tags=["Observabilidade"],
    summary="Métricas Prometheus",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def metrics():
    """Endpoint de scraping para o Prometheus. Não requer autenticação."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post(
    "/convert",
    tags=["Conversão"],
    summary="Enviar documento para conversão",
    response_model=ConvertResponse,
    status_code=202,
    responses={
        400: {"description": "Formato de arquivo inválido ou conteúdo não corresponde à extensão."},
        401: {"description": "API Key não informada."},
        403: {"description": "API Key inválida."},
        413: {"description": "Arquivo maior que 500 MB."},
        429: {"description": "Rate limit atingido. Tente novamente em 1 minuto."},
    },
)
@limiter.limit("10/minute")
async def convert(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Arquivo a converter. Formatos aceitos: .pdf, .docx, .pptx, .xlsx, .xls"),
    _: str = Depends(verify_api_key),
):
    """
    Envia um documento para conversão assíncrona.

    O arquivo é validado (extensão + MIME type real) e lido antes de retornar.
    A conversão em si ocorre em background — use `GET /result/{id}` para
    acompanhar o andamento e recuperar o Markdown quando concluído.

    **Limite:** 500 MB por arquivo · 10 requisições/min por IP.
    """
    temp_path, ext = await prepare_upload(file)

    doc_id = str(uuid.uuid4())
    await save_status(doc_id, "processing")

    documents_submitted_total.labels(ext=ext).inc()
    background_tasks.add_task(_process_and_store, doc_id, temp_path, ext)

    return {"id": doc_id, "status": "processing"}


@app.get(
    "/result/{doc_id}",
    tags=["Conversão"],
    summary="Recuperar resultado da conversão",
    response_model=ResultResponse,
    responses={
        200: {"description": "Status atual do documento (processing, done ou error)."},
        401: {"description": "API Key não informada."},
        403: {"description": "API Key inválida."},
        404: {"description": "ID não encontrado ou resultado expirado (TTL esgotado)."},
        429: {"description": "Rate limit atingido. Tente novamente em 1 minuto."},
    },
)
@limiter.limit("10/minute")
async def get_result(
    request: Request,
    doc_id: str,
    _: str = Depends(verify_api_key),
):
    """
    Retorna o status e, quando concluído, o Markdown do documento.

    | `status`      | Significado |
    |---------------|-------------|
    | `processing`  | Conversão em andamento — consulte novamente em instantes. |
    | `done`        | Concluído — campo `markdown` disponível. |
    | `error`       | Falha no processamento — campo `detail` com a mensagem. |

    O resultado expira conforme a variável `REDIS_TTL` (padrão: 24h).
    Após expirado, retorna `404`.
    """
    status = await get_status(doc_id)

    if status is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado ou expirado.")

    if status == "processing":
        return {"id": doc_id, "status": "processing"}

    if status == "error":
        return {"id": doc_id, "status": "error", "detail": "Falha ao processar o documento."}

    markdown = await get_markdown(doc_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado ou expirado.")

    return {"id": doc_id, "status": "done", "markdown": markdown}
