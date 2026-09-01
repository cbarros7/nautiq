"""
Adaptador Gemini para el punto de inyección "generar_texto" de
informe_llm.py / math_oracle.py.

Aísla el SDK concreto (google-genai) del resto del pipeline, que sigue
siendo agnóstico al proveedor: nadie fuera de este módulo importa
`google.genai`. Se usa el SDK nuevo unificado (`google-genai`), no el
antiguo `google-generativeai` (en vías de retirada por parte de
Google)
"""

from __future__ import annotations

import os
from typing import Callable

from google import genai
from dotenv import load_dotenv

load_dotenv()

# Modelo por entorno (GEMINI_MODEL en las variables de entorno): en DEV
# interesa un modelo barato/rápido y en PRO el que se vaya a presentar,
# y son cuentas distintas con cuotas distintas. Va por entorno y no por
# NAUTIQ_ENV en el código porque el par (api_key, modelo) tiene que
# viajar junto: la key de una cuenta no da acceso a los modelos de otra.
#
# OJO al formato: el SDK google-genai quiere el id pelado
# ("gemini-3.5-flash-lite"). El prefijo de proveedor que usan LiteLLM y
# similares ("gemini/gemini-3.5-flash-lite") NO vale aquí y da un 404 de
# modelo no encontrado.
MODELO_POR_DEFECTO = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"


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

    `modelo` de Google AI Studio 
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
