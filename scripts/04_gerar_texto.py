#!/usr/bin/env python3
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


PROIBIDOS_RESULTADOS_DISCUSS = [
    "teste f", "p>0,05", "p<0,05", "p≤0,05", "p<=0,05",
    "marcador ns", "presença do marcador ns", "indicado por ns",
    "coeficiente de variação", "coeficientes de variação", " boa precisão",
    "precisão dos dados", "variabilidade experimental", "margem da variabilidade experimental",
]


def normalizar_texto_gerado(texto: str) -> str:
    txt = (texto or "").replace("\r\n", "\n")
    txt = re.sub(r"\btestemunha\b", "Controle", txt, flags=re.IGNORECASE)
    txt = re.sub(r"\bcontrole\b", "Controle", txt)
    txt = re.sub(r"\((?:teste\s*f\s*)?[pP]\s*[><≤=]\s*0,05\)", "", txt)
    txt = re.sub(r",?\s*indicad[ao]s?\s+pelo?\s+marcador\s+ns\.?", ".", txt, flags=re.IGNORECASE)
    txt = re.sub(r",?\s*presença\s+do\s+marcador\s+ns\.?", ".", txt, flags=re.IGNORECASE)

    frases = re.split(r"(?<=[.!?])\s+", txt)
    limpas = []
    for f in frases:
        fl = f.lower()
        if any(t in fl for t in PROIBIDOS_RESULTADOS_DISCUSS):
            continue
        limpas.append(f)
    txt = " ".join(limpas)

    txt = re.sub(r"\s+([,.;:!?])", r"\1", txt)
    txt = re.sub(r"([.;:!?])(?!\s|$)", r"\1 ", txt)
    txt = re.sub(r"\s{2,}", " ", txt)
    txt = re.sub(r"\.\s*\.", ".", txt)
    txt = re.sub(r"\bA\s+Controle\b", "O Controle", txt)
    if "Na Tabela" in (texto or "") and "Na Tabela" not in txt:
        m = re.search(r"(Na Tabela\s+\d+,[^.]*diferença[^.]*)", texto or "", flags=re.IGNORECASE)
        if m:
            cab = re.sub(r"\((?:teste\s*f\s*)?[pP]\s*[><≤=]\s*0,05\)", "", m.group(1), flags=re.IGNORECASE)
            cab = re.sub(r",?\s*indicad[ao]s?\s+pelo?\s+marcador\s+ns", "", cab, flags=re.IGNORECASE).strip(" ,;.")
            txt = f"{cab}. {txt}".strip()
    return txt.strip()


def normalizar_consideracoes(topicos: list[str]) -> list[str]:
    itens = [str(t).strip(' -\t\n') for t in topicos if str(t).strip()]
    saida = []
    for i, it in enumerate(itens):
        t = re.sub(r"[;.]$", "", it.strip())
        t += "." if i == len(itens)-1 else ";"
        saida.append(t)
    return saida

SCHEMA_SAIDA = {
    "name": "texto_relatorio",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "blocos_resultados": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tipo_anchor": {"type": "string", "enum": ["tabela", "figura", "quadro"]},
                        "numero_anchor": {"type": "integer"},
                        "titulo_detectado": {"type": "string"},
                        "texto": {"type": "string"},
                    },
                    "required": ["tipo_anchor", "numero_anchor", "titulo_detectado", "texto"],
                },
            },
            "consideracoes_topicos": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4},
        },
        "required": ["blocos_resultados", "consideracoes_topicos"],
    },
    "strict": True,
}

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dados-relatorio", type=Path, default=Path("entrada/tabelas_extraidas/tabelas_extraidas.json"))
    p.add_argument("--classificacao", type=Path, default=Path("saida/logs_revisao/classificacao_estatistica.json"))
    p.add_argument("--trechos-base", type=Path, default=Path("saida/logs_revisao/trechos_base_recuperados.md"))
    p.add_argument("--saida-resultados", type=Path, default=Path("saida/textos_gerados/resultados_discussao.md"))
    p.add_argument("--saida-consideracoes", type=Path, default=Path("saida/textos_gerados/consideracoes.md"))
    p.add_argument("--saida-blocos", type=Path, default=Path("saida/textos_gerados/resultados_discussao_blocos.json"))
    p.add_argument("--modelo", default="gpt-4.1-mini")
    return p.parse_args()

def carregar_json(c: Path) -> dict[str, Any]: return json.loads(c.read_text(encoding='utf-8'))
def carregar_markdown(c: Path) -> str: return c.read_text(encoding='utf-8')

def _detectar_anchors(dados: dict[str, Any]) -> list[dict[str, Any]]:
    txt = json.dumps(dados, ensure_ascii=False)
    encontrados = []
    for m in re.finditer(r"\b(Tabela|Figura|Quadro)\s*(\d+)\b[^\n\"]*", txt, re.IGNORECASE):
        tipo = m.group(1).lower()
        encontrados.append({"tipo_anchor": tipo, "numero_anchor": int(m.group(2)), "titulo_detectado": m.group(0).strip()})
    uniq, seen = [], set()
    for x in encontrados:
        k = (x['tipo_anchor'], x['numero_anchor'])
        if k in seen: continue
        seen.add(k); uniq.append(x)
    uniq.sort(key=lambda a: (a['tipo_anchor'] != 'tabela', a['numero_anchor']))
    return uniq

def _insights_produtividade(dados: dict[str, Any]) -> list[dict[str, Any]]:
    txt = json.dumps(dados, ensure_ascii=False)
    vals = re.findall(r"\b\d+,\d\b", txt)
    if len(vals) < 2:
        return []
    nums = [float(v.replace(',', '.')) for v in vals]
    controle = nums[0]
    difs = [n - controle for n in nums[1:] if n >= controle]
    if not difs:
        return []
    return [{
        "variavel": "Produtividade",
        "unidade": "sc ha⁻¹",
        "casas_decimais": 1,
        "controle": f"{controle:.1f}".replace('.', ','),
        "menor_incremento_produto": f"{min(difs):.1f}".replace('.', ','),
        "maior_incremento_produto": f"{max(difs):.1f}".replace('.', ','),
        "media_incremento_produto": f"{(sum(difs)/len(difs)):.1f}".replace('.', ','),
    }]

def montar_prompt(dados_relatorio: dict[str, Any], classificacao: dict[str, Any], trechos_base: str) -> str:
    anchors = _detectar_anchors(dados_relatorio)
    insights = _insights_produtividade(dados_relatorio)
    return (
        "Gere RESULTADOS E DISCUSSÃO por blocos vinculados a tabela/figura/quadro. "
        "Cada bloco deve discutir apenas variáveis daquele anchor. "
        "Nunca gerar discussão geral única quando houver múltiplas tabelas. "
        "Nunca citar cidade/local. "
        "PROIBIDO em Resultados e Discussão: teste F; p>0,05; p<0,05; P>0,05; P<0,05; P≤0,05; marcador ns; presença do marcador ns; indicado por ns; ns; coeficiente de variação; coeficientes de variação; CV; precisão dos dados; boa precisão experimental; variabilidade experimental como justificativa; margem da variabilidade experimental; testemunha. "
        "Se não houver diferença estatística, escrever apenas 'não houve diferença estatisticamente significativa' e usar 'diferença numérica', 'incremento numérico' ou 'tendência numérica'. "
        "Não explicar marcadores estatísticos da tabela e não mencionar teste F ou p-valor no corpo da discussão. "
        "Usar sempre 'Controle' (C maiúsculo), nunca 'testemunha'. "
        "Nunca use termos promocionais. "
        "Ao citar diferenças numéricas, respeite casas decimais da variável e use vírgula decimal. "
        "Para produtividade, prefira sc ha⁻¹ e use insights_calculados quando disponíveis. "
        f"Considerações devem iniciar com: '{ABERTURA_CONSIDERACOES}' e depois 3-4 tópicos.\n\n"
        f"ANCHORS DETECTADOS:\n{json.dumps(anchors, ensure_ascii=False)}\n\n"
        f"INSIGHTS_CALCULADOS:\n{json.dumps(insights, ensure_ascii=False)}\n\n"
        f"DADOS RELATÓRIO:\n{json.dumps(dados_relatorio, ensure_ascii=False)}\n\n"
        f"CLASSIFICAÇÃO:\n{json.dumps(classificacao, ensure_ascii=False)}\n\n"
        f"BASE:\n{trechos_base}"
    )

def gerar_textos(modelo: str, prompt: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"): raise RuntimeError("A variável de ambiente OPENAI_API_KEY não está definida.")
    rsp = OpenAI().responses.create(model=modelo,input=[{"role":"user","content":[{"type":"input_text","text":prompt}]}],text={"format":{"type":"json_schema","name":SCHEMA_SAIDA['name'],"schema":SCHEMA_SAIDA['schema'],"strict":True}})
    return json.loads(rsp.output[0].content[0].text)

def salvar_resultados(c: Path, blocos: list[dict[str, Any]]):
    c.parent.mkdir(parents=True, exist_ok=True)
    for b in blocos:
        if b.get("texto"):
            b["texto"] = normalizar_texto_gerado(str(b["texto"]))
    texto = "\n\n".join(b.get("texto", "").strip() for b in blocos if b.get("texto", "").strip())
    c.write_text(texto.strip()+"\n", encoding='utf-8')

def salvar_consideracoes(c: Path, tops: list[str]):
    c.parent.mkdir(parents=True, exist_ok=True)
    norm = normalizar_consideracoes(tops)
    linhas=[ABERTURA_CONSIDERACOES,"",*[f"- {t}" for t in norm]]
    c.write_text("\n".join(linhas).strip()+"\n", encoding='utf-8')

def main() -> int:
    a = parse_args()
    for p in (a.dados_relatorio,a.classificacao,a.trechos_base):
        if not p.exists(): print(f"Erro: arquivo de entrada não encontrado: '{p}'.", file=sys.stderr); return 2
    try:
        dados, cls, base = carregar_json(a.dados_relatorio), carregar_json(a.classificacao), carregar_markdown(a.trechos_base)
        saida = gerar_textos(a.modelo, montar_prompt(dados, cls, base))
        blocos = saida.get('blocos_resultados') or []
        if not blocos: raise RuntimeError("Campo 'blocos_resultados' retornou vazio.")
        for bloco in blocos:
            if bloco.get("texto"):
                bloco["texto"] = normalizar_texto_gerado(str(bloco["texto"]))
        a.saida_blocos.parent.mkdir(parents=True, exist_ok=True)
        a.saida_blocos.write_text(json.dumps({"blocos_resultados": blocos, "consideracoes_topicos": saida.get('consideracoes_topicos', [])}, ensure_ascii=False, indent=2)+"\n", encoding='utf-8')
        salvar_resultados(a.saida_resultados, blocos)
        salvar_consideracoes(a.saida_consideracoes, saida.get('consideracoes_topicos') or [])
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr); return 1
    print(f"Blocos de Resultados e Discussão salvos em: {a.saida_blocos}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
