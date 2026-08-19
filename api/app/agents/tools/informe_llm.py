"""
Resumen en lenguaje natural del informe de Adaptive Slow Steaming
(math_oracle.build_informe) — agnóstico al proveedor/modelo de LLM.

Este módulo NO importa ningún SDK de proveedor concreto (Anthropic,
OpenAI, LangChain chat models...): construye el prompt y expone un
punto de inyección (`generar_texto: Callable[[str], str]`) para que
quien orqueste el grafo (math_oracle) decida qué modelo usar — sin que
este módulo ni math_oracle.py tengan que cambiar cuando se elija.

Expone DOS pares de funciones (ahorro / alerta) en vez de una sola con
un `if` interno: la decisión de cuál usar (¿el CII con velocidad JIT
mejora o empeora respecto al inicial?) vive en el grafo de math_oracle
como una arista condicional real (add_conditional_edges), no escondida
dentro de una función — así el grafo expresa de verdad una rama, en
vez de ser una cadena fija que solo varía su texto de salida.

Si no se inyecta ningún `generar_texto` (todavía no se ha decidido
modelo), se usa un resumen determinista sin LLM, para que el grafo
siga siendo ejecutable de punta a punta.
"""

from __future__ import annotations

from typing import Callable, Optional


def _formato_horas(h: Optional[float]) -> str:
    if h is None:
        return "—"
    return f"{h:.1f} h"


def _datos_comunes(informe: dict) -> str:
    buque = informe["buque"]
    cola = informe["cola_puerto"]
    velocidad = informe["velocidad"]
    cii = informe["cii"]

    return f"""- Buque: MMSI {buque.get('mmsi')}, IMO {buque.get('imo')}, destino {buque.get('puerto_destino')}
- Tiempo de espera hasta atraque libre: {_formato_horas(cola.get('tiempo_espera_estimado_h'))} \
(posición {cola.get('posicion_cola')} en la cola del segmento {cola.get('segmento_atraque')})
- Velocidad actual: {velocidad.get('actual_kn')} kn
- Velocidad de diseño estimada del buque: {velocidad.get('diseno_kn')} kn
- Velocidad JIT recomendada: {velocidad.get('jit_recomendada_kn')} kn \
(tránsito estimado {_formato_horas(velocidad.get('tiempo_transito_estimado_h'))}, \
pérdida por meteo {velocidad.get('perdida_kwon_media_pct')}%{", SUPERA la velocidad de diseño" if velocidad.get('excede_v_diseno') else ""})
- CII inicial: {cii.get('inicial')} gCO2/(t·nm)
- CII con velocidad JIT: {cii.get('jit')} gCO2/(t·nm)
- Variación de CII: {cii.get('ahorro_pct')}%"""


# ──────────────────────────────────────────────────────────────────────
#  Caso "ahorro": el CII mejora con la velocidad JIT
# ──────────────────────────────────────────────────────────────────────

def construir_prompt_ahorro(informe: dict) -> str:
    """Prompt para el caso en que el CII mejora con la velocidad JIT."""
    return f"""Eres un asistente que resume para un oficial de operaciones
portuarias el resultado de una recomendación de velocidad JIT (Just-In-Time)
para reducir emisiones. Con los datos de abajo, escribe un resumen breve
(3-5 frases, español, tono profesional y directo) que destaque:
  1. El tiempo de espera hasta que haya atraque libre para este buque.
  2. La velocidad de motor recomendada frente a la actual.
  3. El ahorro de CII conseguido con la velocidad JIT.

Datos:
{_datos_comunes(informe)}
"""


def _resumen_sin_llm_ahorro(informe: dict) -> str:
    cola = informe["cola_puerto"]
    velocidad = informe["velocidad"]
    cii = informe["cii"]
    return (
        f"Atraque libre en {_formato_horas(cola.get('tiempo_espera_estimado_h'))}. "
        f"Velocidad recomendada: {velocidad.get('jit_recomendada_kn')} kn "
        f"(actual: {velocidad.get('actual_kn')} kn). "
        f"Ahorro de CII estimado: {cii.get('ahorro_pct')}%."
    )


def resumen_ahorro(informe: dict, generar_texto: Optional[Callable[[str], str]] = None) -> dict:
    """Resumen para el caso en que el CII mejora con la velocidad JIT."""
    prompt = construir_prompt_ahorro(informe)
    texto = generar_texto(prompt) if generar_texto else _resumen_sin_llm_ahorro(informe)
    return {"texto": texto, "prompt": prompt, "alerta_cii": False}


# ──────────────────────────────────────────────────────────────────────
#  Caso "alerta": el CII empeora con la velocidad JIT
# ──────────────────────────────────────────────────────────────────────
# No es un error de cálculo: normalmente significa que la ventana de
# espera en puerto es tan ajustada que el buque tiene que ACELERAR
# respecto a su velocidad actual para llegar a tiempo, en vez de poder
# reducir velocidad (slow steaming).

def construir_prompt_alerta(informe: dict) -> str:
    """Prompt para el caso en que el CII empeora con la velocidad JIT."""
    return f"""Eres un asistente que resume para un oficial de operaciones
portuarias el resultado de una recomendación de velocidad JIT (Just-In-Time).
En este caso el CII con la velocidad recomendada es PEOR (mayor) que el CII
inicial. Esto no es un error de cálculo: normalmente significa que la
ventana de espera en puerto es tan ajustada que el buque tiene que ACELERAR
respecto a su velocidad actual para llegar a tiempo, en vez de poder reducir
velocidad (slow steaming). Con los datos de abajo, escribe un resumen breve
(3-5 frases, español, tono profesional y directo) que:
  1. Indique el tiempo de espera hasta que haya atraque libre para este buque.
  2. Deje claro que el CII empeora con la velocidad recomendada y por qué
     (ventana de espera demasiado ajustada para aplicar slow steaming).
  3. Aclare que la velocidad recomendada sigue siendo necesaria para no
     perder el turno de atraque, aunque no suponga un ahorro de combustible.
No lo presentes como un ahorro ni como un éxito de la recomendación.

Datos:
{_datos_comunes(informe)}
"""


def _resumen_sin_llm_alerta(informe: dict) -> str:
    cola = informe["cola_puerto"]
    velocidad = informe["velocidad"]
    cii = informe["cii"]
    ahorro_pct = cii.get("ahorro_pct")
    empeora_pct = abs(ahorro_pct) if ahorro_pct is not None else "?"
    aviso_diseno = (
        f" Además, {velocidad.get('jit_recomendada_kn')} kn supera la velocidad "
        f"de diseño estimada del buque ({velocidad.get('diseno_kn')} kn)."
        if velocidad.get("excede_v_diseno") else ""
    )
    return (
        f"Atraque libre en {_formato_horas(cola.get('tiempo_espera_estimado_h'))}. "
        f"AVISO: el CII empeora un {empeora_pct}% con la velocidad recomendada "
        f"({velocidad.get('jit_recomendada_kn')} kn, actual: {velocidad.get('actual_kn')} kn) "
        "— la ventana de espera es demasiado ajustada para aplicar slow "
        "steaming; la velocidad recomendada evita perder el atraque, no "
        f"ahorra combustible.{aviso_diseno}"
    )


def resumen_alerta(informe: dict, generar_texto: Optional[Callable[[str], str]] = None) -> dict:
    """Resumen para el caso en que el CII empeora con la velocidad JIT."""
    prompt = construir_prompt_alerta(informe)
    texto = generar_texto(prompt) if generar_texto else _resumen_sin_llm_alerta(informe)
    return {"texto": texto, "prompt": prompt, "alerta_cii": True}
