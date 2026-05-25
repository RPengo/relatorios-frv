#!/usr/bin/env python3
"""Classifica o tipo de análise estatística de um relatório usando a OpenAI API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

SCHEMA_CLASSIFICACAO = {
    "name": "classificacao_estatistica",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cultura": {"type": "string"},
            "objetivo": {"type": "string"},
            "delineamento": {"type": "string"},
            "tipo_analise_estatistica": {"type": "string"},
            "fatores": {
                "type": "array",
                "items": {"type": "string"},
            },
            "teste_media": {"type": "string"},
            "presenca_regressao": {"type": "boolean"},
            "presenca_interacao": {"type": "boolean"},
            "variaveis_avaliadas": {
                "type": "array",
                "items": {"type": "string"},
            },
            "variaveis_com_efeito_significativo": {
                "type": "array",
                "items": {"type": "string"},
            },
            "variaveis_sem_efeito_significativo": {
                "type": "array",
                "items": {"type": "string"},
            },
            "riscos_interpretacao": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "cultura",
            "objetivo",
            "delineamento",
            "tipo_analise_estatistica",
            "fatores",
            "teste_media",
            "presenca_regressao",
            "presenca_interacao",
            "variaveis_avaliadas",
            "variaveis_com_efeito_significativo",
            "variaveis_sem_efeito_significativo",
            "riscos_interpretacao",
        ],
    },
    "strict": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classifica a estatística de um relatório agronômico a partir de JSON extraído do DOCX."
    )
    parser.add_argument(
        "--entrada",
        type=Path,
        default=Path("entrada/tabelas_extraidas/tabelas_extraidas.json"),
        help="JSON de entrada gerado pelo script 01 (padrão: entrada/tabelas_extraidas/tabelas_extraidas.json).",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("saida/logs_revisao/classificacao_estatistica.json"),
        help="JSON de saída da classificação (padrão: saida/logs_revisao/classificacao_estatistica.json).",
    )
    parser.add_argument(
        "--modelo",
        default="gpt-4.1-mini",
        help="Modelo OpenAI usado para classificação (padrão: gpt-4.1-mini).",
    )
    return parser.parse_args()


def carregar_json(caminho_entrada: Path) -> dict[str, Any]:
    try:
        return json.loads(caminho_entrada.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler JSON de entrada '{caminho_entrada}': {exc}") from exc


def montar_prompt(dados_relatorio: dict[str, Any]) -> str:
    instrucoes = (
        "Você é um assistente técnico de estatística experimental agronômica. "
        "Classifique APENAS os elementos estatísticos do relatório com base no JSON fornecido. "
        "Não gere seção de Resultados e Discussão e não invente informações ausentes. "
        "Quando não houver evidência suficiente, use strings como 'não informado'."
    )
    return f"{instrucoes}\n\nJSON DO RELATÓRIO:\n{json.dumps(dados_relatorio, ensure_ascii=False)}"


def classificar_estatistica(modelo: str, dados_relatorio: dict[str, Any]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")

    client = OpenAI()
    resposta = client.responses.create(
        model=modelo,
        input=[{"role": "user", "content": [{"type": "input_text", "text": montar_prompt(dados_relatorio)}]}],
        text={"format": {"type": "json_schema", "name": SCHEMA_CLASSIFICACAO["name"], "schema": SCHEMA_CLASSIFICACAO["schema"], "strict": True}},
    )

    try:
        conteudo = resposta.output[0].content[0].text
        return json.loads(conteudo)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao interpretar Structured Output da OpenAI: {exc}") from exc


def salvar_json(dados: dict[str, Any], caminho_saida: Path) -> None:
    try:
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao salvar saída em '{caminho_saida}': {exc}") from exc


def main() -> int:
    args = parse_args()

    if not args.entrada.exists() or not args.entrada.is_file():
        print(f"Erro: JSON de entrada não encontrado: '{args.entrada}'.", file=sys.stderr)
        return 2

    try:
        dados = carregar_json(args.entrada)
        classificacao = classificar_estatistica(args.modelo, dados)
        salvar_json(classificacao, args.saida)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Classificação concluída com sucesso. JSON salvo em: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
