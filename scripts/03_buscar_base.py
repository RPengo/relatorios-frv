#!/usr/bin/env python3
"""Busca trechos técnicos relevantes na base File Search com base na classificação estatística."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

CONFIG_MODELOS = Path("config/modelos.json")
CLASSIFICACAO_PATH = Path("saida/logs_revisao/classificacao_estatistica.json")
SAIDA_TRECHOS = Path("saida/logs_revisao/trechos_base_recuperados.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consulta a base File Search da OpenAI a partir da classificação estatística."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_MODELOS,
        help="Arquivo de configuração com vector_store_id (padrão: config/modelos.json).",
    )
    parser.add_argument(
        "--classificacao",
        type=Path,
        default=CLASSIFICACAO_PATH,
        help=(
            "JSON com a classificação estatística (padrão: "
            "saida/logs_revisao/classificacao_estatistica.json)."
        ),
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=SAIDA_TRECHOS,
        help="Markdown de saída com trechos recuperados (padrão: saida/logs_revisao/trechos_base_recuperados.md).",
    )
    parser.add_argument(
        "--modelo",
        default="gpt-4.1-mini",
        help="Modelo para orquestrar o File Search (padrão: gpt-4.1-mini).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=8,
        help="Número máximo de trechos a recuperar no File Search (padrão: 8).",
    )
    return parser.parse_args()


def carregar_json(caminho: Path) -> dict[str, Any]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Falha ao ler JSON '{caminho}': {exc}") from exc


def obter_vector_store_id(config: dict[str, Any]) -> str:
    bloco_file_search = config.get("file_search")
    if isinstance(bloco_file_search, dict):
        vector_store_id = bloco_file_search.get("vector_store_id")
        if isinstance(vector_store_id, str) and vector_store_id.strip():
            return vector_store_id.strip()

    raise RuntimeError(
        "vector_store_id não encontrado em config/modelos.json na chave 'file_search.vector_store_id'."
    )


def montar_consulta_tecnica(classificacao: dict[str, Any]) -> str:
    cultura = classificacao.get("cultura", "não informado")
    tema = classificacao.get("objetivo", "não informado")
    tipo_analise = classificacao.get("tipo_analise_estatistica", "não informado")
    variaveis = classificacao.get("variaveis_avaliadas") or []
    resultado_significativo = classificacao.get("variaveis_com_efeito_significativo") or []
    resultado_sem_efeito = classificacao.get("variaveis_sem_efeito_significativo") or []

    variaveis_txt = ", ".join(str(v) for v in variaveis) if variaveis else "não informado"
    tipo_resultado = (
        f"com efeito significativo: {', '.join(map(str, resultado_significativo)) or 'nenhuma variável informada'}; "
        f"sem efeito significativo: {', '.join(map(str, resultado_sem_efeito)) or 'nenhuma variável informada'}"
    )

    return (
        "Recupere conteúdos técnicos e exemplos de redação para relatório agronômico com os seguintes critérios:\n"
        f"- cultura: {cultura}\n"
        f"- tema: {tema}\n"
        f"- tipo de análise: {tipo_analise}\n"
        f"- variáveis principais: {variaveis_txt}\n"
        f"- tipo de resultado: {tipo_resultado}\n\n"
        "Priorize regras de interpretação estatística, padrões de escrita técnica e exemplos aplicáveis "
        "a Resultados e Discussão."
    )


def extrair_texto_resposta(resposta: Any) -> str:
    texto = getattr(resposta, "output_text", None)
    if isinstance(texto, str) and texto.strip():
        return texto.strip()

    blocos: list[str] = []
    for item in getattr(resposta, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text_value = getattr(content, "text", None)
            if isinstance(text_value, str) and text_value.strip():
                blocos.append(text_value.strip())
    if blocos:
        return "\n\n".join(blocos)

    raise RuntimeError("A resposta da API não contém texto interpretável.")


def buscar_trechos(modelo: str, vector_store_id: str, consulta: str, max_results: int) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")

    client = OpenAI()
    resposta = client.responses.create(
        model=modelo,
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
                "max_num_results": max_results,
            }
        ],
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Use SOMENTE o conteúdo recuperado do File Search para responder. "
                            "Liste exemplos práticos e regras técnicas relevantes ao caso abaixo, "
                            "em tópicos claros.\n\n"
                            f"{consulta}"
                        ),
                    }
                ],
            }
        ],
    )
    return extrair_texto_resposta(resposta)


def salvar_markdown(caminho_saida: Path, consulta: str, resposta: str) -> None:
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    conteudo = (
        "# Trechos recuperados da base\n\n"
        f"_Gerado em: {datetime.now(timezone.utc).isoformat()}_\n\n"
        "## Consulta técnica utilizada\n\n"
        f"{consulta}\n\n"
        "## Conteúdo recuperado\n\n"
        f"{resposta}\n"
    )
    caminho_saida.write_text(conteudo, encoding="utf-8")


def main() -> int:
    args = parse_args()

    if not args.config.exists() or not args.config.is_file():
        print(f"Erro: arquivo de configuração não encontrado: '{args.config}'.", file=sys.stderr)
        return 2

    if not args.classificacao.exists() or not args.classificacao.is_file():
        print(f"Erro: classificação não encontrada: '{args.classificacao}'.", file=sys.stderr)
        return 2

    try:
        config = carregar_json(args.config)
        classificacao = carregar_json(args.classificacao)
        vector_store_id = obter_vector_store_id(config)
        consulta = montar_consulta_tecnica(classificacao)
        trechos = buscar_trechos(args.modelo, vector_store_id, consulta, args.max_results)
        salvar_markdown(args.saida, consulta, trechos)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"Busca concluída com sucesso. Trechos salvos em: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
