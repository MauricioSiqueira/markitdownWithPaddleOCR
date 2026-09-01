from typing import Literal, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]

    model_config = {
        "json_schema_extra": {"example": {"status": "ok"}}
    }


class ConvertResponse(BaseModel):
    id: str = Field(
        description="UUID do documento. Use-o em GET /result/{id} para acompanhar o resultado.",
        examples=["bd22c47e-fb79-4aa4-9cf1-589423f8d653"],
    )
    status: Literal["processing"] = Field(
        description="Sempre 'processing' — o documento é convertido em background."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                "status": "processing",
            }
        }
    }


class ResultResponse(BaseModel):
    id: str = Field(
        description="UUID do documento.",
        examples=["bd22c47e-fb79-4aa4-9cf1-589423f8d653"],
    )
    status: Literal["processing", "done", "error"] = Field(
        description=(
            "'processing' → ainda em andamento; "
            "'done' → concluído, campo 'markdown' disponível; "
            "'error' → falha no processamento."
        )
    )
    markdown: Optional[str] = Field(
        default=None,
        description="Conteúdo Markdown gerado. Presente apenas quando status='done'.",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Mensagem de erro. Presente apenas quando status='error'.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": {
                "processing": {
                    "summary": "Ainda processando",
                    "value": {
                        "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                        "status": "processing",
                    },
                },
                "done": {
                    "summary": "Concluído",
                    "value": {
                        "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                        "status": "done",
                        "markdown": "# Título do Documento\n\nConteúdo convertido...",
                    },
                },
                "error": {
                    "summary": "Falha no processamento",
                    "value": {
                        "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                        "status": "error",
                        "detail": "Falha ao processar o documento.",
                    },
                },
            }
        }
    }
