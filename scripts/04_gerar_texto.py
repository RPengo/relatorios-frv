#!/usr/bin/env python3
"""Gera as seções de Resultados e Discussão e Considerações para relatório agronômico."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

SCHEMA_SAIDA = {
    "name": "texto_relatorio",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "resultados_discussao": {"type": "string"},
            "consideracoes_topicos": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["resultados_discussao", "consideracoes_topicos"],
    },
    "strict": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera textos técnicos de Resultados e Discussão e Considerações."
    )
    parser.add_argument(
        "--dados-relatorio",
        type=Path,
        default=Path("entrada/tabelas_extraidas/tabelas_extraidas.json"),
        help="JSON extraído do relatório (padrão: entrada/tabelas_extraidas/tabelas_extraidas.json).",
    )
    parser.add_argument(
        "--classificacao",
        type=Path,
        default=Path("saida/logs_revisao/classificacao_estatistica.json"),
        help="JSON de classificação estatística (padrão: saida/logs_revisao/classificacao_estatistica.json).",
    )
    parser.add_argument(
        "--trechos-base",
        type=Path,
        default=Path("saida/logs_revisao/trechos_base_recuperados.md"),
        help="Trechos recuperados da base (padrão: saida/logs_revisao/trechos_base_recuperados.md).",
    )
    parser.add_argument(
        "--saida-resultados",
        type=Path,
        default=Path("saida/textos_gerados/resultados_discussao.md"),
        help="Arquivo de saída de Resultados e Discussão.",
    )
    parser.add_argument(
        "--saida-consideracoes",
        type=Path,
        default=Path("saida/textos_gerados/consideracoes.md"),
        help="Arquivo de saída de Considerações.",
    )
    parser.add_argument(
        "--modelo",
        default="gpt-4.1-mini",
        help="Modelo OpenAI para geração de texto (padrão: gpt-4.1-mini).",
    )
    return parser.parse_args()


def carregar_json(caminho: Path) -> dict[str, Any]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler JSON '{caminho}': {exc}") from exc


def carregar_markdown(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler markdown '{caminho}': {exc}") from exc


def montar_prompt(dados_relatorio: dict[str, Any], classificacao: dict[str, Any], trechos_base: str) -> str:
    instrucoes = (
        "Você é redator técnico da Fundação Rio Verde para relatórios agronômicos. "
        "Gere APENAS dois conteúdos: (1) RESULTADOS E DISCUSSÃO e (2) CONSIDERAÇÕES em tópicos. "
        "Use exclusivamente as informações presentes nos insumos fornecidos. "
        "NUNCA invente dados, valores, tratamentos, conclusões ou referências. "
        "NUNCA afirme diferença estatística quando tabela/insumo indicar 'ns'. "
        "Separe explicitamente tendência numérica de efeito estatisticamente significativo. "
        "Quando houver efeito significativo, descreva com linguagem técnica e cite as tabelas no texto "
        "(ex.: Tabela 1, Tabela 2). "
        "Quando não houver significância, deixe claro que variações observadas são apenas numéricas. "
        "Adote português brasileiro, tom técnico, objetivo, impessoal e compatível com estilo Fundação Rio Verde. "
        "As CONSIDERAÇÕES devem ser curtas, acionáveis e em lista de tópicos."
    )

    return (
        f"{instrucoes}\n\n"
        "INSUMO 1 - JSON extraído do relatório:\n"
        f"{json.dumps(dados_relatorio, ensure_ascii=False)}\n\n"
        "INSUMO 2 - Classificação estatística:\n"
        f"{json.dumps(classificacao, ensure_ascii=False)}\n\n"
        "INSUMO 3 - Trechos recuperados da base:\n"
        f"{trechos_base}\n\n"
        "Formato esperado:\n"
        "- resultados_discussao: texto corrido com parágrafos e citação de tabelas.\n"
        "- consideracoes_topicos: array de tópicos SEM numeração automática."
    )


def gerar_textos(modelo: str, prompt: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")

    client = OpenAI()
    resposta = client.responses.create(
        model=modelo,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        text={
            "format": {
                "type": "json_schema",
                "name": SCHEMA_SAIDA["name"],
                "schema": SCHEMA_SAIDA["schema"],
                "strict": True,
            }
        },
    )

    try:
        conteudo = resposta.output[0].content[0].text
        return json.loads(conteudo)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao interpretar saída estruturada da OpenAI: {exc}") from exc


def salvar_resultados(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto.strip() + "\n", encoding="utf-8")


def salvar_consideracoes(caminho: Path, topicos: list[str]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"- {topico.strip()}" for topico in topicos if str(topico).strip()]
    caminho.write_text("\n".join(linhas).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    for caminho in (args.dados_relatorio, args.classificacao, args.trechos_base):
        if not caminho.exists() or not caminho.is_file():
            print(f"Erro: arquivo de entrada não encontrado: '{caminho}'.", file=sys.stderr)
            return 2

    try:
        dados_relatorio = carregar_json(args.dados_relatorio)
        classificacao = carregar_json(args.classificacao)
        trechos_base = carregar_markdown(args.trechos_base)
        prompt = montar_prompt(dados_relatorio, classificacao, trechos_base)
        saida = gerar_textos(args.modelo, prompt)

        resultados = str(saida.get("resultados_discussao", "")).strip()
        consideracoes = saida.get("consideracoes_topicos") or []
        if not resultados:
            raise RuntimeError("Campo 'resultados_discussao' retornou vazio.")

        salvar_resultados(args.saida_resultados, resultados)
        salvar_consideracoes(args.saida_consideracoes, consideracoes)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Texto de Resultados e Discussão salvo em: {args.saida_resultados}")
    print(f"Texto de Considerações salvo em: {args.saida_consideracoes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
