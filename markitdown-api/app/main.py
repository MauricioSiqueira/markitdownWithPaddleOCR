import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth import verify_api_key
from app.services.markitdown_service import convert_file_to_markdown
from app.services.redis_service import get_markdown, save_markdown

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="MarkItDown API",
    version="2.0.0",
    description="API for converting documents to Markdown using Microsoft MarkItDown + PaddleOCR",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/convert", status_code=202)
@limiter.limit("10/minute")
async def convert(request: Request, file: UploadFile = File(...), _: str = Depends(verify_api_key)):
    """
    Converte um documento para Markdown e armazena no Redis.
    Retorna um ID para consulta posterior via GET /result/{id}.
    Limite: 10 requisições por minuto por IP. Bloqueio de 1 minuto ao exceder.
    """
    markdown = await convert_file_to_markdown(file)
    doc_id = str(uuid.uuid4())
    await save_markdown(doc_id, markdown)
    return {"id": doc_id}


@app.get("/result/{doc_id}")
@limiter.limit("10/minute")
async def get_result(request: Request, doc_id: str, _: str = Depends(verify_api_key)):
    """
    Retorna o Markdown previamente gerado pelo /convert.
    O resultado expira após o TTL configurado (padrão: 24 horas).
    Limite: 10 requisições por minuto por IP. Bloqueio de 1 minuto ao exceder.
    """
    markdown = await get_markdown(doc_id)
    if markdown is None:
        raise HTTPException(
            status_code=404,
            detail="Documento não encontrado ou expirado.",
        )
    return {"id": doc_id, "markdown": markdown}
