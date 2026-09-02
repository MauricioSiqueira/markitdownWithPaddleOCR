"""
Testes da API MarkItDown com Redis e background tasks.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DUMMY_PDF = b"%PDF-1.4 fake pdf content"
VALID_API_KEY = "nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ"

DUMMY_PAGES = [
    {"page": 1, "markitdown": "Conteúdo da página 1.", "noises": []},
    {"page": 2, "markitdown": "Conteúdo da página 2.", "noises": [
        {"page": 2, "text": "rmorl", "confidence": 0.54, "reason": "low_confidence"}
    ]},
]


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
# POST /convert
# ---------------------------------------------------------------------------


def test_convert_pdf_retorna_id_e_status_processing():
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_pages", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=DUMMY_PAGES):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        body = response.json()
        assert "id" in body
        assert len(body["id"]) == 36
        assert body["status"] == "processing"


def test_convert_pdf_escaneado_retorna_id():
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_pages", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=DUMMY_PAGES):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("scan.pdf", DUMMY_PDF, "application/pdf")},
        )

        assert response.status_code == 202
        assert response.json()["status"] == "processing"


def test_convert_formato_invalido_retorna_400():
    response = client.post(
        f"/convert?api_key={VALID_API_KEY}",
        files={"file": ("img.jpg", b"fake", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "Formato não suportado" in response.json()["detail"]


def test_arquivo_com_extensao_valida_mas_conteudo_invalido_retorna_400():
    with patch("app.services.markitdown_service._validate_mime", return_value=False):
        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("malicioso.pdf", b"isto nao e um pdf", "application/pdf")},
        )
    assert response.status_code == 400
    assert "não corresponde" in response.json()["detail"]


def test_arquivo_com_mime_valido_e_aceito():
    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_pages", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=DUMMY_PAGES), \
         patch("app.services.markitdown_service._validate_mime", return_value=True):
        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", b"%PDF-1.4 conteudo fake", "application/pdf")},
        )
    assert response.status_code == 202


def test_arquivo_maior_que_500mb_retorna_413():
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
    saved_statuses: list[tuple] = []

    async def capture_status(doc_id: str, status: str) -> None:
        saved_statuses.append((doc_id, status))

    with patch("app.main.save_status", side_effect=capture_status), \
         patch("app.main.save_pages", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", side_effect=Exception("falha simulada")):

        response = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("doc.pdf", DUMMY_PDF, "application/pdf")},
        )

    assert response.status_code == 202
    statuses = [s for _, s in saved_statuses]
    assert "processing" in statuses
    assert "error" in statuses


# ---------------------------------------------------------------------------
# GET /result/{id}
# ---------------------------------------------------------------------------


def test_get_result_status_processing():
    with patch("app.main.get_status", new_callable=AsyncMock, return_value="processing"):
        response = client.get(f"/result/meu-id?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["id"] == "meu-id"


def test_get_result_encontrado():
    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_pages", new_callable=AsyncMock, return_value=DUMMY_PAGES):
        response = client.get(f"/result/meu-id-qualquer?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["id"] == "meu-id-qualquer"
    assert len(body["pages"]) == 2
    assert body["pages"][0]["page"] == 1
    assert body["pages"][1]["noises"][0]["reason"] == "low_confidence"


def test_get_result_status_error():
    with patch("app.main.get_status", new_callable=AsyncMock, return_value="error"):
        response = client.get(f"/result/id-com-erro?api_key={VALID_API_KEY}")

    assert response.status_code == 200
    assert response.json()["status"] == "error"


def test_get_result_nao_encontrado_retorna_404():
    with patch("app.main.get_status", new_callable=AsyncMock, return_value=None):
        response = client.get(f"/result/id-inexistente?api_key={VALID_API_KEY}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fluxo completo
# ---------------------------------------------------------------------------


def test_fluxo_completo_convert_e_recupera():
    captured: dict = {}

    async def fake_save_pages(doc_id: str, pages: list) -> None:
        captured["id"] = doc_id

    async def fake_save_status(doc_id: str, status: str) -> None:
        pass

    with patch("app.main.save_pages", side_effect=fake_save_pages), \
         patch("app.main.save_status", side_effect=fake_save_status), \
         patch("app.services.markitdown_service.process_pdf", return_value=DUMMY_PAGES):
        r1 = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        assert r1.status_code == 202
        doc_id = r1.json()["id"]
        assert r1.json()["status"] == "processing"

    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_pages", new_callable=AsyncMock, return_value=DUMMY_PAGES):
        r2 = client.get(f"/result/{doc_id}?api_key={VALID_API_KEY}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "done"
        assert r2.json()["id"] == doc_id
        assert len(r2.json()["pages"]) == 2


# ---------------------------------------------------------------------------
# Preservação de caracteres portugueses
# ---------------------------------------------------------------------------


def test_pdf_preserva_caracteres_portugueses():
    texto_pt = "Portaria nº 123/2024 — Seção de Administração do órgão público; critérios específicos."
    pages_pt = [{"page": 1, "markitdown": texto_pt, "noises": []}]

    with patch("app.main.save_status", new_callable=AsyncMock), \
         patch("app.main.save_pages", new_callable=AsyncMock), \
         patch("app.services.markitdown_service.process_pdf", return_value=pages_pt):
        r1 = client.post(
            f"/convert?api_key={VALID_API_KEY}",
            files={"file": ("portaria.pdf", DUMMY_PDF, "application/pdf")},
        )
        doc_id = r1.json()["id"]

    with patch("app.main.get_status", new_callable=AsyncMock, return_value="done"), \
         patch("app.main.get_pages", new_callable=AsyncMock, return_value=pages_pt):
        r2 = client.get(f"/result/{doc_id}?api_key={VALID_API_KEY}")
        body = r2.json()["pages"][0]["markitdown"]
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

    resultado = assemble_pages(["Conteúdo da primeira", "", "Conteúdo da terceira"])
    assert "Conteúdo da primeira" in resultado
    assert "Conteúdo da terceira" in resultado
    assert "## Página 1/3" in resultado
    assert "## Página 2/3" in resultado
    assert "## Página 3/3" in resultado
    assert resultado.index("Página 1") < resultado.index("Página 3")


def test_assemble_pages_lista_vazia_retorna_vazio():
    from app.services.markdown_builder import assemble_pages

    assert assemble_pages([]) == ""


def test_assemble_pages_pagina_vazia_recebe_nota():
    from app.services.markdown_builder import assemble_pages

    resultado = assemble_pages(["texto", ""])
    assert "## Página 2/2" in resultado
    assert "*(sem conteúdo)*" in resultado


def test_assemble_pages_preserva_acentuacao():
    from app.services.markdown_builder import assemble_pages

    texto = "Portaria nº 1 — regulamentação específica"
    resultado = assemble_pages([texto])
    assert texto in resultado
    assert "## Página 1/1" in resultado
