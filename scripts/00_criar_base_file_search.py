#!/usr/bin/env python3
"""Cria/atualiza base de conhecimento no File Search (Vector Store) da OpenAI."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

NOME_VECTOR_STORE = "relatorios_frv_base"
DIRETORIOS_BASE = [
    Path("base_conhecimento/estilo"),
    Path("base_conhecimento/estatistica"),
    Path("base_conhecimento/regras_tecnicas"),
    Path("base_conhecimento/exemplos_relatorios"),
]
CATALOGO_RELATORIOS = Path("catalogo_relatorios.csv")
CONFIG_MODELOS = Path("config/modelos.json")
LOG_UPLOAD = Path("saida/logs_revisao/upload_base.json")

EXTENSOES_COMPATIVEIS = {
    ".txt", ".md", ".pdf", ".doc", ".docx", ".csv", ".json", ".html", ".xml"
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cria/atualiza vector store com arquivos da base de conhecimento."
    )
    parser.add_argument(
        "--modelo-config-key",
        default="file_search",
        help="Chave em config/modelos.json para salvar vector_store_id (padrão: file_search).",
    )
    return parser.parse_args()


def sha256_arquivo(caminho: Path) -> str:
    hasher = hashlib.sha256()
    with caminho.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def carregar_catalogo(caminho_csv: Path) -> dict[str, dict[str, str]]:
    if not caminho_csv.exists() or not caminho_csv.is_file():
        return {}

    with caminho_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        metadados: dict[str, dict[str, str]] = {}
        for row in reader:
            normalizada = {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items()}
            for chave_nome in ("arquivo", "arquivo_relatorio", "nome_arquivo", "file_name", "filename"):
                nome = normalizada.get(chave_nome)
                if nome:
                    metadados[nome] = normalizada
                    break
        return metadados


def coletar_arquivos() -> tuple[list[Path], list[str]]:
    arquivos: list[Path] = []
    avisos: list[str] = []

    for pasta in DIRETORIOS_BASE:
        if not pasta.exists() or not pasta.is_dir():
            avisos.append(f"Diretório não encontrado: {pasta}")
            continue
        for caminho in sorted(pasta.rglob("*")):
            if caminho.is_file() and caminho.suffix.lower() in EXTENSOES_COMPATIVEIS:
                arquivos.append(caminho)
    return arquivos, avisos


def obter_ou_criar_vector_store(client: OpenAI, nome: str) -> Any:
    for vs in client.vector_stores.list(limit=100).data:
        if vs.name == nome:
            return vs
    return client.vector_stores.create(name=nome)


def mapear_arquivos_existentes(client: OpenAI, vector_store_id: str) -> dict[str, dict[str, Any]]:
    existentes: dict[str, dict[str, Any]] = {}
    pagina = client.vector_stores.files.list(vector_store_id=vector_store_id, limit=100)
    while True:
        for item in pagina.data:
            attrs = getattr(item, "attributes", None) or {}
            origem = attrs.get("source_path")
            hash_ = attrs.get("sha256")
            if origem and hash_:
                existentes[f"{origem}|{hash_}"] = {"vector_store_file_id": item.id, "file_id": item.id}
        if not getattr(pagina, "has_more", False):
            break
        pagina = client.vector_stores.files.list(
            vector_store_id=vector_store_id,
            limit=100,
            after=pagina.data[-1].id,
        )
    return existentes


def salvar_vector_store_config(caminho: Path, chave: str, vector_store_id: str) -> None:
    dados: dict[str, Any] = {}
    if caminho.exists() and caminho.is_file():
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dados = {}

    if chave not in dados or not isinstance(dados[chave], dict):
        dados[chave] = {}

    dados[chave]["vector_store_id"] = vector_store_id

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def salvar_log(caminho: Path, log: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("Erro: variável de ambiente OPENAI_API_KEY não definida.", file=sys.stderr)
        return 2

    client = OpenAI()
    arquivos, avisos = coletar_arquivos()
    catalogo = carregar_catalogo(CATALOGO_RELATORIOS)

    log: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "vector_store": {"name": NOME_VECTOR_STORE, "id": None},
        "totais": {
            "arquivos_encontrados": len(arquivos),
            "enviados": 0,
            "ignorados_ja_existentes": 0,
            "falhas": 0,
        },
        "avisos": avisos,
        "arquivos": [],
    }

    try:
        vs = obter_ou_criar_vector_store(client, NOME_VECTOR_STORE)
        log["vector_store"]["id"] = vs.id

        existentes = mapear_arquivos_existentes(client, vs.id)

        for arquivo in arquivos:
            rel_path = str(arquivo.as_posix())
            hash_arquivo = sha256_arquivo(arquivo)
            chave_existente = f"{rel_path}|{hash_arquivo}"

            registro: dict[str, Any] = {
                "arquivo": rel_path,
                "sha256": hash_arquivo,
                "status": "",
                "metadados": {},
            }

            if chave_existente in existentes:
                registro["status"] = "ignorado_ja_existente"
                log["totais"]["ignorados_ja_existentes"] += 1
                log["arquivos"].append(registro)
                continue

            metadata = {
                "source_path": rel_path,
                "sha256": hash_arquivo,
                "categoria": arquivo.parts[1] if len(arquivo.parts) > 1 else "desconhecida",
            }

            if "exemplos_relatorios" in arquivo.parts:
                dados_catalogo = catalogo.get(arquivo.name)
                if dados_catalogo:
                    for k, v in dados_catalogo.items():
                        if len(k) <= 64 and len(v) <= 512 and v:
                            metadata[f"cat_{k.lower().replace(' ', '_')}"] = v

            registro["metadados"] = metadata

            try:
                with arquivo.open("rb") as f:
                    file_obj = client.files.create(file=f, purpose="assistants")

                vs_file = client.vector_stores.files.create(
                    vector_store_id=vs.id,
                    file_id=file_obj.id,
                    attributes=metadata,
                )
                registro["status"] = "enviado"
                registro["file_id"] = file_obj.id
                registro["vector_store_file_id"] = vs_file.id
                log["totais"]["enviados"] += 1
            except Exception as exc:  # noqa: BLE001
                registro["status"] = "falha"
                registro["erro"] = str(exc)
                log["totais"]["falhas"] += 1

            log["arquivos"].append(registro)

        salvar_vector_store_config(CONFIG_MODELOS, args.modelo_config_key, vs.id)
        salvar_log(LOG_UPLOAD, log)
    except Exception as exc:  # noqa: BLE001
        log["erro_fatal"] = str(exc)
        salvar_log(LOG_UPLOAD, log)
        print(f"Erro ao criar/atualizar base: {exc}", file=sys.stderr)
        return 1

    print(f"Vector store pronto: {vs.id}")
    print(f"Log salvo em: {LOG_UPLOAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
