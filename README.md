# MarkItDown API

API para conversão de documentos para Markdown com suporte a PDFs escaneados via OCR.

Utiliza [Microsoft MarkItDown](https://github.com/microsoft/markitdown) para documentos com texto nativo e [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) para PDFs escaneados, processando o documento página por página e roteando cada uma pelo método mais adequado. O resultado é armazenado no Redis e recuperado via ID.

## Funcionalidades

- Conversão de `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xls` para Markdown
- PDFs híbridos: páginas com texto usam MarkItDown, páginas escaneadas usam OCR automaticamente
- Recebe a URI do arquivo hospedado na Azure Blob Storage — sem upload direto
- Processamento assíncrono em background — a rota retorna imediatamente
- Consulta de status isolada (`GET /status/{id}`), sem o custo de trafegar o conteúdo
- Resultado estruturado por página com ruídos OCR identificados
- Autenticação por API Key
- Validação de MIME type real do arquivo (python-magic)
- Limite de tamanho: 500 MB por arquivo
- Compressão gzip dos resultados no Redis
- Métricas Prometheus em `/metrics`

---

## Pré-requisitos

- [Docker](https://www.docker.com/) instalado
- [Docker Compose](https://docs.docker.com/compose/) instalado

---

## Rodando com Docker Compose (recomendado)

Sobe a API e o Redis juntos, idêntico ao ambiente de produção:

```bash
docker compose up --build -d
```

> Na primeira execução o PaddleOCR baixa os modelos (~16 MB). A API já responde normalmente enquanto isso acontece; os modelos são baixados sob demanda no primeiro documento com OCR.

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
docker build -t markitdown-api markitdown-api/

docker run -d -p 8000:8000 \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  markitdown-api
```

> `host.docker.internal` é o DNS que o Docker no Mac/Windows resolve para o IP da máquina host. No Linux, substitua por `--add-host=host.docker.internal:host-gateway`.

---

## Autenticação

Todas as rotas (exceto `/health` e `/metrics`) exigem uma API Key passada como query string:

```
?api_key=SUA_CHAVE
```

A chave padrão de desenvolvimento é:

```
nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ
```

Para produção, gere uma nova chave e adicione o hash SHA-512 dela em `markitdown-api/app/api_keys.py`.

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

Recebe a URI de um documento hospedado na Azure Blob Storage, baixa e inicia a conversão em background. Retorna imediatamente com um ID e status `processing`.

**Body (JSON):**

| Campo | Tipo   | Descrição |
|-------|--------|-----------|
| `uri` | string | URI do arquivo na Azure (com SAS token se necessário) |

```bash
curl -X POST "http://localhost:8000/convert?api_key=nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ" \
  -H "Content-Type: application/json" \
  -d '{"uri": "https://minhaconta.blob.core.windows.net/documentos/processo.pdf?sv=2023-01-03&se=..."}'
```

```json
{"id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653", "status": "processing"}
```

Use o `id` retornado para consultar o resultado.

**Códigos de erro:**

| Código | Motivo |
|--------|--------|
| `400` | URI inacessível, formato não suportado ou conteúdo não corresponde à extensão |
| `401` | API Key não informada |
| `403` | API Key inválida |
| `413` | Arquivo maior que 500 MB |
| `422` | Body inválido (ex.: `uri` não é uma URL válida) |

---

### `GET /status/{id}`

Consulta apenas o status da conversão (sem o conteúdo). Útil para polling leve enquanto o documento ainda está `processing`.

```bash
curl "http://localhost:8000/status/bd22c47e-fb79-4aa4-9cf1-589423f8d653?api_key=nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ"
```

```json
{"id": "bd22c47e-fb79-4aa4-9cf1-589423f8d653", "status": "processing"}
```

`status` pode ser `processing`, `done` ou `error`. Quando `done`, use `GET /result/{id}` para recuperar o Markdown.

**Códigos de erro:**

| Código | Motivo |
|--------|--------|
| `401` | API Key não informada |
| `403` | API Key inválida |
| `404` | ID não encontrado ou expirado (TTL esgotado) |

---

### `GET /result/{id}`

Recupera o resultado da conversão.

```bash
curl "http://localhost:8000/result/bd22c47e-fb79-4aa4-9cf1-589423f8d653?api_key=nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ"
```

Possíveis respostas:

**Ainda processando:**
```json
{"id": "...", "status": "processing"}
```

**Concluído:**
```json
{
  "id": "...",
  "status": "done",
  "pages": [
    {
      "page": 1,
      "markitdown": "# Processo nº 1234/2026\n\nAuto de Infração...",
      "noises": []
    },
    {
      "page": 2,
      "markitdown": "Conforme estabelecido no Art. 5º...",
      "noises": [
        {"page": 2, "text": "rmorl", "confidence": 0.54, "reason": "low_confidence"}
      ]
    }
  ]
}
```

O campo `noises` por página lista tokens que o OCR não reconheceu com confiança suficiente (`low_confidence`, threshold 0.75) ou que foram descartados por serem lixo (`garbage_pattern`). Permite metrificar a acertividade do OCR por documento.

**Erro no processamento:**
```json
{"id": "...", "status": "error", "detail": "Falha ao processar o documento."}
```

**ID não encontrado ou expirado (TTL esgotado):**
```
HTTP 404
```

---

### `GET /metrics`

Expõe métricas no formato Prometheus. Não requer autenticação.

```bash
curl http://localhost:8000/metrics
```

Métricas disponíveis:

| Métrica | Tipo | Descrição |
|---|---|---|
| `documents_in_progress` | Gauge | Conversões em andamento agora |
| `document_processing_seconds` | Histogram | Duração de conversão por extensão |
| `documents_completed_total` | Counter | Total concluídos por status e extensão |
| `documents_submitted_total` | Counter | Total de envios por extensão |
| `http_request_duration_seconds` | Histogram | Latência das rotas |
| `http_requests_total` | Counter | Requisições por endpoint e status HTTP |
| `process_resident_memory_bytes` | Gauge | RAM do processo |
| `process_cpu_seconds_total` | Counter | CPU do processo |

---

## Fluxo completo em um comando

```bash
# 1. Envia a URI e captura o ID
ID=$(curl -s -X POST \
  "http://localhost:8000/convert?api_key=nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ" \
  -H "Content-Type: application/json" \
  -d '{"uri": "https://minhaconta.blob.core.windows.net/docs/processo.pdf?sv=..."}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "ID: $ID"

# 2. Aguarda processamento e recupera o resultado
curl "http://localhost:8000/result/$ID?api_key=nJHU7QG6PuD8qwwkvWO0KgDLH7FUcltPu9L3a0mwJJQ"
```

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379` | URL de conexão com o Redis |
| `REDIS_TTL` | `86400` | Expiração do resultado em segundos (24h) |
| `OCR_ENABLED` | `true` | Habilita OCR para páginas escaneadas |
| `OCR_LANGUAGE` | `pt` | Idioma do OCR |
| `OCR_DPI` | `400` | Resolução de renderização para OCR |
| `OCR_CONFIDENCE_THRESHOLD` | `0.75` | Confiança mínima do OCR; abaixo disso o token vai para `noises` |
| `OCR_MIN_TEXT_LENGTH` | `30` | Mínimo de caracteres para considerar página como texto nativo |
| `OCR_MIN_IMAGE_RATIO` | `0.10` | Proporção mínima de área de imagem para acionar OCR |
| `OCR_PREPROCESSING` | `true` | Pré-processamento de imagem antes do OCR |
| `OCR_MAX_PAGES` | `100` | Limite de páginas processadas por documento |
| `PROCESSING_TIMEOUT` | `300` | Timeout de conversão em segundos |

---

## Rodando os testes

```bash
cd markitdown-api

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

venv/bin/pytest tests/ -v
```

---

## CI/CD

O projeto inclui `.github/workflows/deploy.yml` com acionamento manual (`workflow_dispatch`). O workflow:

1. Roda os testes
2. Faz build e publica a imagem no GHCR com duas tags: `latest` e o SHA do commit

Para publicar, acesse **Actions → Deploy em Produção → Run workflow** no GitHub.
