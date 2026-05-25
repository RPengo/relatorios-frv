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

ABERTURA_CONSIDERACOES = "Conforme as condições em que este ensaio foi realizado podemos concluir que:"
PROIBIDOS_RESULTADOS = [
    "lucas do rio verde",
    "lucas do rio verde – mt",
    "lucas do rio verde - mt",
    "coeficiente de variação",
    "coeficientes de variação",
    " cv ",
    "robustez do experimento",
    "consistência dos achados",
]

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

# keep existing helpers

def carregar_json(caminho: Path) -> dict[str, Any]:
    return json.loads(caminho.read_text(encoding="utf-8"))

def carregar_texto(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")

def extrair_numeros(texto: str) -> set[str]:
    numeros = re.findall(r"\d+(?:[\.,]\d+)?", texto)
    return {n.replace(",", ".") for n in numeros}

def extrair_numeros_tabelas(dados_relatorio: dict[str, Any]) -> set[str]:
    return extrair_numeros(json.dumps(dados_relatorio, ensure_ascii=False))

def revisar_com_llm(modelo: str, dados_relatorio: dict[str, Any], classificacao: dict[str, Any], texto: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")
    prompt = (
        "Você é revisor técnico de estatística experimental agronômica. "
        "Reprove conteúdo que viole regras obrigatórias: discussão em parágrafo único com múltiplas tabelas; "
        "menção de cidade/local em resultados; menção de CV/coeficiente de variação na discussão; "
        "não explorar diferenças numéricas de produtividade quando não houver significância; "
        "considerações genéricas sem suporte; duplicidade da frase de abertura das considerações.\n\n"
        f"TABELAS (JSON):\n{json.dumps(dados_relatorio, ensure_ascii=False)}\n\n"
        f"CLASSIFICAÇÃO ESTATÍSTICA (JSON):\n{json.dumps(classificacao, ensure_ascii=False)}\n\n"
        f"TEXTO A REVISAR:\n{texto}"
    )
    client = OpenAI()
    resposta = client.responses.create(
        model=modelo,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        text={"format": {"type": "json_schema", "name": SCHEMA_REVISAO["name"], "schema": SCHEMA_REVISAO["schema"], "strict": True}},
    )
    return json.loads(resposta.output[0].content[0].text)

def contar_tabelas(dados_relatorio: dict[str, Any]) -> int:
    bruto = json.dumps(dados_relatorio, ensure_ascii=False).lower()
    return len(re.findall(r"tabela\s*\d+", bruto)) or bruto.count('"tabela"')

def validar_regras_fixas(resultados: str, consideracoes: str, dados_relatorio: dict[str, Any]) -> list[str]:
    erros = []
    parags = [p.strip() for p in re.split(r"\n\s*\n", resultados) if p.strip()]
    if contar_tabelas(dados_relatorio) >= 2 and len(parags) < 2:
        erros.append("Resultados e Discussão em parágrafo único apesar de múltiplas tabelas.")

    resultados_lower = f" {resultados.lower()} "
    for termo in PROIBIDOS_RESULTADOS:
        if termo in resultados_lower:
            erros.append(f"Resultados e Discussão contém termo proibido: '{termo.strip()}'.")

    if consideracoes.count(ABERTURA_CONSIDERACOES) > 1:
        erros.append("Frase de abertura das considerações está duplicada.")

    linhas_cons = [l.strip() for l in consideracoes.splitlines() if l.strip()]
    topicos = [l for l in linhas_cons if l.startswith("-")]
    if not linhas_cons or linhas_cons[0] != ABERTURA_CONSIDERACOES:
        erros.append("Considerações não iniciam com a frase obrigatória.")
    if len(topicos) < 3 or len(topicos) > 4:
        erros.append("Considerações devem conter de 3 a 4 tópicos.")
    return erros

def classificar_status(criticas: list[str], moderadas: list[str]) -> str:
    return "reprovado" if criticas else ("aprovado com ressalvas" if moderadas else "aprovado")

def main() -> int:
    args = parse_args()
    try:
        dados_relatorio = carregar_json(args.dados_relatorio)
        classificacao = carregar_json(args.classificacao)
        texto_resultados = carregar_texto(args.resultados)
        texto_consideracoes = carregar_texto(args.consideracoes)
        texto_unificado = f"## Resultados e Discussão\n{texto_resultados}\n\n## Considerações\n{texto_consideracoes}".strip()

        criticas = validar_regras_fixas(texto_resultados, texto_consideracoes, dados_relatorio)
        numeros_ausentes = sorted(n for n in extrair_numeros(texto_unificado) if n not in extrair_numeros_tabelas(dados_relatorio))
        if numeros_ausentes:
            criticas.append("Há números no texto que não foram localizados nas tabelas: " + ", ".join(numeros_ausentes))

        llm = revisar_com_llm(args.modelo, dados_relatorio, classificacao, texto_unificado)
        criticas.extend(llm.get("correcoes_obrigatorias", []))
        moderadas = llm.get("itens_problematicos", [])
        status = classificar_status(criticas, moderadas)

        linhas = ["# Revisão Técnica de Texto", "", f"**Classificação final:** {status}", "", "## Pendências"]
        if criticas:
            linhas += ["### Correções obrigatórias (reprovação)"] + [f"- {x}" for x in criticas]
        if moderadas:
            linhas += ["### Ressalvas"] + [f"- {x}" for x in moderadas]
        if not criticas and not moderadas:
            linhas.append("- Nenhuma pendência identificada.")

        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text("\n".join(linhas).strip() + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Revisão técnica concluída. Relatório salvo em: {args.saida}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
