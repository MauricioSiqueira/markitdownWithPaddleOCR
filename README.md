# MarkItDown API

API para conversão de documentos para Markdown com suporte a PDFs escaneados via OCR.

Utiliza [Microsoft MarkItDown](https://github.com/microsoft/markitdown) para documentos com texto nativo e [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) para PDFs escaneados, processando o documento página por página e roteando cada uma pelo método mais adequado. O resultado é armazenado no Redis e recuperado via ID.

## Funcionalidades

- Conversão de `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xls` para Markdown
- PDFs híbridos: páginas com texto usam MarkItDown, páginas escaneadas usam OCR automaticamente
- Preservação de caracteres especiais (acentuação em Português)
- Resultado armazenado no Redis com TTL configurável
- Pronto para deploy via Docker e GHCR

---

## Pré-requisitos

- [Docker](https://www.docker.com/) instalado
- [Docker Compose](https://docs.docker.com/compose/) instalado

---

## Rodando com Docker Compose (recomendado)

Sobe a API e o Redis juntos — idêntico ao ambiente de produção:

```bash
docker compose up -d
```

Para acompanhar os logs:

```bash
docker compose logs -f api
```

Para derrubar:

```bash
docker compose down
```

---

## Rodando apenas o container da API (Redis externo)

Se você já tem um Redis rodando localmente na porta `6379`:

```bash
docker build -t markitdown-api .

docker run -d -p 8000:8000 \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  markitdown-api
```

> `host.docker.internal` é o DNS que o Docker no Mac/Windows resolve para o IP da máquina host. No Linux, substitua por `--add-host=host.docker.internal:host-gateway`.

---

## Usando a imagem publicada no GHCR

```bash
docker pull ghcr.io/<usuario>/<repo>:latest

docker run -d -p 8000:8000 \
  -e REDIS_URL=redis://redis:6379 \
  ghcr.io/<usuario>/<repo>:latest
```

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379` | URL de conexão com o Redis |
| `REDIS_TTL` | `86400` | Tempo de expiração do resultado em segundos (24h) |
| `OCR_ENABLED` | `true` | Habilita OCR para páginas escaneadas |
| `OCR_LANGUAGE` | `pt` | Idioma do OCR |
| `OCR_DPI` | `300` | Resolução de renderização das páginas para OCR |
| `OCR_MIN_TEXT_LENGTH` | `30` | Mínimo de caracteres para considerar a página como texto nativo |
| `OCR_MIN_IMAGE_RATIO` | `0.10` | Proporção mínima de área de imagem para acionar OCR |
| `OCR_PREPROCESSING` | `true` | Aplica pipeline de pré-processamento de imagem antes do OCR |

---

## Endpoints

### `GET /health`
Verifica se a API está online.

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

---

### `POST /convert`
Converte um documento para Markdown e armazena o resultado no Redis. Retorna um ID para consulta posterior.

```bash
curl -X POST http://localhost:8000/convert \
  -F "file=@documento.pdf"
```

```json
{"id": "550e8400-e29b-41d4-a716-446655440000"}
```

---

### `GET /result/{id}`
Recupera o Markdown gerado anteriormente pelo `/convert`. O resultado expira conforme o `REDIS_TTL` configurado.

```bash
curl http://localhost:8000/result/550e8400-e29b-41d4-a716-446655440000
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "markdown": "# Título do Documento\n\nConteúdo convertido..."
}
```

Retorna `404` se o ID não existir ou tiver expirado.

---

## Fluxo completo em um comando

```bash
ID=$(curl -s -X POST http://localhost:8000/convert \
  -F "file=@documento.pdf" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "ID gerado: $ID"

curl -s http://localhost:8000/result/$ID
```

---

## Rodando os testes

```bash
python -m venv venv
source venv/bin/activate

pip install fastapi uvicorn python-multipart markitdown pymupdf numpy opencv-python-headless redis httpx pytest pytest-mock

pytest tests/ -v
```

---

## CI/CD

O projeto inclui um workflow em `.github/workflows/deploy.yml` que:

1. Roda os testes a cada push e pull request para `main`
2. Faz build e publica a imagem no GHCR automaticamente após os testes passarem

Tags geradas automaticamente:
- `latest` — push para `main`
- `1.2.3` e `1.2` — ao criar tag `v1.2.3`
- `sha-a1b2c3d` — sempre presente para rastreabilidade
