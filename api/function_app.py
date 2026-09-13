"""
Azure Function del Oráculo — punto de entrada del webhook de Flink.

Recibe la alerta de que un buque está a <12h de un puerto y devuelve la
recomendación de velocidad JIT, publicándola de paso en Supabase y ADLS
(ver math_oracle.publicar_recomendacion). Este módulo NO calcula nada:
valida la entrada, invoca el grafo y traduce el resultado a HTTP.

Cuerpo de la petición (POST, JSON) — el mismo objeto que produce Flink y
que consume el replay:

    {
      "paquete_1": { "mmsi": ..., "imo": ..., "puerto": "ALGECIRAS", ... },
      "paquete_2": { "puerto": "ALGECIRAS", "estados": { ... } }
    }

Por qué el proceso es SÍNCRONO
------------------------------
Se calcula dentro de la propia petición y se responde con el resultado,
en vez de devolver 202 y seguir trabajando en segundo plano. El host
puede congelar o reciclar la instancia en cuanto la respuesta HTTP sale,
así que un hilo de fondo (el equivalente al BackgroundTasks de FastAPI)
se perdería en silencio, sin traza y sin reintento: justo el fallo que
no se ve hasta que faltan filas.

El coste de esperar es asumible: el pipeline ronda los 2,5-5 s medidos y
el timeout de un HTTP trigger son 230 s. Si en algún momento la latencia
molesta al llamador, el camino correcto NO es un hilo: es encolar
(Storage Queue con queue trigger, o Service Bus), que da durabilidad,
reintento y control de concurrencia. Por eso el trabajo real vive en
`_procesar_alerta`, para que ese cambio sea añadir un trigger que la
llame, no reescribir el endpoint.

Nota de despliegue (Flex Consumption): la memoria de instancia y la
concurrencia por instancia se fijan con `az functionapp scale config set`,
NO en host.json — ahí `extensions.http.maxConcurrentRequests` se ignora.
Como se factura memoria x tiempo, esa pareja de valores es lo que decide
el coste por alerta; el detalle está en .github/workflows/deploy_function.yml.

Códigos de respuesta
--------------------
200  recomendación calculada y publicada (cuerpo = oracle_recommendation_v1)
400  cuerpo ausente, no-JSON o sin paquete_1/paquete_2
422  alerta no aplicable (buque atracado o parado; BuqueNoNavegandoError)
500  fallo inesperado del pipeline

El 422 es deliberado y distinto del 500: una alerta de un buque parado no
es un error del sistema, y quien llame no debe reintentarla.
"""

from __future__ import annotations

import json
import logging

from pathlib import Path

import azure.functions as func

from app.agents.math_oracle import BuqueNoNavegandoError, oracle_graph
from app.config import ENV_SLUG, NAUTIQ_ENV, TABLA_RECOMENDACIONES

logger = logging.getLogger("nautiq.oraculo")


def _leer_build() -> str:
    """
    Identificador del build desplegado, para saber QUÉ código está
    corriendo ahora mismo en la app.

    Lo escribe el workflow con el SHA del commit justo antes de empaquetar
    (ver .github/workflows/deploy_function.yml). Sin esto no hay forma de
    distinguir un despliegue de otro: dos versiones distintas del código
    responden igual mientras no cambie el comportamiento observable, así
    que "¿ha llegado mi cambio?" se vuelve incontestable desde fuera.

    Devuelve "local" cuando el fichero no existe — que es el caso de un
    `func azure functionapp publish` a mano o de una ejecución en local.
    """
    try:
        return (Path(__file__).parent / "BUILD_INFO").read_text(encoding="utf-8").strip() or "local"
    except OSError:
        return "local"


BUILD = _leer_build()

# google-genai loguea cada POST al endpoint y avisa en cada llamada sobre
# "automatic function calling" (que aquí no se usa). En Application Insights
# eso es ruido de pago: se silencia igual que en scripts/replay_alertas.py.
# Los fallos reales llegan como excepción y los registra llm_provider.
logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

app = func.FunctionApp()


def _construir_config_llm() -> dict:
    """
    Cadena de proveedores de LLM (Gemini -> Foundry -> resumen
    determinista), construida UNA vez por instancia y reutilizada en las
    invocaciones calientes: crear los clientes por petición añadiría
    handshake TLS a cada alerta sin ganar nada.

    Si la construcción falla (SDK ausente, configuración a medias) se
    sigue sin LLM en vez de tumbar el arranque del Function App: el
    oráculo produce igualmente su resumen determinista, y perder el
    texto bonito es mucho menos grave que no responder al webhook.
    """
    try:
        from app.agents.tools.llm_provider import crear_generar_texto_desde_entorno

        generar_texto = crear_generar_texto_desde_entorno()
    except Exception:
        logger.exception(
            "No se pudo montar la cadena de LLM; se seguirá con el resumen determinista"
        )
        return {}

    return {"configurable": {"generar_texto": generar_texto}} if generar_texto else {}


_CONFIG_LLM = _construir_config_llm()

logger.info(
    "Oráculo iniciado — NAUTIQ_ENV=%s, tabla=%s, carpeta ADLS=%s/, LLM=%s",
    NAUTIQ_ENV, TABLA_RECOMENDACIONES, ENV_SLUG, bool(_CONFIG_LLM),
)


def _procesar_alerta(alerta: dict) -> dict:
    """
    Ejecuta el grafo sobre una alerta ya validada y devuelve el evento
    con forma oracle_recommendation_v1.

    Separada del handler HTTP a propósito: es el único punto que
    necesitaría un futuro trigger de cola, y así el cambio de transporte
    no toca la lógica.
    """
    resultado = oracle_graph.invoke(
        {"paquete_1": alerta["paquete_1"], "paquete_2": alerta["paquete_2"]},
        config=_CONFIG_LLM,
    )
    return resultado["evento_contrato"]


def _respuesta(cuerpo: dict, status: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(cuerpo, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
    )


#: Campos de paquete_1 que el grafo lee con acceso directo (no con .get) y sin
#: los cuales revienta. El resto son opcionales y degradan con elegancia.
CAMPOS_OBLIGATORIOS = (
    "puerto", "lat_buque", "lon_buque", "lat_port", "lon_port", "velocidad_buque",
)


def _campos_que_faltan(paquete_1: dict) -> list[str]:
    """
    Campos obligatorios ausentes o nulos en paquete_1.

    Se comprueban por adelantado en vez de dejar que falten dentro del
    grafo: allí producen un KeyError dos o tres nodos más adentro, que
    sale como 500 con un mensaje que no señala el campo. Aquí sale un 400
    nombrándolo, que es la diferencia entre diagnosticar un cambio de
    contrato del productor en un minuto o en una tarde.

    Es una comprobación de PRESENCIA, no de tipo: el objetivo es detectar
    que el emisor ha cambiado el contrato, no validar cada valor.
    """
    return [c for c in CAMPOS_OBLIGATORIOS if paquete_1.get(c) is None]


@app.route(route="alerta", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def alerta(req: func.HttpRequest) -> func.HttpResponse:
    """Webhook de Flink: una alerta por petición."""
    try:
        alerta_json = req.get_json()
    except ValueError:
        logger.warning("Petición con cuerpo ausente o no-JSON")
        return _respuesta({"error": "El cuerpo debe ser JSON válido"}, 400)

    if not isinstance(alerta_json, dict) or not alerta_json.get("paquete_1") or not alerta_json.get("paquete_2"):
        logger.warning("Petición sin paquete_1 y/o paquete_2")
        return _respuesta(
            {"error": "Se esperan las claves 'paquete_1' y 'paquete_2' en el cuerpo"}, 400
        )

    if not isinstance(alerta_json["paquete_1"], dict):
        return _respuesta({"error": "'paquete_1' debe ser un objeto"}, 400)

    faltan = _campos_que_faltan(alerta_json["paquete_1"])
    if faltan:
        logger.warning("paquete_1 sin los campos obligatorios: %s", ", ".join(faltan))
        return _respuesta(
            {"error": f"Faltan campos obligatorios en paquete_1: {', '.join(faltan)}",
             "campos_faltantes": faltan},
            400,
        )

    mmsi = alerta_json["paquete_1"].get("mmsi")
    puerto = alerta_json["paquete_1"].get("puerto")

    try:
        evento = _procesar_alerta(alerta_json)
    except BuqueNoNavegandoError as exc:
        # No es un fallo: el buque está atracado o parado y no hay
        # velocidad que recomendar. 422 para que el llamador NO reintente.
        logger.info("Alerta descartada (mmsi=%s, puerto=%s): %s", mmsi, puerto, exc)
        return _respuesta({"descartada": True, "motivo": str(exc)}, 422)
    except Exception as exc:  # noqa: BLE001 — se registra y se traduce a 500
        logger.exception("Fallo procesando la alerta (mmsi=%s, puerto=%s)", mmsi, puerto)
        return _respuesta({"error": f"{type(exc).__name__}: {exc}"}, 500)

    logger.info(
        "Recomendación publicada: event_id=%s mmsi=%s puerto=%s v=%skn espera=%sh",
        evento["event_id"], mmsi, puerto,
        evento["recommendation"]["recommended_speed_kn"],
        evento["queue"]["estimated_wait_hours"],
    )
    return _respuesta(evento, 200)


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Sonda de vida. Anónima a propósito (la usan probes y monitorización)
    y por eso NO revela secretos ni hosts: solo a qué entorno apunta esta
    instancia, que es justo el dato que evita el error de tener la
    Function de producción escribiendo en las tablas de dev.
    """
    return _respuesta(
        {
            "estado": "ok",
            "entorno": NAUTIQ_ENV,
            "tabla_recomendaciones": TABLA_RECOMENDACIONES,
            "carpeta_adls": f"{ENV_SLUG}/",
            "llm_configurado": bool(_CONFIG_LLM),
            # SHA del commit desplegado ("local" si se publicó a mano):
            # permite confirmar QUÉ versión está corriendo sin adivinar.
            "build": BUILD,
        },
        200,
    )
