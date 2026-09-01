"""
Monta o documento Markdown final a partir dos resultados individuais por página.

Preserva:
  - ordem das páginas
  - parágrafos
  - acentuação e Unicode (sem normalização que elimine diacríticos)
  - quebras de linha significativas
"""
import logging
import re
from typing import List

logger = logging.getLogger(__name__)


def assemble_pages(page_results: List[str]) -> str:
    """
    Recebe os textos de cada página (na ordem correta) e monta o documento final.

    Páginas em branco são ignoradas na concatenação, mas a ordem das demais
    é sempre preservada.
    """
    if not page_results:
        return ""

    cleaned = [_clean_page_text(text) for text in page_results]
    non_empty = [p for p in cleaned if p.strip()]

    if not non_empty:
        return ""

    return "\n\n".join(non_empty)


def _clean_page_text(text: str) -> str:
    """
    Normalização mínima e não-destrutiva do texto de uma página.

    O que fazemos:
      - Remove caracteres de controle (exceto \\n, \\r, \\t).
      - Colapsa múltiplos espaços em branco dentro de uma linha em um único espaço.
      - Remove espaços no final de cada linha.
      - Reduz mais de duas linhas em branco consecutivas para duas.

    O que NÃO fazemos:
      - Não usamos unicodedata.normalize() com forma que elimine acentos.
      - Não convertemos para ASCII.
      - Não fazemos correção ortográfica.
    """
    if not text:
        return ""

    # Remove caracteres de controle (mantém \\n, \\r, \\t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Normaliza espaços dentro de cada linha
    lines = text.splitlines()
    normalized: List[str] = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).rstrip()
        normalized.append(line)

    text = "\n".join(normalized)

    # Colapsa mais de 2 linhas em branco consecutivas
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
