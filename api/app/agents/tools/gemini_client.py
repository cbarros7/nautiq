"""
Adaptador Gemini para el punto de inyección "generar_texto" de
informe_llm.py / math_oracle.py.

Aísla el SDK concreto (google-genai) del resto del pipeline, que sigue
siendo agnóstico al proveedor: nadie fuera de este módulo importa
`google.genai`. Se usa el SDK nuevo unificado (`google-genai`), no el
antiguo `google-generativeai` (en vías de retirada por parte de
Google) — ambos funcionan con una API key simple del nivel gratuito,
sin necesitar modo Vertex AI.
"""

from __future__ import annotations

from typing import Callable

from google import genai

MODELO_POR_DEFECTO = "gemini-2.0-flash"


def crear_generar_texto(
    api_key: str,
    modelo: str = MODELO_POR_DEFECTO,
) -> Callable[[str], str]:
    """
    Devuelve una función prompt -> texto que llama a Gemini, lista para
    inyectar en el grafo vía config:

        oracle_graph.invoke(
            {"paquete_1": ..., "paquete_2": ...},
            config={"configurable": {
                "generar_texto": crear_generar_texto(api_key=GEMINI_API_KEY),
            }},
        )

    `modelo` es el nombre de modelo de la Gemini API (p.ej.
    "gemini-2.0-flash"); comprobar en Google AI Studio qué modelos
    están disponibles en el nivel gratuito de tu API key, ya que la
    disponibilidad/nombres cambian con el tiempo.
    """
    client = genai.Client(api_key=api_key)

    def generar_texto(prompt: str) -> str:
        respuesta = client.models.generate_content(model=modelo, contents=prompt)
        return respuesta.text

    return generar_texto


if __name__ == "__main__":
    import os

    api_key = os.environ["GEMINI_API_KEY"]
    generar_texto = crear_generar_texto(api_key)
    print(generar_texto("Responde solo con 'ok' si me recibes."))
