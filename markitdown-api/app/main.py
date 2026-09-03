import logging
import os
import time
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import verify_api_key
from app.schemas import ConvertRequest, ConvertResponse, HealthResponse, ResultResponse
from app.services.markitdown_service import prepare_from_uri, process_document
from app.services.metrics import (
    document_processing_seconds,
    documents_completed_total,
    documents_in_progress,
    documents_submitted_total,
    http_request_duration_seconds,
    http_requests_total,
)
from app.services.redis_service import get_pages, get_status, save_pages, save_status

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
        "Todas as rotas (exceto `/health` e `/metrics`) exigem `?api_key=SUA_CHAVE`."
    ),
    openapi_tags=_TAGS,
)
app.add_middleware(PrometheusMiddleware)


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _process_and_store(doc_id: str, temp_path: str, ext: str) -> None:
    documents_in_progress.inc()
    start = time.perf_counter()
    try:
        pages = await process_document(temp_path, ext)
        await save_pages(doc_id, pages)
        await save_status(doc_id, "done")
        documents_completed_total.labels(status="done", ext=ext).inc()
        total_noise = sum(len(p.get("noises", [])) for p in pages)
        logger.info("Processamento concluído: id=%s páginas=%d ruído=%d token(s)", doc_id, len(pages), total_noise)
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
        400: {"description": "URI inacessível, formato inválido ou conteúdo não corresponde à extensão."},
        401: {"description": "API Key não informada."},
        403: {"description": "API Key inválida."},
        413: {"description": "Arquivo maior que 500 MB."},
    },
)
async def convert(
    body: ConvertRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_api_key),
):
    """
    Recebe a URI de um documento hospedado na Azure, baixa e inicia a conversão assíncrona.

    A URI deve apontar para um arquivo com extensão suportada (.pdf, .docx, .pptx, .xlsx, .xls).
    O download e a validação ocorrem antes de retornar; a conversão em si ocorre em background.
    Use `GET /result/{id}` para acompanhar o andamento e recuperar o Markdown quando concluído.

    **Limite:** 500 MB por arquivo.
    """
    temp_path, ext = await prepare_from_uri(str(body.uri))

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
    },
)
async def get_result(
    doc_id: str,
    _: str = Depends(verify_api_key),
):
    """
    Retorna o status e, quando concluído, o Markdown do documento.

    | `status`      | Significado |
    |---------------|-------------|
    | `processing`  | Conversão em andamento — consulte novamente em instantes. |
    | `done`        | Concluído — campo `pages` disponível. |
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

    pages = await get_pages(doc_id)
    if pages is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado ou expirado.")

    return {"id": doc_id, "status": "done", "pages": pages}
