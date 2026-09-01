"""
Cadena de proveedores de LLM para el "generar_texto" que consume
informe_llm.py a través de math_oracle.

Por qué existe
--------------
El resumen se genera con el free tier de Gemini, cuyos límites (~15-30
RPM) están por debajo de las ráfagas reales de Flink (hasta 17
alertas/min): los 429 son esperables, no excepcionales. Hasta ahora la
única red era el resumen determinista de informe_llm, que es correcto
pero de plantilla. Con la cadena, antes de caer a plantilla se intenta
Azure AI Foundry (de pago, pero solo se toca cuando Gemini falla, así
que el gasto es proporcional a los fallos, no al tráfico).

Orden: Gemini (gratis) -> Foundry (pago) -> resumen determinista.
El último escalón NO vive aquí: lo pone informe_llm._texto_con_fallback,
que ya degrada a plantilla si el callable que le inyecten revienta. Este
módulo solo encadena proveedores REALES; si todos fallan, deja
propagar la excepción para que informe_llm haga su trabajo y marque
`llm_degradado=True`.

Este módulo es agnóstico al proveedor igual que informe_llm: compone
callables `prompt -> texto`, no importa ningún SDK. Los SDK viven en
gemini_client.py / foundry_client.py.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

GeneradorTexto = Callable[[str], str]


def _texto_utilizable(texto: object) -> bool:
    """
    Una respuesta vacía cuenta como fallo del proveedor, aunque no haya
    lanzado excepción.

    No es teórico: Gemini devuelve `respuesta.text = None` (sin error)
    cuando el filtro de seguridad bloquea la generación, y el SDK de
    Foundry devuelve content vacío si la respuesta se corta por
    `max_tokens` en el primer token. Sin esta comprobación, ese None se
    colaría hasta `recommendation.rationale` del contrato como texto
    válido, sin activar ni el siguiente proveedor ni el resumen
    determinista.
    """
    return isinstance(texto, str) and bool(texto.strip())


def encadenar(proveedores: list[tuple[str, GeneradorTexto]]) -> Optional[GeneradorTexto]:
    """
    Compone varios `generar_texto` en uno solo que los prueba en orden
    hasta que uno devuelva texto utilizable.

    `proveedores` es una lista de (nombre, callable); el nombre solo se
    usa para los logs, que es como se sigue en ejecución qué escalón
    respondió — el contrato de salida no distingue proveedores (solo
    `rationale_degradado`, que marca el caso "ninguno respondió").

    Devuelve None si la lista viene vacía, para que quien inyecte pueda
    tratarlo igual que "sin LLM configurado" (informe_llm ya sabe usar
    el resumen determinista cuando recibe None).

    Si TODOS fallan, se relanza la excepción del último: informe_llm la
    captura y degrada a plantilla marcando `llm_degradado=True`.
    """
    if not proveedores:
        return None

    def generar_texto(prompt: str) -> str:
        ultimo_error: Optional[Exception] = None
        for i, (nombre, proveedor) in enumerate(proveedores):
            try:
                texto = proveedor(prompt)
                if _texto_utilizable(texto):
                    # Se registra SIEMPRE quién sirvió el resumen, también en
                    # el camino feliz: sin esto, "lo generó el primario" solo
                    # se deduce de la AUSENCIA de warnings, que es una señal
                    # frágil (depende de que el SDK del proveedor loguee sus
                    # propias peticiones HTTP). Con respaldo sube a WARNING,
                    # porque implica que el primario está fallando.
                    if i == 0:
                        logger.info("Resumen generado con el proveedor '%s'", nombre)
                    else:
                        logger.warning(
                            "Resumen generado con el proveedor de respaldo '%s' "
                            "(fallaron los %d anteriores)", nombre, i,
                        )
                    return texto
                logger.warning(
                    "El proveedor '%s' devolvió una respuesta vacía; se prueba el siguiente",
                    nombre,
                )
                ultimo_error = RuntimeError(f"{nombre} devolvió una respuesta vacía")
            except Exception as exc:  # noqa: BLE001 — se registra y se prueba el siguiente
                logger.warning(
                    "El proveedor '%s' falló (%s: %s); se prueba el siguiente",
                    nombre, type(exc).__name__, exc,
                )
                ultimo_error = exc

        raise ultimo_error  # type: ignore[misc]  # la lista no está vacía: siempre hay error

    return generar_texto


def crear_generar_texto_desde_entorno() -> Optional[GeneradorTexto]:
    """
    Monta la cadena Gemini -> Foundry con lo que haya configurado en el
    entorno (GEMINI_API_KEY / FOUNDRY_ENDPOINT + FOUNDRY_API_KEY).

    Los SDK se importan aquí dentro, no arriba: así no hace falta tener
    instalados los dos proveedores para usar uno, ni para ejecutar el
    grafo sin LLM.

    Devuelve None si no hay ninguno configurado — informe_llm usará
    entonces el resumen determinista.
    """
    proveedores: list[tuple[str, GeneradorTexto]] = []

    api_key_gemini = os.environ.get("GEMINI_API_KEY")
    if api_key_gemini:
        from app.agents.tools.gemini_client import crear_generar_texto

        proveedores.append(("gemini", crear_generar_texto(api_key_gemini)))

    from app.agents.tools import foundry_client

    if foundry_client.esta_configurado():
        generador_foundry = foundry_client.crear_generar_texto_desde_entorno()
        if generador_foundry is not None:
            proveedores.append(("foundry", generador_foundry))

    if not proveedores:
        logger.info(
            "Sin proveedor de LLM configurado (ni GEMINI_API_KEY ni FOUNDRY_*); "
            "se usará el resumen determinista"
        )
    else:
        logger.info(
            "Cadena de LLM: %s -> resumen determinista",
            " -> ".join(nombre for nombre, _ in proveedores),
        )

    return encadenar(proveedores)
