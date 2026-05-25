#!/usr/bin/env python3
"""Extrai seções e tabelas de um relatório DOCX da Fundação Rio Verde."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

SECOES_ALVO = [
    "OBJETIVO",
    "MATERIAL E MÉTODOS",
    "RESULTADOS E DISCUSSÃO",
    "CONSIDERAÇÕES",
    "REFERÊNCIAS BIBLIOGRÁFICAS",
]


def normalizar_titulo(texto: str) -> str:
    texto = texto.strip().upper()
    texto = " ".join(texto.split())
    return texto


def iterar_blocos(documento: DocxDocument):
    """Itera parágrafos e tabelas na ordem original do documento."""
    corpo = documento.element.body
    for elemento in corpo.iterchildren():
        if elemento.tag.endswith("}p"):
            yield Paragraph(elemento, documento), "paragrafo"
        elif elemento.tag.endswith("}tbl"):
            yield Table(elemento, documento), "tabela"


def parece_legenda(texto: str) -> bool:
    texto_limpo = texto.strip()
    if not texto_limpo:
        return False

    padrao_legenda = re.compile(r"^(tabela|quadro)\s*\d+", re.IGNORECASE)
    if padrao_legenda.match(texto_limpo):
        return True

    # Heurística: frases curtas próximas de tabela costumam ser legenda.
    return len(texto_limpo) <= 180 and texto_limpo.endswith((":", "."))


def encontrar_legenda_mais_proxima(paragrafos: list[str]) -> str:
    for texto in reversed(paragrafos):
        if parece_legenda(texto):
            return texto.strip()
    return ""


def extrair_tabela(tabela: Table) -> list[list[str]]:
    dados: list[list[str]] = []
    for linha in tabela.rows:
        dados.append([celula.text.strip() for celula in linha.cells])
    return dados


def extrair_documento(caminho_docx: Path) -> dict[str, Any]:
    try:
        documento = Document(str(caminho_docx))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao abrir o arquivo DOCX '{caminho_docx}': {exc}") from exc

    paragrafos_em_ordem: list[str] = []
    secoes: dict[str, list[str]] = {secao: [] for secao in SECOES_ALVO}
    tabelas: list[dict[str, Any]] = []

    secao_atual: str | None = None

    for bloco, tipo in iterar_blocos(documento):
        if tipo == "paragrafo":
            texto = bloco.text.strip()
            paragrafos_em_ordem.append(texto)

            titulo_normalizado = normalizar_titulo(texto)
            if titulo_normalizado in SECOES_ALVO:
                secao_atual = titulo_normalizado
                continue

            if secao_atual and texto:
                secoes[secao_atual].append(texto)

        elif tipo == "tabela":
            legenda = encontrar_legenda_mais_proxima(paragrafos_em_ordem)
            tabelas.append(
                {
                    "indice_tabela": len(tabelas) + 1,
                    "legenda_proxima": legenda,
                    "conteudo": extrair_tabela(bloco),
                }
            )

    return {
        "arquivo_origem": str(caminho_docx),
        "paragrafos": paragrafos_em_ordem,
        "secoes": secoes,
        "tabelas": tabelas,
    }


def salvar_json(dados: dict[str, Any], caminho_saida: Path) -> None:
    try:
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao salvar JSON em '{caminho_saida}': {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai seções e tabelas de um relatório agronômico em DOCX."
    )
    parser.add_argument(
        "arquivo_docx",
        type=Path,
        help="Caminho para o arquivo .docx de entrada.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("entrada/tabelas_extraidas/tabelas_extraidas.json"),
        help="Caminho do JSON de saída (padrão: entrada/tabelas_extraidas/tabelas_extraidas.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    caminho_docx = args.arquivo_docx
    if not caminho_docx.exists():
        print(f"Erro: arquivo não encontrado: '{caminho_docx}'.", file=sys.stderr)
        return 2

    if caminho_docx.suffix.lower() != ".docx":
        print(
            f"Erro: o arquivo informado não é .docx: '{caminho_docx}'.",
            file=sys.stderr,
        )
        return 2

    if not caminho_docx.is_file():
        print(f"Erro: o caminho informado não é um arquivo: '{caminho_docx}'.", file=sys.stderr)
        return 2

    try:
        dados = extrair_documento(caminho_docx)
        salvar_json(dados, args.saida)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Extração concluída com sucesso. JSON salvo em: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
