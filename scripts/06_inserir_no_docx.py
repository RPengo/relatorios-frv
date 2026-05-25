#!/usr/bin/env python3
"""Insere seções geradas em um arquivo DOCX sem alterar o restante do relatório."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Substitui conteúdo das seções RESULTADOS E DISCUSSÃO e CONSIDERAÇÕES.")
    parser.add_argument("--docx-original", type=Path, required=True, help="Caminho do arquivo .docx original")
    parser.add_argument("--resultados", type=Path, default=Path("saida/textos_gerados/resultados_discussao.md"))
    parser.add_argument("--consideracoes", type=Path, default=Path("saida/textos_gerados/consideracoes.md"))
    parser.add_argument("--saida-dir", type=Path, default=Path("saida/relatorios_finalizados"))
    return parser.parse_args()


def normalizar_titulo(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto or "").strip().upper()
    return texto


def carregar_texto(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8").strip()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler arquivo '{caminho}': {exc}") from exc


def encontrar_indice_secao(doc: Document, titulo: str) -> int:
    alvo = normalizar_titulo(titulo)
    for i, par in enumerate(doc.paragraphs):
        if normalizar_titulo(par.text) == alvo:
            return i
    raise RuntimeError(f"Seção '{titulo}' não encontrada no documento.")


def eh_titulo(par_texto: str) -> bool:
    texto = normalizar_titulo(par_texto)
    if not texto:
        return False
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    # Heurística para títulos: quase todo em maiúsculas.
    return len(letras) >= 3 and sum(c.isupper() for c in letras) / len(letras) > 0.9


def indice_proximo_titulo(doc: Document, inicio: int) -> int:
    for i in range(inicio + 1, len(doc.paragraphs)):
        if eh_titulo(doc.paragraphs[i].text):
            return i
    return len(doc.paragraphs)


def remover_intervalo_paragrafos(doc: Document, inicio: int, fim: int) -> None:
    for idx in range(fim - 1, inicio - 1, -1):
        p = doc.paragraphs[idx]._element
        p.getparent().remove(p)


def inserir_texto_apos(doc: Document, indice_titulo: int, texto: str) -> None:
    titulo_elem = doc.paragraphs[indice_titulo]._element
    parent = titulo_elem.getparent()

    linhas = [linha.rstrip() for linha in texto.splitlines()]
    if not linhas:
        linhas = [""]

    for linha in reversed(linhas):
        novo_par = doc.add_paragraph(linha)
        parent.insert(parent.index(titulo_elem) + 1, novo_par._element)


def substituir_secao(doc: Document, titulo: str, novo_conteudo: str) -> None:
    idx_titulo = encontrar_indice_secao(doc, titulo)
    idx_proximo_titulo = indice_proximo_titulo(doc, idx_titulo)
    if idx_proximo_titulo > idx_titulo + 1:
        remover_intervalo_paragrafos(doc, idx_titulo + 1, idx_proximo_titulo)
    inserir_texto_apos(doc, idx_titulo, novo_conteudo)


def main() -> int:
    args = parse_args()

    for caminho in (args.docx_original, args.resultados, args.consideracoes):
        if not caminho.exists() or not caminho.is_file():
            print(f"Erro: arquivo não encontrado: '{caminho}'.", file=sys.stderr)
            return 2

    try:
        texto_resultados = carregar_texto(args.resultados)
        texto_consideracoes = carregar_texto(args.consideracoes)

        doc = Document(args.docx_original)
        substituir_secao(doc, "RESULTADOS E DISCUSSÃO", texto_resultados)
        substituir_secao(doc, "CONSIDERAÇÕES", texto_consideracoes)

        args.saida_dir.mkdir(parents=True, exist_ok=True)
        saida = args.saida_dir / f"{args.docx_original.stem}_final.docx"
        doc.save(saida)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Erro inesperado ao processar DOCX: {exc}", file=sys.stderr)
        return 1

    print(f"Relatório final salvo em: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
