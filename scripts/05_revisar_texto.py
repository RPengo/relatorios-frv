#!/usr/bin/env python3
"""Revisa tecnicamente os textos gerados com base nas tabelas e na classificação estatística."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

SCHEMA_REVISAO = {
    "name": "revisao_tecnica",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "avaliacao_geral": {"type": "string"},
            "consistencia_estatistica": {"type": "string"},
            "tratamento_nao_significativo": {"type": "string"},
            "itens_problematicos": {"type": "array", "items": {"type": "string"}},
            "correcoes_obrigatorias": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "avaliacao_geral",
            "consistencia_estatistica",
            "tratamento_nao_significativo",
            "itens_problematicos",
            "correcoes_obrigatorias",
        ],
    },
    "strict": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revisa tecnicamente os textos antes da inserção no relatório.")
    parser.add_argument("--dados-relatorio", type=Path, default=Path("entrada/tabelas_extraidas/tabelas_extraidas.json"))
    parser.add_argument("--classificacao", type=Path, default=Path("saida/logs_revisao/classificacao_estatistica.json"))
    parser.add_argument("--resultados", type=Path, default=Path("saida/textos_gerados/resultados_discussao.md"))
    parser.add_argument("--consideracoes", type=Path, default=Path("saida/textos_gerados/consideracoes.md"))
    parser.add_argument("--saida", type=Path, default=Path("saida/logs_revisao/revisao_tecnica.md"))
    parser.add_argument("--modelo", default="gpt-4.1-mini")
    return parser.parse_args()


def carregar_json(caminho: Path) -> dict[str, Any]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler JSON '{caminho}': {exc}") from exc


def carregar_texto(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler texto '{caminho}': {exc}") from exc


def extrair_numeros(texto: str) -> set[str]:
    numeros = re.findall(r"\d+(?:[\.,]\d+)?", texto)
    return {n.replace(",", ".") for n in numeros}


def extrair_numeros_tabelas(dados_relatorio: dict[str, Any]) -> set[str]:
    bruto = json.dumps(dados_relatorio, ensure_ascii=False)
    return extrair_numeros(bruto)


def detectar_indicios_significancia(dados_relatorio: dict[str, Any]) -> list[str]:
    bruto = json.dumps(dados_relatorio, ensure_ascii=False).lower()
    indicios = []
    for padrao in ("*", "p<", "p <=", "p-valor", "p valor", "letras", "teste de", "ns"):
        if padrao in bruto:
            indicios.append(padrao)
    return indicios


def revisar_com_llm(modelo: str, dados_relatorio: dict[str, Any], classificacao: dict[str, Any], texto: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")

    prompt = (
        "Você é revisor técnico de estatística experimental agronômica. "
        "Avalie a coerência técnica do texto em relação às tabelas e à classificação estatística. "
        "Se houver extrapolações, causalidade indevida, inversão de significância ou interpretação incorreta, sinalize. "
        "Exija linguagem conservadora para resultados não significativos.\n\n"
        f"TABELAS (JSON):\n{json.dumps(dados_relatorio, ensure_ascii=False)}\n\n"
        f"CLASSIFICAÇÃO ESTATÍSTICA (JSON):\n{json.dumps(classificacao, ensure_ascii=False)}\n\n"
        f"TEXTO A REVISAR:\n{texto}"
    )

    client = OpenAI()
    resposta = client.responses.create(
        model=modelo,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        text={
            "format": {
                "type": "json_schema",
                "name": SCHEMA_REVISAO["name"],
                "schema": SCHEMA_REVISAO["schema"],
                "strict": True,
            }
        },
    )

    try:
        return json.loads(resposta.output[0].content[0].text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao interpretar revisão técnica da OpenAI: {exc}") from exc


def classificar_status(pendencias_criticas: list[str], pendencias_moderadas: list[str]) -> str:
    if pendencias_criticas:
        return "reprovado"
    if pendencias_moderadas:
        return "aprovado com ressalvas"
    return "aprovado"


def main() -> int:
    args = parse_args()
    for caminho in (args.dados_relatorio, args.classificacao, args.resultados, args.consideracoes):
        if not caminho.exists() or not caminho.is_file():
            print(f"Erro: arquivo de entrada não encontrado: '{caminho}'.", file=sys.stderr)
            return 2

    try:
        dados_relatorio = carregar_json(args.dados_relatorio)
        classificacao = carregar_json(args.classificacao)
        texto_resultados = carregar_texto(args.resultados)
        texto_consideracoes = carregar_texto(args.consideracoes)

        texto_unificado = f"## Resultados e Discussão\n{texto_resultados}\n\n## Considerações\n{texto_consideracoes}".strip()

        numeros_texto = extrair_numeros(texto_unificado)
        numeros_tabela = extrair_numeros_tabelas(dados_relatorio)
        numeros_ausentes = sorted(n for n in numeros_texto if n not in numeros_tabela)

        indicios_significancia = detectar_indicios_significancia(dados_relatorio)
        llm = revisar_com_llm(args.modelo, dados_relatorio, classificacao, texto_unificado)

        pendencias_criticas: list[str] = []
        pendencias_moderadas: list[str] = []

        if numeros_ausentes:
            pendencias_criticas.append(
                "Há números no texto que não foram localizados nas tabelas: " + ", ".join(numeros_ausentes)
            )

        if not indicios_significancia:
            pendencias_moderadas.append(
                "Não foram detectados indícios explícitos de apoio estatístico nas tabelas (letras, asteriscos, p-valor ou ns)."
            )

        pendencias_criticas.extend(llm.get("correcoes_obrigatorias", []))
        pendencias_moderadas.extend(llm.get("itens_problematicos", []))

        status = classificar_status(pendencias_criticas, pendencias_moderadas)

        linhas = [
            "# Revisão Técnica de Texto",
            "",
            f"**Classificação final:** {status}",
            "",
            "## Checagens automáticas",
            f"- Números citados no texto: {len(numeros_texto)}",
            f"- Números encontrados nas tabelas: {len(numeros_tabela)}",
            f"- Números no texto ausentes nas tabelas: {len(numeros_ausentes)}",
            f"- Indícios estatísticos detectados nas tabelas: {', '.join(indicios_significancia) if indicios_significancia else 'nenhum'}",
            "",
            "## Parecer técnico (LLM)",
            f"- Avaliação geral: {llm.get('avaliacao_geral', 'não informado')}",
            f"- Consistência estatística: {llm.get('consistencia_estatistica', 'não informado')}",
            f"- Tratamento de não significância: {llm.get('tratamento_nao_significativo', 'não informado')}",
            "",
            "## Pendências",
        ]

        if not pendencias_criticas and not pendencias_moderadas:
            linhas.append("- Nenhuma pendência identificada.")
        else:
            if pendencias_criticas:
                linhas.append("### Correções obrigatórias (reprovação)")
                linhas.extend([f"- {item}" for item in pendencias_criticas])
            if pendencias_moderadas:
                linhas.append("### Ressalvas")
                linhas.extend([f"- {item}" for item in pendencias_moderadas])

        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text("\n".join(linhas).strip() + "\n", encoding="utf-8")
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Revisão técnica concluída. Relatório salvo em: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
