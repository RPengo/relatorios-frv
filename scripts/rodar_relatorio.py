#!/usr/bin/env python3
"""Orquestra o fluxo completo de geração e revisão de relatório."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

STATUS_APROVADOS = {"aprovado", "aprovado com ressalvas"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa o fluxo completo de geração de relatório.")
    parser.add_argument("arquivo_docx", type=Path, help="Caminho para o arquivo .docx de entrada")
    return parser.parse_args()


def executar_etapa(comando: list[str], descricao: str) -> None:
    print(f"\n==> {descricao}")
    print("$ " + " ".join(comando))
    resultado = subprocess.run(comando, check=False)
    if resultado.returncode != 0:
        raise RuntimeError(f"Etapa falhou ({descricao}) com código {resultado.returncode}.")


def extrair_status_revisao(caminho_revisao: Path) -> str:
    try:
        conteudo = caminho_revisao.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler relatório de revisão em '{caminho_revisao}': {exc}") from exc

    for linha in conteudo.splitlines():
        if "**Classificação final:**" in linha:
            status = linha.split("**Classificação final:**", maxsplit=1)[1].strip().lower()
            if status:
                return status
            break

    raise RuntimeError(
        "Não foi possível identificar a classificação final no relatório de revisão "
        f"'{caminho_revisao}'."
    )


def main() -> int:
    args = parse_args()

    caminho_docx = args.arquivo_docx
    if not caminho_docx.exists() or not caminho_docx.is_file():
        print(f"Erro: arquivo não encontrado: '{caminho_docx}'.", file=sys.stderr)
        return 2

    if caminho_docx.suffix.lower() != ".docx":
        print(f"Erro: o arquivo informado não é .docx: '{caminho_docx}'.", file=sys.stderr)
        return 2

    revisao_path = Path("saida/logs_revisao/revisao_tecnica.md")

    etapas = [
        ([sys.executable, "scripts/01_extrair_docx.py", str(caminho_docx)], "01 - Extrair DOCX"),
        ([sys.executable, "scripts/02_classificar_estatistica.py"], "02 - Classificar estatística"),
        ([sys.executable, "scripts/03_buscar_base.py"], "03 - Buscar base"),
        ([sys.executable, "scripts/04_gerar_texto.py"], "04 - Gerar texto"),
        ([sys.executable, "scripts/05_revisar_texto.py"], "05 - Revisar texto"),
    ]

    try:
        for comando, descricao in etapas:
            executar_etapa(comando, descricao)

        status = extrair_status_revisao(revisao_path)
        print(f"\nClassificação final da revisão: {status}")

        if status in STATUS_APROVADOS:
            executar_etapa(
                [sys.executable, "scripts/06_inserir_no_docx.py", "--docx-original", str(caminho_docx)],
                "06 - Inserir no DOCX",
            )
            print("\nFluxo concluído: Word final gerado com sucesso.")
            return 0

        print("\nFluxo encerrado: relatório reprovado. Word final não será gerado.")
        print(f"Consulte o relatório de revisão em: {revisao_path}")
        return 1
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
