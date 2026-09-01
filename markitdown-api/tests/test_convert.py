"""
Testes da API MarkItDown com Redis e background tasks.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DUMMY_PDF = b"%PDF-1.4 fake pdf content"

# Chave raw de teste — deve bater com o hash em api_keys.py
VALID_API_KEY = "nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reseta o estado do rate limiter antes de cada teste para evitar interferência."""
    from app.main import limiter
    limiter._storage.reset()
    yield


def _md_result(text: str) -> MagicMock:
    result = MagicMock()
    result.text_content = text
    return result


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limit_retorna_429_apos_10_requisicoes():
    """Após 10 requisições no mesmo minuto, o IP deve ser bloqueado com 429."""
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value="texto"):
        for _ in range(10):
            r = client.post(
                f"/convert?api_key={VALID_API_KEY}",
                files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
            )
            assert r.status_code == 202

        blocked = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )
        assert blocked.status_code == 429


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------


def test_sem_api_key_retorna_401():
    response = client.post(
        "/convert",
        files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
    )
    assert response.status_code == 401


def test_api_key_invalida_retorna_403():
    response = client.post(
        "/convert?api_key=chave-errada",
        files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
    )
    assert response.status_code == 403


def test_get_result_sem_api_key_retorna_401():
    response = client.get("/result/qualquer-id")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /convert — retorna ID + status "processing" imediatamente
# ---------------------------------------------------------------------------


def test_convert_pdf_retorna_id_e_status_processing():
    """POST /convert deve retornar UUID e status 'processing' imediatamente."""
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value="Texto do documento."):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        body = response.json()
        assert "id" in body
        assert len(body["id"]) == 36  # UUID4
        assert body["status"] == "processing"


def test_convert_pdf_escaneado_retorna_id():
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value="Texto extraído via OCR."):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("scan.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        body = response.json()
        assert "id" in body
        assert body["status"] == "processing"


def test_convert_formato_invalido_retorna_400():
    response = client.post(
        f"/convert?api_key={VALID_API_KEY}",
        files={"file": ("img.jpg", b"fake", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "Formato não suportado" in response.json()["detail"]


def test_arquivo_com_extensao_valida_mas_conteudo_invalido_retorna_400():
    """Arquivo com extensão .pdf mas conteúdo falso deve ser rejeitado pelo python-magic."""
    with patch("app.services.markitdown_service._validate_mime", return_value=False):
        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("malicioso.pdf", b"isto nao e um pdf", "application/pdf")},
        )
    assert response.status_code == 400
    assert "não corresponde" in response.json()["detail"]


def test_arquivo_com_mime_valido_e_aceito():
    """Arquivo com MIME type correto detectado pelo python-magic deve passar."""
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value="texto"), \
         patch("app.services.markitdown_service._validate_mime", return_value=True):
        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", b"%PDF-1.4 conteudo fake", "application/pdf")},
        )
    assert response.status_code == 202


def test_arquivo_maior_que_500mb_retorna_413():
    """Arquivo acima de 500 MB deve ser rejeitado durante a leitura em chunks."""
    from fastapi import HTTPException as _HTTPException
    with patch("app.services.markitdown_service._read_chunked", new_callable=AsyncMock) as mock_read:
        mock_read.side_effect = _HTTPException(
            status_code=413,
            detail="O arquivo excedeu o limite de tamanho permitido (500 MB).",
        )
        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("grande.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert response.status_code == 413
    assert "500 MB" in response.json()["detail"]


def test_convert_erro_no_processamento_salva_status_error():
    """Erro durante processamento em background deve resultar em status 'error' no Redis."""
    saved_statuses: list[tuple] = []

    async def capture_status(doc_id: str, status: str) -> None:
        saved_statuses.append((doc_id, status))

    with patch("app.main.save_status", side_effect=capture_status), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", side_effect=Exception("falha simulada")):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )

    assert response.status_code == 202
    # Background task deve ter gravado "processing" e depois "error"
    statuses = [s for _, s in saved_statuses]
    assert "processing" in statuses
    assert "error" in statuses


# ---------------------------------------------------------------------------
# GET /result/{id} — lê status e markdown do Redis
# ---------------------------------------------------------------------------


def test_get_result_status_processing():
    """Enquanto processamento não terminou, deve retornar status 'processing'."""
    with patch("app.main.get_status", new_callable=AsyncMock, return_value="processing"):
        response = client.get(f"/result/meu-id?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["id"] == "meu-id"


def test_get_result_encontrado():
    """Quando processamento terminou, deve retornar status 'done' e markdown."""
    texto = "Conteúdo markdown armazenado."

    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto):
        response = client.get(f"/result/meu-id-qualquer?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["markdown"] == texto
    assert body["id"] == "meu-id-qualquer"
    assert body["status"] == "done"


def test_get_result_status_error():
    """Quando processamento falhou, deve retornar status 'error'."""
    with patch("app.main.get_status", new_callable=AsyncMock, return_value="error"):
        response = client.get(f"/result/id-com-erro?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"


def test_get_result_nao_encontrado_retorna_404():
    """ID inexistente ou expirado deve retornar 404."""
    with patch("app.main.get_status", new_callable=AsyncMock, return_value=None):
        response = client.get(f"/result/id-inexistente?api_key={VALID_API_KEY}")

    assert response.status_code == 404
    assert "não encontrado" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Fluxo completo: convert → result
# ---------------------------------------------------------------------------


def test_fluxo_completo_convert_e_recupera():
    """Simula o fluxo completo: POST /convert → GET /result/{id}."""
    texto = "Portaria nº 42 — regulamentação específica do órgão."
    captured_id: dict = {}

    async def fake_save_markdown(doc_id: str, markdown: str) -> None:
        captured_id["id"] = doc_id
        captured_id["markdown"] = markdown

    async def fake_save_status(doc_id: str, status: str) -> None:
        pass

    with patch("app.main.save_markdown", side_effect=fake_save_markdown), \
         patch("app.main.save_status", side_effect=fake_save_status), \
         patch("app.services.markitdown_service.process_pdf", return_value=texto):
        r1 = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        assert r1.status_code == 202
        doc_id = r1.json()["id"]
        assert r1.json()["status"] == "processing"

    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto):
        r2 = client.get(f"/result/{doc_id}?api_key={VALID_API_KEY}")
        assert r2.status_code == 200
        assert r2.json()["markdown"] == texto
        assert r2.json()["id"] == doc_id
        assert r2.json()["status"] == "done"


# ---------------------------------------------------------------------------
# Preservação de caracteres portugueses
# ---------------------------------------------------------------------------


def test_pdf_preserva_caracteres_portugueses():
    texto_pt = "Portaria nº 123/2024 — Seção de Administração do órgão público; critérios específicos."

    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_markdown", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=texto_pt):
        r1 = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        doc_id = r1.json()["id"]

    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_markdown", new_callable=AsyncMock, return_value=texto_pt):
        r2 = client.get(f"/result/{doc_id}?api_key={VALID_API_KEY}")
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
