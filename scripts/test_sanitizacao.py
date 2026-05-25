#!/usr/bin/env python3
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

sys.modules['openai'] = types.SimpleNamespace(OpenAI=object)
spec = spec_from_file_location('gerar_texto', Path('scripts/04_gerar_texto.py'))
mod = module_from_spec(spec)
spec.loader.exec_module(mod)

entrada = "Na Tabela 5, houve ausência de diferença (teste F p>0,05), indicada pelo marcador ns. O coeficiente de variação foi baixo, indicando boa precisão. A testemunha produziu 73,8 sc ha⁻¹."
esperado = "Na Tabela 5, houve ausência de diferença. O Controle produziu 73,8 sc ha⁻¹."
saida = mod.normalizar_texto_gerado(entrada)
assert saida == esperado, f"Saída inesperada:\n{saida}\nEsperado:\n{esperado}"
print('OK')
