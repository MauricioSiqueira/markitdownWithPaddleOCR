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

    Cada página não vazia é precedida por um cabeçalho `---\\n## Página N`
    que permite correlacionar o conteúdo com os itens de `ocr_noise`
    (que também carregam o número da página).

    Páginas em branco recebem o cabeçalho com nota "(sem conteúdo)" para
    que a numeração fique contínua e rastreável.
    """
    if not page_results:
        return ""

    total = len(page_results)
    sections: List[str] = []

    for i, text in enumerate(page_results):
        page_num = i + 1
        cleaned = _clean_page_text(text)
        header = f"---\n## Página {page_num}/{total}"

        if cleaned.strip():
            sections.append(f"{header}\n\n{cleaned}")
        else:
            sections.append(f"{header}\n\n*(sem conteúdo)*")

    return "\n\n".join(sections)


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
