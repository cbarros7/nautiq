"""
Adaptador Azure AI Foundry para el punto de inyección "generar_texto" de
informe_llm.py / math_oracle.py.

Mismo contrato que gemini_client.py (prompt -> texto) y misma razón de
ser: aislar el SDK concreto (azure-ai-inference) para que el resto del
pipeline siga sin importar ningún SDK de proveedor.

Su papel en el pipeline es de RESPALDO de pago, no de primario: Gemini
free tier va primero y Foundry solo entra cuando aquel falla (ver
llm_provider.crear_generar_texto_desde_entorno). El free tier de Gemini
ronda 15-30 RPM y las ráfagas reales de Flink llegan a 17 alertas/min,
así que los 429 son esperables, no excepcionales.

Se usa el endpoint de inferencia de Foundry (`/models`), que sirve todo
el catálogo (GPT, Llama, Phi, Mistral...) con una sola API key y
cambiando únicamente el nombre del modelo — de ahí que el modelo sea
configurable por entorno (FOUNDRY_MODEL) y no una constante.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional
from urllib.parse import urlparse

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODELO_POR_DEFECTO = os.environ.get("FOUNDRY_MODEL", "gpt-4.1-mini")


def esta_configurado() -> bool:
    """True si hay endpoint y API key de Foundry en el entorno."""
    return bool(os.environ.get("FOUNDRY_ENDPOINT") and os.environ.get("FOUNDRY_API_KEY"))


def _normalizar_endpoint(endpoint: str) -> str:
    """
    Reescribe el endpoint de PROYECTO de Foundry al de INFERENCIA.

    El portal de Foundry enseña de forma prominente el endpoint del
    proyecto (https://<recurso>.services.ai.azure.com/api/projects/<proj>),
    que es el que consume el SDK azure-ai-projects. ChatCompletionsClient
    habla contra el de inferencia (.../models), y si le das el del
    proyecto Azure responde `(BadRequest) API version not supported` —
    un mensaje que apunta a la versión de API y no a la ruta, así que
    se pierde un rato largo buscando en el sitio equivocado.

    Solo se toca esa forma concreta; cualquier otro endpoint se deja
    tal cual, para no romper despliegues serverless o dedicados que
    legítimamente no cuelgan de /models.
    """
    partes = urlparse(endpoint)
    if "/api/projects/" not in partes.path:
        return endpoint

    corregido = f"{partes.scheme}://{partes.netloc}/models"
    logger.warning(
        "FOUNDRY_ENDPOINT apunta al proyecto (%s), no al endpoint de inferencia; "
        "se usa %s en su lugar. Ajusta la variable para quitar este aviso.",
        endpoint, corregido,
    )
    return corregido


def crear_generar_texto(
    api_key: str,
    endpoint: str,
    modelo: str = MODELO_POR_DEFECTO,
    max_tokens: int = 512,
) -> Callable[[str], str]:
    """
    Devuelve una función prompt -> texto que llama a Foundry, con la
    misma firma que gemini_client.crear_generar_texto para que ambas
    sean intercambiables en la cadena de proveedores.

    `endpoint` es la URL del recurso de Foundry terminada en /models,
    p.ej. https://<recurso>.services.ai.azure.com/models

    `max_tokens` acotado a propósito: el resumen son 3-5 frases (ver
    los prompts de informe_llm), y esta es la vía de PAGO — no tiene
    sentido dejar el techo abierto en el camino de respaldo.
    """
    client = ChatCompletionsClient(
        endpoint=_normalizar_endpoint(endpoint),
        credential=AzureKeyCredential(api_key),
    )

    def generar_texto(prompt: str) -> str:
        respuesta = client.complete(
            messages=[UserMessage(content=prompt)],
            model=modelo,
            max_tokens=max_tokens,
        )
        return respuesta.choices[0].message.content

    return generar_texto


def crear_generar_texto_desde_entorno() -> Optional[Callable[[str], str]]:
    """Adaptador de Foundry con la configuración del entorno, o None si no la hay."""
    if not esta_configurado():
        return None
    return crear_generar_texto(
        api_key=os.environ["FOUNDRY_API_KEY"],
        endpoint=os.environ["FOUNDRY_ENDPOINT"],
    )


if __name__ == "__main__":
    generar_texto = crear_generar_texto_desde_entorno()
    if generar_texto is None:
        raise SystemExit("Falta FOUNDRY_ENDPOINT y/o FOUNDRY_API_KEY en el entorno")
    print(generar_texto("Responde solo con 'ok' si me recibes."))
