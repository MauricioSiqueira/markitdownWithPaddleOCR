import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File

from app.services.markitdown_service import convert_file_to_markdown
from app.services.redis_service import get_markdown, save_markdown

app = FastAPI(
    title="MarkItDown API",
    version="2.0.0",
    description="API for converting documents to Markdown using Microsoft MarkItDown + PaddleOCR",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/convert", status_code=202)
async def convert(file: UploadFile = File(...)):
    """
    Converte um documento para Markdown e armazena no Redis.
    Retorna um ID para consulta posterior via GET /result/{id}.
    """
    markdown = await convert_file_to_markdown(file)
    doc_id = str(uuid.uuid4())
    await save_markdown(doc_id, markdown)
    return {"id": doc_id}


@app.get("/result/{doc_id}")
async def get_result(doc_id: str):
    """
    Retorna o Markdown previamente gerado pelo /convert.
    O resultado expira após o TTL configurado (padrão: 24 horas).
    """
    markdown = await get_markdown(doc_id)
    if markdown is None:
        raise HTTPException(
            status_code=404,
            detail="Documento não encontrado ou expirado.",
        )
    return {"id": doc_id, "markdown": markdown}
