#!/usr/bin/env python3
"""Orquestra o fluxo completo para todos os .docx em entrada/relatorios_novos."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STATUS_APROVADOS = {"aprovado", "aprovado com ressalvas"}

DIR_ENTRADA_RELATORIOS = Path("entrada/relatorios_novos")
DIR_TABELAS = Path("entrada/tabelas_extraidas")
DIR_LOGS = Path("saida/logs_revisao")
DIR_TEXTOS = Path("saida/textos_gerados")
DIR_FINALIZADOS = Path("saida/relatorios_finalizados")
ARQUIVO_REVISAO = DIR_LOGS / "revisao_tecnica.md"
ARQUIVO_RESUMO = DIR_LOGS / "resumo_execucao_pasta.md"


@dataclass
class ResultadoRelatorio:
    nome: str
    sucesso: bool
    motivo: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Executa o fluxo completo de geração (Resultados e Discussão e Considerações) "
            "para todos os .docx em entrada/relatorios_novos."
        )
    )
    parser.add_argument(
        "--manter-saidas-antigas",
        action="store_true",
        help="Não limpa saida/relatorios_finalizados no início da execução.",
    )
    return parser.parse_args()


def garantir_pastas() -> None:
    for pasta in [DIR_ENTRADA_RELATORIOS, DIR_TABELAS, DIR_LOGS, DIR_TEXTOS, DIR_FINALIZADOS]:
        pasta.mkdir(parents=True, exist_ok=True)


def limpar_conteudo_pasta(pasta: Path) -> None:
    if not pasta.exists():
        return
    for item in pasta.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def listar_docx_validos() -> list[Path]:
    return sorted(
        arquivo
        for arquivo in DIR_ENTRADA_RELATORIOS.glob("*.docx")
        if arquivo.is_file() and not arquivo.name.startswith("~$")
    )


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


def processar_relatorio(caminho_docx: Path) -> ResultadoRelatorio:
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

        status = extrair_status_revisao(ARQUIVO_REVISAO)
        print(f"Classificação final da revisão: {status}")

        if status in STATUS_APROVADOS:
            executar_etapa(
                [sys.executable, "scripts/06_inserir_no_docx.py", "--docx-original", str(caminho_docx)],
                "06 - Inserir no DOCX",
            )
            return ResultadoRelatorio(caminho_docx.name, True, "Aprovado e finalizado")

        return ResultadoRelatorio(
            caminho_docx.name,
            False,
            f"Relatório reprovado na revisão (status: {status}).",
        )
    except RuntimeError as exc:
        return ResultadoRelatorio(caminho_docx.name, False, str(exc))


def escrever_resumo(resultados: list[ResultadoRelatorio], finalizados: list[str]) -> None:
    total = len(resultados)
    sucessos = sum(1 for r in resultados if r.sucesso)
    falhas = [r for r in resultados if not r.sucesso]

    linhas = [
        "# Resumo da execução em lote",
        "",
        f"- Total de arquivos encontrados: {total}",
        f"- Total processado com sucesso: {sucessos}",
        f"- Total com falha: {len(falhas)}",
        "",
        "## Arquivos gerados em saida/relatorios_finalizados",
    ]

    if finalizados:
        linhas.extend(f"- {nome}" for nome in finalizados)
    else:
        linhas.append("- Nenhum arquivo gerado.")

    linhas.extend(["", "## Arquivos com erro"])
    if falhas:
        linhas.extend(f"- {falha.nome}: {falha.motivo}" for falha in falhas)
    else:
        linhas.append("- Nenhum erro.")

    ARQUIVO_RESUMO.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    garantir_pastas()

    limpar_conteudo_pasta(DIR_TABELAS)
    limpar_conteudo_pasta(DIR_LOGS)
    limpar_conteudo_pasta(DIR_TEXTOS)
    if not args.manter_saidas_antigas:
        limpar_conteudo_pasta(DIR_FINALIZADOS)

    relatorios = listar_docx_validos()
    if not relatorios:
        print("Nenhum arquivo .docx encontrado em entrada/relatorios_novos.")
        return 0

    print(f"Encontrados {len(relatorios)} relatórios para processar.")

    resultados: list[ResultadoRelatorio] = []
    for indice, docx in enumerate(relatorios, start=1):
        if indice > 1:
            limpar_conteudo_pasta(DIR_TABELAS)
            limpar_conteudo_pasta(DIR_LOGS)
            limpar_conteudo_pasta(DIR_TEXTOS)

        print(f"\nProcessando {indice}/{len(relatorios)}: {docx.name}")
        resultado = processar_relatorio(docx)
        resultados.append(resultado)

        if resultado.sucesso:
            print(f"Concluído: {docx.name}")
        else:
            print(f"Falhou: {docx.name}")
            print(f"Motivo: {resultado.motivo}")

    finalizados = sorted(arq.name for arq in DIR_FINALIZADOS.glob("*.docx") if arq.is_file())
    escrever_resumo(resultados, finalizados)

    total = len(resultados)
    sucessos = sum(1 for r in resultados if r.sucesso)
    falhas = [r for r in resultados if not r.sucesso]

    print("\nResumo final:")
    print(f"- Total de arquivos encontrados: {total}")
    print(f"- Total processado com sucesso: {sucessos}")
    print(f"- Total com falha: {len(falhas)}")
    print("- Arquivos gerados em saida/relatorios_finalizados:")
    if finalizados:
        for nome in finalizados:
            print(f"  - {nome}")
    else:
        print("  - Nenhum arquivo gerado.")

    if falhas:
        print("- Arquivos com erro:")
        for falha in falhas:
            print(f"  - {falha.nome}: {falha.motivo}")

    print(f"\nResumo detalhado salvo em: {ARQUIVO_RESUMO}")
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
