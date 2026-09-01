"""
Testes da API MarkItDown com Redis.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DUMMY_PDF = b"%PDF-1.4 fake pdf content"


def _md_result(text: str) -> MagicMock:
    result = MagicMock()
    result.text_content = text
    return result


def _mock_redis(save_ok=True, stored_value: str | None = None):
    """Retorna patches para save_markdown e get_markdown."""
    return (
        patch("app.main.save_markdown", new_callable=AsyncMock),
        patch("app.main.get_markdown", new_callable=AsyncMock, return_value=stored_value),
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /convert — grava no Redis, devolve ID
# ---------------------------------------------------------------------------


def test_convert_pdf_retorna_id():
    """POST /convert deve retornar um UUID e salvar no Redis."""
    with patch("app.main.save_markdown", new_callable=AsyncMock) as mock_save, \
         patch("app.services.markitdown_service.process_pdf") as mock_process:
        mock_process.return_value = "Texto do documento."

        response = client.post(
            "/convert",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        body = response.json()
        assert "id" in body
        assert len(body["id"]) == 36  # UUID4
        mock_save.assert_awaited_once()


def test_convert_pdf_escaneado_retorna_id():
    with patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf") as mock_process:
        mock_process.return_value = "Texto extraído via OCR."

        response = client.post(
            "/convert",
            files={"file": ("scan.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        assert "id" in response.json()


def test_convert_formato_invalido_retorna_400():
    response = client.post(
        "/convert",
        files={"file": ("img.jpg", b"fake", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "Formato não suportado" in response.json()["detail"]


def test_convert_erro_interno_retorna_500():
    with patch("app.services.markitdown_service.process_pdf") as mock_process:
        mock_process.side_effect = Exception("falha")

        response = client.post(
            "/convert",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /result/{id} — lê do Redis
# ---------------------------------------------------------------------------


def test_get_result_encontrado():
    texto = "Conteúdo markdown armazenado."

    with patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto):
        response = client.get("/result/meu-id-qualquer")

    assert response.status_code == 200
    body = response.json()
    assert body["markdown"] == texto
    assert body["id"] == "meu-id-qualquer"


def test_get_result_nao_encontrado_retorna_404():
    with patch("app.main.get_markdown", new_callable=AsyncMock, return_value=None):
        response = client.get("/result/id-inexistente")

    assert response.status_code == 404
    assert "não encontrado" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Fluxo completo: convert → result
# ---------------------------------------------------------------------------


def test_fluxo_completo_convert_e_recupera():
    """Simula o fluxo completo: POST /convert → GET /result/{id}."""
    texto = "Portaria nº 42 — regulamentação específica do órgão."
    captured_id = {}

    async def fake_save(doc_id, markdown):
        captured_id["id"] = doc_id
        captured_id["markdown"] = markdown

    with patch("app.main.save_markdown", side_effect=fake_save), \
         patch("app.services.markitdown_service.process_pdf", return_value=texto):
        r1 = client.post(
            "/convert",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        assert r1.status_code == 202
        doc_id = r1.json()["id"]

    with patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto):
        r2 = client.get(f"/result/{doc_id}")
        assert r2.status_code == 200
        assert r2.json()["markdown"] == texto
        assert r2.json()["id"] == doc_id


# ---------------------------------------------------------------------------
# Preservação de caracteres portugueses
# ---------------------------------------------------------------------------


def test_pdf_preserva_caracteres_portugueses():
    texto_pt = "Portaria nº 123/2024 — Seção de Administração do órgão público; critérios específicos."

    with patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=texto_pt):
        r1 = client.post(
            "/convert",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        doc_id = r1.json()["id"]

    with patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto_pt):
        r2 = client.get(f"/result/{doc_id}")
        body = r2.json()["markdown"]
        assert "nº" in body
        assert "ã" in body
        assert "ç" in body
        assert "é" in body
        assert "ó" in body


# ---------------------------------------------------------------------------
# Testes unitários: page_analyzer
# ---------------------------------------------------------------------------


def test_page_analyzer_texto_suficiente_nao_usa_ocr():
    from app.services.page_analyzer import should_use_ocr

    mock_page = MagicMock()
    mock_page.rect.width = 595.0
    mock_page.rect.height = 842.0

    mock_page.get_text.side_effect = lambda fmt: "A" * 50 if fmt == "text" else []

    assert should_use_ocr(mock_page, min_text_length=30, min_image_ratio=0.10) is False


def test_page_analyzer_scan_usa_ocr():
    from app.services.page_analyzer import should_use_ocr

    mock_page = MagicMock()
    mock_page.rect.width = 595.0
    mock_page.rect.height = 842.0

    img_block = (0.0, 0.0, 595.0, 700.0, "", 0, 1)
    mock_page.get_text.side_effect = lambda fmt: "abc" if fmt == "text" else [img_block]

    assert should_use_ocr(mock_page, min_text_length=30, min_image_ratio=0.10) is True


def test_page_analyzer_pagina_em_branco_nao_usa_ocr():
    from app.services.page_analyzer import should_use_ocr

    mock_page = MagicMock()
    mock_page.rect.width = 595.0
    mock_page.rect.height = 842.0
    mock_page.get_images.return_value = []
    mock_page.get_text.side_effect = lambda fmt: "" if fmt == "text" else []

    assert should_use_ocr(mock_page, min_text_length=30, min_image_ratio=0.10) is False


# ---------------------------------------------------------------------------
# Testes unitários: markdown_builder
# ---------------------------------------------------------------------------


def test_assemble_pages_une_paginas_nao_vazias():
    from app.services.markdown_builder import assemble_pages

    resultado = assemble_pages(["Página 1", "", "Página 3"])
    assert "Página 1" in resultado
    assert "Página 3" in resultado
    assert resultado.index("Página 1") < resultado.index("Página 3")


def test_assemble_pages_lista_vazia_retorna_vazio():
    from app.services.markdown_builder import assemble_pages

    assert assemble_pages([]) == ""


def test_assemble_pages_preserva_acentuacao():
    from app.services.markdown_builder import assemble_pages

    texto = "Portaria nº 1 — regulamentação específica"
    assert assemble_pages([texto]) == texto
