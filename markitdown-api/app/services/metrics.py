"""
Definição centralizada das métricas Prometheus.

Métricas expostas:
  - http_requests_total          — contador por endpoint/método/status
  - http_request_duration_seconds — latência HTTP (histogram)
  - documents_submitted_total    — documentos enviados, por extensão
  - documents_completed_total    — documentos concluídos, por status e extensão
  - documents_in_progress        — gauge: conversões em andamento agora
  - document_processing_seconds  — duração de conversão (histogram), por extensão
  - process_* (RSS, CPU)         — coletadas automaticamente pelo prometheus_client
"""
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total de requisições HTTP recebidas.",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Latência das requisições HTTP em segundos.",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Processamento de documentos
# ---------------------------------------------------------------------------

documents_submitted_total = Counter(
    "documents_submitted_total",
    "Total de documentos enviados para processamento.",
    ["ext"],
)

documents_completed_total = Counter(
    "documents_completed_total",
    "Total de documentos cujo processamento terminou.",
    ["status", "ext"],  # status: done | error
)

documents_in_progress = Gauge(
    "documents_in_progress",
    "Número de documentos sendo processados agora (background tasks ativas).",
)

document_processing_seconds = Histogram(
    "document_processing_seconds",
    "Duração total da conversão de um documento em segundos.",
    ["ext"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)
