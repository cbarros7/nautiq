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

Si no se inyecta ningún `generar_texto`, se usa un resumen determinista 
sin LLM, para que el grafo siga siendo ejecutable de punta a punta.

`historial` (opcional): últimas recomendaciones para el mismo
mmsi+puerto (db_conn.get_historial_recomendaciones), para que el LLM
mantenga coherencia entre avisos sucesivos — la alerta se dispara cada
30 min mientras el buque está a <12h del puerto, así que una misma
aproximación genera varios resúmenes.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _formato_horas(h: Optional[float]) -> str:
    if h is None:
        return "—"
    return f"{h:.1f} h"


def _texto_con_fallback(
    prompt: str,
    generar_texto: Optional[Callable[[str], str]],
    fallback: Callable[[dict], str],
    informe: dict,
) -> tuple[str, bool]:
    """
    Llama al LLM y, si falla, degrada al resumen determinista.

    El resumen es lo ÚLTIMO del pipeline: para cuando se llama aquí ya
    se han pagado la ruta, la meteo, el CII y el JIT. Dejar que un 429
    por rate limit (probable: el free tier de Gemini ronda 15-30 RPM y
    las ráfagas reales de Flink llegan a 17 alertas/min), un 5xx
    transitorio o un model_id inválido tumben `oracle_graph.invoke()`
    tiraría todo ese trabajo por el texto de acompañamiento. Mismo
    criterio que las escrituras a Supabase/ADLS en math_oracle: se
    registra y se sigue.

    Devuelve (texto, degradado) — `degradado=True` avisa de que el
    texto NO viene del LLM, para que el consumidor pueda distinguirlo.
    """
    if generar_texto is None:
        return fallback(informe), False

    try:
        return generar_texto(prompt), False
    except Exception:
        logger.exception(
            "La generación del resumen con LLM falló; se degrada al resumen "
            "determinista (el cálculo del oráculo se conserva intacto)"
        )
        return fallback(informe), True


def _formato_historial(historial: Optional[list[dict]]) -> str:
    """
    Compacta el historial de recomendaciones previas (mismo mmsi+puerto,
    ventana reciente — ver db_conn.get_historial_recomendaciones) para
    el prompt: sólo lo necesario para que el LLM mantenga coherencia
    entre avisos sucesivos (se dispara cada 30 min para buques a <12h
    del puerto), no el JSON completo de cada registro.
    """
    if not historial:
        return ""

    lineas = [
        "\nHistorial de recomendaciones previas para este mismo buque y "
        "puerto (más reciente primero — mantén coherencia con ellas; si "
        "la nueva recomendación difiere mucho, explica brevemente por "
        "qué, p.ej. cambió la cola del puerto o la meteo):"
    ]
    for r in historial:
        recomendacion = r["payload"].get("recommendation", {})
        cii = recomendacion.get("cii", {})
        lineas.append(
            f"  - {r['emitted_at']}: velocidad recomendada "
            f"{recomendacion.get('recommended_speed_kn')} kn, ahorro CII "
            f"{cii.get('ahorro_pct')}% — \"{recomendacion.get('rationale')}\""
        )
    return "\n".join(lineas)


def _datos_comunes(informe: dict) -> str:
    buque = informe["buque"]
    cola = informe["cola_puerto"]
    velocidad = informe["velocidad"]
    cii = informe["cii"]
    eta = informe.get("eta", {})

    linea_eta = ""
    if eta.get("inicial_sin_cola"):
        linea_eta = (
            f"\n- ETA inicial a la velocidad actual, sin colas (dato del webhook): "
            f"{eta['inicial_sin_cola']}\n"
            f"- ETA recomendada con velocidad JIT: {eta['recomendada_jit']} "
            f"({'+' if (eta.get('diferencia_h') or 0) >= 0 else ''}{eta.get('diferencia_h')}h "
            "respecto a la inicial)"
        )

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
- Variación de CII: {cii.get('ahorro_pct')}%{linea_eta}"""


# ──────────────────────────────────────────────────────────────────────
#  Caso "ahorro": el CII mejora con la velocidad JIT
# ──────────────────────────────────────────────────────────────────────

def construir_prompt_ahorro(informe: dict, historial: Optional[list[dict]] = None) -> str:
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
{_formato_historial(historial)}
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


def resumen_ahorro(
    informe: dict,
    generar_texto: Optional[Callable[[str], str]] = None,
    historial: Optional[list[dict]] = None,
) -> dict:
    """Resumen para el caso en que el CII mejora con la velocidad JIT."""
    prompt = construir_prompt_ahorro(informe, historial)
    texto, degradado = _texto_con_fallback(
        prompt, generar_texto, _resumen_sin_llm_ahorro, informe
    )
    return {
        "texto": texto,
        "prompt": prompt,
        "alerta_cii": False,
        "llm_degradado": degradado,
    }


# ──────────────────────────────────────────────────────────────────────
#  Caso "alerta": el CII empeora con la velocidad JIT
# ──────────────────────────────────────────────────────────────────────
# No es un error de cálculo: normalmente significa que la ventana de
# espera en puerto es tan ajustada que el buque tiene que ACELERAR
# respecto a su velocidad actual para llegar a tiempo, en vez de poder
# reducir velocidad (slow steaming).

def construir_prompt_alerta(informe: dict, historial: Optional[list[dict]] = None) -> str:
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
{_formato_historial(historial)}
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


def resumen_alerta(
    informe: dict,
    generar_texto: Optional[Callable[[str], str]] = None,
    historial: Optional[list[dict]] = None,
) -> dict:
    """Resumen para el caso en que el CII empeora con la velocidad JIT."""
    prompt = construir_prompt_alerta(informe, historial)
    texto, degradado = _texto_con_fallback(
        prompt, generar_texto, _resumen_sin_llm_alerta, informe
    )
    return {
        "texto": texto,
        "prompt": prompt,
        "alerta_cii": True,
        "llm_degradado": degradado,
    }
