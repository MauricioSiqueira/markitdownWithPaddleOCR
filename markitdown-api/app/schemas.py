from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, AnyHttpUrl


class ConvertRequest(BaseModel):
    uri: AnyHttpUrl = Field(
        description="URI do arquivo hospedado na Azure (Blob Storage). O formato deve ser suportado: .pdf, .docx, .pptx, .xlsx, .xls.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "uri": "https://minhaconta.blob.core.windows.net/documentos/processo.pdf?sv=2023-01-03&se=...",
            }
        }
    }


class HealthResponse(BaseModel):
    status: Literal["ok"]

    model_config = {"json_schema_extra": {"example": {"status": "ok"}}}


class ConvertResponse(BaseModel):
    id: str = Field(
        description="UUID do documento. Use em GET /result/{id} para acompanhar o resultado.",
        examples=["bd22c47e-fb79-4aa4-9cf1-589423f8d653"],
    )
    status: Literal["processing"] = Field(
        description="Sempre 'processing' — conversão ocorre em background."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                "status": "processing",
            }
        }
    }


class PageResult(BaseModel):
    page: int = Field(description="Número da página (começa em 1).")
    markitdown: str = Field(description="Conteúdo Markdown extraído da página.")
    noises: List[Dict[str, Any]] = Field(
        description=(
            "Tokens que o OCR não reconheceu com confiança suficiente nesta página. "
            "Cada item: {page, text, confidence, reason}."
        )
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "page": 3,
                "markitdown": "Art. 5º — São direitos fundamentais...",
                "noises": [
                    {"page": 3, "text": "rmorl", "confidence": 0.54, "reason": "low_confidence"},
                ],
            }
        }
    }


class ResultResponse(BaseModel):
    id: str = Field(description="UUID do documento.")
    status: Literal["processing", "done", "error"] = Field(
        description=(
            "'processing' → ainda em andamento; "
            "'done' → concluído, campo 'pages' disponível; "
            "'error' → falha no processamento."
        )
    )
    pages: Optional[List[PageResult]] = Field(
        default=None,
        description="Lista de páginas com markdown e ruídos. Presente apenas quando status='done'.",
    )
    detail: Optional[str] = Field(
        default=None,
        description="Mensagem de erro. Presente apenas quando status='error'.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653",
                "status": "done",
                "pages": [
                    {
                        "page": 1,
                        "markitdown": "# Processo nº 1234/2026\n\nAuto de Infração...",
                        "noises": [],
                    },
                    {
                        "page": 2,
                        "markitdown": "Conforme estabelecido no Art. 5º...",
                        "noises": [
                            {"page": 2, "text": "rmorl", "confidence": 0.54, "reason": "low_confidence"},
                        ],
                    },
                ],
            }
        }
    }
