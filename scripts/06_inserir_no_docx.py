#!/usr/bin/env python3
"""Insere seções geradas em um arquivo DOCX sem alterar o restante do relatório."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.text.paragraph import CT_P
from docx.shared import Pt

ABERTURA_CONSIDERACOES = "Conforme as condições em que este ensaio foi realizado podemos concluir que:"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Substitui conteúdo das seções RESULTADOS E DISCUSSÃO e CONSIDERAÇÕES.")
    parser.add_argument("--docx-original", type=Path, required=True)
    parser.add_argument("--resultados", type=Path, default=Path("saida/textos_gerados/resultados_discussao.md"))
    parser.add_argument("--consideracoes", type=Path, default=Path("saida/textos_gerados/consideracoes.md"))
    parser.add_argument("--saida-dir", type=Path, default=Path("saida/relatorios_finalizados"))
    return parser.parse_args()


def normalizar_titulo(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip().upper()


def carregar_texto(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8").strip()


def encontrar_paragrafo_por_titulo(doc: Document, titulo: str):
    alvo = normalizar_titulo(titulo)
    for p in doc.paragraphs:
        if normalizar_titulo(p.text) == alvo:
            return p
    raise RuntimeError(f"Seção '{titulo}' não encontrada no documento.")


def aplicar_formatacao(paragrafo) -> None:
    fmt = paragrafo.paragraph_format
    paragrafo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    fmt.line_spacing = 1.5
    fmt.first_line_indent = Pt(24)


def inserir_paragrafos_apos(doc: Document, paragrafo_base, blocos: list[str]) -> None:
    parent = paragrafo_base._element.getparent()
    anchor = paragrafo_base._element
    for bloco in reversed(blocos):
        novo = doc.add_paragraph(bloco)
        aplicar_formatacao(novo)
        parent.insert(parent.index(anchor) + 1, novo._element)


def blocos_paragrafos(texto: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]


def substituir_resultados_discussao(doc: Document, texto: str) -> None:
    titulo = encontrar_paragrafo_por_titulo(doc, "RESULTADOS E DISCUSSÃO")
    body = doc._body._element
    idx_titulo = list(body).index(titulo._element)

    remover = []
    for el in list(body)[idx_titulo + 1 :]:
        if isinstance(el, CT_P):
            txt = "".join(el.itertext()).strip()
            if normalizar_titulo(txt) in {"CONSIDERAÇÕES", "REFERÊNCIAS BIBLIOGRÁFICAS"}:
                break
            remover.append(el)
            continue
        break

    for el in remover:
        el.getparent().remove(el)

    inserir_paragrafos_apos(doc, titulo, blocos_paragrafos(texto))


def substituir_consideracoes(doc: Document, texto: str) -> None:
    titulo = encontrar_paragrafo_por_titulo(doc, "CONSIDERAÇÕES")
    ref = encontrar_paragrafo_por_titulo(doc, "REFERÊNCIAS BIBLIOGRÁFICAS")
    body = doc._body._element
    elems = list(body)
    i1, i2 = elems.index(titulo._element), elems.index(ref._element)

    for el in elems[i1 + 1 : i2]:
        el.getparent().remove(el)

    blocos = blocos_paragrafos(texto)
    if not blocos:
        blocos = [ABERTURA_CONSIDERACOES]
    inserir_paragrafos_apos(doc, titulo, blocos)


def main() -> int:
    args = parse_args()
    try:
        texto_resultados = carregar_texto(args.resultados)
        texto_consideracoes = carregar_texto(args.consideracoes)
        doc = Document(args.docx_original)
        substituir_resultados_discussao(doc, texto_resultados)
        substituir_consideracoes(doc, texto_consideracoes)
        args.saida_dir.mkdir(parents=True, exist_ok=True)
        saida = args.saida_dir / f"{args.docx_original.stem}_final.docx"
        doc.save(saida)
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao processar DOCX: {exc}", file=sys.stderr)
        return 1
    print(f"Relatório final salvo em: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
