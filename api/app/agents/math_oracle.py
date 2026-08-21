"""
Grafo del Oráculo Matemático (LangGraph).

Orquesta, como un StateGraph de aristas fijas (sin tool-calling, ver decisión
tomada para el pipeline reactivo), los nodos deterministas que alimentan la
recomendación de Adaptive Slow Steaming. Los cálculos viven como funciones
puras en `sea_route.py` / `open_meteo.py` / `cii_calculus.py` /
`jit_calculus.py` / `kwon_euler.py`; este módulo solo los encadena.

Entrada del grafo: los dos paquetes que llegan del webhook.
  - paquete_1: mensaje individual del buque que dispara el proceso —
    mmsi, imo, puerto destino (nombre, no locode), estado (código AIS
    Navigational Status numérico), lat_buque/lon_buque, lat_port/
    lon_port (el webhook ya manda las coordenadas del puerto, no hace
    falta resolverlas contra ninguna tabla), velocidad_buque,
    dimensiones, tipo_buque (código AIS numérico, ITU-R M.1371),
    ETA_dynamic (horas a la velocidad actual hasta las inmediaciones
    del puerto, SIN contar colas — no se usa en el cálculo, sólo para
    comparar en el informe final), ingest_timestamp (instante de
    referencia del mensaje, confirmado contra fixture real — ver
    fetch_datos_buque) y correlation_id (trazabilidad Kafka/Flink, se
    propaga tal cual en el informe/evento).
  - paquete_2: contrato agregado del estado del puerto (atracados/
    fondeados/en_camino) que consume jit_calculus. Confirmado contra
    fixture real (284 alertas, 6341 buques): sus buques SÍ traen imo
    (100% de cobertura en la muestra) — tipo_buque como código AIS
    numérico queda como fallback de jit_calculus.parse_contrato para
    cuando falte el imo o no resuelva contra thetis_mrv, no como el
    caso típico.

Secuencia
---------
1. fetch_datos_buque  — traduce paquete_1 a los campos que necesita el
   resto del grafo (vessel_lat/lon, port, speed_knot, event_timestamp).
2. fetch_route        — SeaRoute: ruta navegable + distancia.
3. fetch_weather       — Open-Meteo sobre los waypoints de la ruta.
4. fetch_cii_inicial   — CII a la velocidad y distancia ACTUALES del buque.
5. fetch_tiempo_espera — jit_calculus: cuánto tardará en tener atraque libre
   (fusiona paquete_1 en paquete_2 y calcula su posición en cola).
6. fetch_velocidad_jit — kwon_euler: velocidad de motor constante para
   llegar exactamente en ese tiempo, corrigiendo por meteo (Beaufort +
   ángulo relativo + forma de casco).
7. fetch_cii_jit       — CII con la velocidad JIT recomendada.
8. build_informe       — compara CII inicial vs. CII con velocidad JIT.
9. fetch_historial     — últimas recomendaciones para este mismo
   mmsi+puerto (oracle_recommendations, ventana de 24h), para que el
   LLM mantenga coherencia entre avisos sucesivos — la alerta se
   dispara cada 30 min mientras el buque está a <12h del puerto, así
   que una misma aproximación genera varios resúmenes.
10. decidir_resumen    — arista condicional (add_conditional_edges): según
    si el CII con velocidad JIT mejora o empeora, enruta a...
    fetch_resumen_ahorro | fetch_resumen_alerta — resumen en lenguaje
    natural del informe (informe_llm.py, agnóstico al proveedor de LLM
    — el "generar_texto" se inyecta vía config["configurable"], ver
    _generar_texto_inyectado; para Gemini, ver gemini_client.py).
11. publicar_recomendacion — construye el evento con la forma de
    contracts/oracle_recommendation_v1 (construir_evento_contrato) y lo
    publica en dos destinos, en orden: primero Supabase
    (oracle_recommendations, FUENTE DE VERDAD: frontera de contrato con
    el frontal + historial para la siguiente alerta), y sólo si esa
    confirma, la copia analítica en ADLS Gen2 para Databricks
    (adls_conn). Ninguno de los dos fallos tumba el grafo.

Sobre oracle_recommendation_v1 (acordado con el equipo de frontend):
  - `vessel.name`: viene de thetis_mrv (columna `name`, ya se trae con
    el SELECT * de db_conn.get_thetis_mrv_record dentro de
    cii_calculus.estimar_cii) — null sólo si no hay IMO o no se
    encuentra en thetis_mrv. `port.locode` sigue sin resolverse (no
    tenemos tabla nombre→locode conectada), va como null.
  - `eta_ais_raw` = paquete_1["ETA_static"] tal cual.
  - `queue`: la posición/espera/segmento que ya calculaba
    fetch_tiempo_espera (jit_calculus) — es la justificación misma de
    la recomendación, así que se expone en el evento, no sólo en el
    informe interno.
  - `context_vessels` usa nuestras propias estimaciones de cola
    (jit_calculus), con nombres de campo (`estimated_wait_hours`, no
    `wait_hours`/`anchored_since`) que dejan claro que es un valor
    MODELADO, no observado por un tracker con estado; cada elemento
    lleva `es_objetivo` (comparación directa de mmsi, no sólo el
    es_objetivo de jit_calculus, que no cubre atracados).
  - Sin `status`/`confidence` inventados: se exponen las señales
    nativas del cálculo (`convergio`, `excede_v_diseno`, `nota`,
    `alerta_cii`, `weather_speed_loss_pct`) directamente en
    `recommendation`.
  - `fuel_saved_t` sólo se rellena cuando thetis_mrv da un DWT REAL
    para el IMO (CIIResult.dwt_real_t) — nunca a partir del DWT
    geométrico estimado, que tiene la misma incertidumbre que el
    método fallback_admiralty. Si no hay DWT real, va null.
  - `publicar_recomendacion` no propaga fallos de Supabase: un fallo al
    escribir se registra y se descarta (mismo criterio que la DLQ de
    ingestion/src/ais/tracker.py), para no perder el cálculo entero
    (incluida la llamada al LLM, ya pagada) por un problema de BBDD.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, TypedDict

import ulid
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.tools import adls_conn, cii_calculus, db_conn, informe_llm, jit_calculus, kwon_euler
from app.agents.tools.open_meteo import marine_weather_at_eta, waypoints_with_eta, wind_at_eta
from app.agents.tools.sea_route import Port, Route, route_to_port

logger = logging.getLogger(__name__)


class OracleState(TypedDict):
    paquete_1: dict
    paquete_2: dict
    vessel_lat: float
    vessel_lon: float
    port: Port
    speed_knot: float
    departure_time: datetime
    event_timestamp: datetime
    route: Route
    distance_nm: float
    weather: list[dict]
    wind: list[dict]
    cii_inicial: cii_calculus.CIIResult
    estimacion_jit: dict
    estimaciones_puerto: list[dict]
    tiempo_espera_h: float
    velocidad_jit: kwon_euler.VelocidadJIT
    cii_jit: cii_calculus.CIIResult
    informe: dict
    historial: list[dict]
    resumen: dict
    evento_contrato: dict


def fetch_datos_buque(state: OracleState) -> dict:
    """
    Traduce paquete_1 a vessel_lat/lon, speed_knot, port y
    event_timestamp/departure_time (lo que consumen el resto de nodos).

    El puerto destino ya NO se resuelve contra ninguna tabla: el
    webhook manda lat_port/lon_port directamente en paquete_1.
    paquete_1["puerto"] es sólo un nombre para mostrar (p.ej.
    "ALGECIRAS"), no un locode.
    """
    paquete_1 = state["paquete_1"]

    speed_knot = float(paquete_1["velocidad_buque"])
    if speed_knot <= 0:
        # open_meteo.waypoints_with_eta divide la distancia acumulada
        # entre speed_knot para estimar el ETA de cada waypoint — con
        # 0 (buque fondeado/parado, o campo ausente) eso es un
        # ZeroDivisionError tres nodos más abajo, sin contexto. Se
        # corta aquí con un error claro.
        raise ValueError(
            f"paquete_1['velocidad_buque'] debe ser > 0 (recibido: {speed_knot}); "
            "no se puede calcular una ruta/ETA con el buque parado."
        )

    nombre_puerto = paquete_1["puerto"]
    port = Port(
        locode=nombre_puerto,
        name=nombre_puerto,
        lat=float(paquete_1["lat_port"]),
        lon=float(paquete_1["lon_port"]),
    )

    # event_timestamp: instante de referencia del mensaje del webhook
    # (paquete_1["ingest_timestamp"], confirmado contra fixture real),
    # para poder sumarle ETA_dynamic y comparar con nuestra propia ETA
    # en build_informe. Fallback a "ahora" sólo por si algún contrato
    # antiguo/de test no lo trae.
    event_timestamp = paquete_1.get("ingest_timestamp") or datetime.now(timezone.utc)
    if isinstance(event_timestamp, str):
        event_timestamp = datetime.fromisoformat(event_timestamp)
    if event_timestamp.tzinfo is None:
        event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)

    return {
        "vessel_lat": float(paquete_1["lat_buque"]),
        "vessel_lon": float(paquete_1["lon_buque"]),
        "port": port,
        "speed_knot": speed_knot,
        "departure_time": event_timestamp,
        "event_timestamp": event_timestamp,
    }


def fetch_route(state: OracleState) -> dict:
    route = route_to_port(
        state["vessel_lat"],
        state["vessel_lon"],
        state["port"],
        speed_knot=state["speed_knot"],
    )
    #recuperamos distance_nm para cii_calculus
    return {"route": route, "distance_nm": route.distance_nm}


def fetch_weather(state: OracleState) -> dict:
    points_with_eta = waypoints_with_eta(
        state["route"].waypoints,
        state["speed_knot"],
        state["departure_time"],
    )
    return {"weather": marine_weather_at_eta(points_with_eta), 'wind': wind_at_eta(points_with_eta)}


def fetch_cii_inicial(state: OracleState) -> dict:
    """CII a la velocidad y distancia ACTUALES del buque (antes de aplicar JIT)."""
    cii_inicial = cii_calculus.estimar_cii(state["paquete_1"], state["distance_nm"])
    return {"cii_inicial": cii_inicial}


def fetch_tiempo_espera(state: OracleState) -> dict:
    """
    jit_calculus: fusiona el buque de paquete_1 dentro del contrato
    agregado del puerto (paquete_2) y calcula, en una sola pasada, su
    tiempo de espera (la ventana que kwon_euler tiene que cumplir) Y la
    del resto de la cola — se guarda la lista completa
    (estimaciones_puerto) para que construir_evento_contrato la
    reutilice en "context_vessels" sin recalcular ni repetir la
    consulta a thetis_mrv sobre el mismo paquete_2.
    """
    estimacion_jit, estimaciones_puerto = jit_calculus.estimaciones_puerto_con_objetivo(
        state["paquete_2"], state["paquete_1"]
    )
    if estimacion_jit is None:
        raise ValueError("No se pudo estimar el tiempo de espera del buque objetivo")
    return {
        "estimacion_jit": estimacion_jit,
        "tiempo_espera_h": estimacion_jit["tiempo_espera_estimado_h"],
        "estimaciones_puerto": estimaciones_puerto,
    }


def fetch_velocidad_jit(state: OracleState) -> dict:
    """
    kwon_euler: velocidad de motor constante para llegar exactamente en
    tiempo_espera_h. Reutiliza el "tipo_normalizado" y "v_diseno_kn" que
    ya resolvió fetch_cii_inicial para el coeficiente de bloque y para
    acotar el rango de búsqueda de velocidad a algo realista para ESTE
    buque ([0.4, 1.2] × v_diseno_kn) — evita una segunda consulta a
    BBDD y evita que la bisección "converja" a velocidades imposibles
    para el casco concreto.
    """
    tipo_normalizado = state["cii_inicial"].detalles.get("tipo_normalizado")
    cb = cii_calculus.CB_POR_TIPO.get(tipo_normalizado, 0.70)

    velocidad_jit = kwon_euler.velocidad_jit_desde_oracle_state(
        state,
        tiempo_objetivo_h=state["tiempo_espera_h"],
        cb=cb,
        v_diseno_kn=state["cii_inicial"].v_diseno_kn,
    )
    return {"velocidad_jit": velocidad_jit}


def fetch_cii_jit(state: OracleState) -> dict:
    """CII con la velocidad JIT recomendada (misma ruta/distancia, distinta velocidad)."""
    paquete_1_jit = dict(state["paquete_1"])
    paquete_1_jit["velocidad_buque"] = state["velocidad_jit"].v_motor_kn
    cii_jit = cii_calculus.estimar_cii(paquete_1_jit, state["distance_nm"])
    return {"cii_jit": cii_jit}


def build_informe(state: OracleState) -> dict:
    """
    Informe final: compara CII inicial vs. CII con velocidad JIT, y
    nuestra ETA recomendada vs. la ETA inicial del webhook (ETA_dynamic:
    a la velocidad actual, sin contar colas, sólo hasta las
    inmediaciones del puerto). ETA_dynamic no se usa en ningún cálculo
    del oráculo, sólo para esta comparación informativa.
    """
    cii_inicial = state["cii_inicial"]
    cii_jit = state["cii_jit"]
    velocidad_jit = state["velocidad_jit"]
    estimacion_jit = state["estimacion_jit"]
    paquete_1 = state["paquete_1"]
    event_timestamp = state["event_timestamp"]

    ahorro_cii_pct: Optional[float] = None
    if cii_inicial.cii:
        ahorro_cii_pct = round(100 * (cii_inicial.cii - cii_jit.cii) / cii_inicial.cii, 1)

    eta_dynamic_h = paquete_1.get("ETA_dynamic")
    eta_inicial_sin_cola = (
        event_timestamp + timedelta(hours=eta_dynamic_h)
        if eta_dynamic_h is not None else None
    )
    eta_recomendada_jit = event_timestamp + timedelta(
        hours=velocidad_jit.tiempo_transito_estimado_h
    )
    diferencia_eta_h = (
        round((eta_recomendada_jit - eta_inicial_sin_cola).total_seconds() / 3600, 1)
        if eta_inicial_sin_cola else None
    )

    informe = {
        "correlation_id": paquete_1.get("correlation_id"),
        "buque": {
            "mmsi": paquete_1.get("mmsi"),
            "imo": paquete_1.get("imo"),
            "puerto_destino": state["port"].name,
        },
        "ruta": {
            "distancia_nm": round(state["distance_nm"], 1),
        },
        "cola_puerto": {
            "tiempo_espera_estimado_h": estimacion_jit["tiempo_espera_estimado_h"],
            "posicion_cola": estimacion_jit["posicion_cola"],
            "segmento_atraque": estimacion_jit["segmento_atraque"],
        },
        "velocidad": {
            "actual_kn": paquete_1.get("velocidad_buque"),
            "diseno_kn": cii_inicial.v_diseno_kn,
            "jit_recomendada_kn": velocidad_jit.v_motor_kn,
            "tiempo_transito_estimado_h": velocidad_jit.tiempo_transito_estimado_h,
            "perdida_kwon_media_pct": velocidad_jit.perdida_media_pct,
            "convergio": velocidad_jit.convergio,
            "excede_v_diseno": velocidad_jit.excede_v_diseno,
            "nota": velocidad_jit.nota,
        },
        "cii": {
            "inicial": cii_inicial.cii,
            "jit": cii_jit.cii,
            "metodo": cii_inicial.metodo,
            "ahorro_pct": ahorro_cii_pct,
        },
        "eta": {
            # ETA_dynamic del webhook: a la velocidad actual, sin colas,
            # sólo hasta las inmediaciones del puerto. No se usa en
            # ningún cálculo, sólo para comparar aquí.
            "inicial_sin_cola": eta_inicial_sin_cola.isoformat() if eta_inicial_sin_cola else None,
            "recomendada_jit": eta_recomendada_jit.isoformat(),
            "diferencia_h": diferencia_eta_h,
        },
    }
    return {"informe": informe}


def _generar_texto_inyectado(config: RunnableConfig) -> Optional[Callable[[str], str]]:
    """
    El "generar_texto" (función prompt -> texto, agnóstica al
    proveedor/modelo de LLM) se inyecta vía `config["configurable"]`,
    no vía el state — así el state del grafo sigue siendo datos puros
    serializables, y el modelo concreto se decide en el momento de la
    invocación sin tocar este módulo:

        oracle_graph.invoke(
            {"paquete_1": ..., "paquete_2": ...},
            config={"configurable": {"generar_texto": mi_funcion}},
        )

    Si no se pasa ningún "generar_texto", informe_llm usa un resumen determinista sin LLM.
    """
    return (config.get("configurable") or {}).get("generar_texto")


def fetch_historial(state: OracleState) -> dict:
    """
    Últimas recomendaciones (hasta 3, últimas 24h) para este mismo
    mmsi+puerto, para dar contexto al LLM y mantener coherencia entre
    avisos sucesivos — la alerta se dispara cada 30 min mientras el
    buque está a <12h del puerto, así que una misma aproximación
    genera varios registros en oracle_recommendations.
    """
    mmsi = str(state["paquete_1"].get("mmsi"))
    puerto = state["port"].name
    historial = db_conn.get_historial_recomendaciones(mmsi, puerto)
    return {"historial": historial}


def decidir_resumen(state: OracleState) -> str:
    """
    Arista condicional real (no un `if` dentro de un nodo): decide si
    el CII con velocidad JIT mejora o empeora respecto al inicial, y
    enruta el grafo al nodo de resumen correspondiente.
    """
    ahorro_pct = state["informe"]["cii"].get("ahorro_pct")
    if ahorro_pct is not None and ahorro_pct < 0:
        return "fetch_resumen_alerta"
    return "fetch_resumen_ahorro"


def fetch_resumen_ahorro(state: OracleState, config: RunnableConfig) -> dict:
    """Resumen en lenguaje natural — caso en que el CII mejora con la velocidad JIT."""
    resumen = informe_llm.resumen_ahorro(
        state["informe"], _generar_texto_inyectado(config), state.get("historial")
    )
    return {"resumen": resumen}


def fetch_resumen_alerta(state: OracleState, config: RunnableConfig) -> dict:
    """Resumen en lenguaje natural — caso en que el CII empeora con la velocidad JIT."""
    resumen = informe_llm.resumen_alerta(
        state["informe"], _generar_texto_inyectado(config), state.get("historial")
    )
    return {"resumen": resumen}


def _conteos_puerto(paquete_2: dict) -> dict:
    estados = paquete_2.get("estados", paquete_2)
    return {
        "berthed_count": len(estados.get("num_buques_atracados", [])),
        "anchored_count": len(estados.get("num_buques_fondeados", [])),
        "inbound_count": len(estados.get("num_buques_en_camino", [])),
    }


def _contexto_buques(paquete_2: dict, target_mmsi: str, estimaciones_puerto: list[dict]) -> dict:
    """
    context_vessels del contrato, con nuestras propias estimaciones de
    cola (jit_calculus) en vez de estado observado por un tracker con
    estado (Flink) — de ahí "estimated_wait_hours" y no
    "wait_hours"/"anchored_since". Sin nombre de buque: paquete_2 no lo
    trae para el resto de la flota.

    `estimaciones_puerto` viene de fetch_tiempo_espera
    (estimaciones_puerto_con_objetivo) — es la MISMA pasada que ya
    fusionó el buque objetivo y calculó su recomendación; no se vuelve
    a llamar a jit_calculus aquí, para no recalcular ni repetir la
    consulta a thetis_mrv sobre el mismo paquete_2.

    `es_objetivo` se marca comparando mmsi directamente contra
    `target_mmsi`, no con el es_objetivo que ya trae
    estimaciones_puerto — ese sólo cubre fondeados/en_camino (la fusión
    de jit_calculus), no atracados, y aquí hace falta para las tres
    listas.
    """
    estados = paquete_2.get("estados", paquete_2)
    atracados_raw = estados.get("num_buques_atracados", [])
    fondeados_raw = estados.get("num_buques_fondeados", [])
    en_camino_raw = estados.get("num_buques_en_camino", [])

    estimaciones = {e["mmsi"]: e for e in estimaciones_puerto}

    def _base(item: dict) -> dict:
        return {
            "mmsi": item.get("mmsi"),
            "name": None,
            "lat": item.get("latitud"),
            "lon": item.get("longitud"),
            "es_objetivo": str(item.get("mmsi")) == str(target_mmsi),
        }

    def _con_estimacion(item: dict) -> dict:
        v = _base(item)
        est = estimaciones.get(str(item.get("mmsi")))
        v["estimated_wait_hours"] = est["tiempo_espera_estimado_h"] if est else None
        return v

    return {
        "berthed": [_base(item) for item in atracados_raw],
        "anchored": [_con_estimacion(item) for item in fondeados_raw],
        "inbound": [_con_estimacion(item) for item in en_camino_raw],
    }


def construir_evento_contrato(state: OracleState, event_id: str, session_id: str) -> dict:
    """Construye el evento con la forma de oracle_recommendation_v1 (ver notas del docstring del módulo)."""
    paquete_1 = state["paquete_1"]
    paquete_2 = state["paquete_2"]
    port = state["port"]
    cii_inicial = state["cii_inicial"]
    cii_jit = state["cii_jit"]
    velocidad_jit = state["velocidad_jit"]
    informe = state["informe"]
    resumen = state["resumen"]
    event_timestamp = state["event_timestamp"]
    tipo_normalizado = cii_inicial.detalles.get("tipo_normalizado")

    route_weather = [
        {
            "lat": ola["lat"], "lon": ola["lon"], "eta": ola["eta"].isoformat(),
            "wave_height": ola["wave_height"], "wave_direction": ola["wave_direction"],
            "wave_period": ola["wave_period"],
            "wind_speed_kn": viento["wind_speed_kn"], "wind_direction": viento["wind_direction"],
            "wind_gusts_kn": viento["wind_gusts_kn"],
        }
        for ola, viento in zip(state["weather"], state["wind"])
    ]

    eta_dynamic_h = paquete_1.get("ETA_dynamic")
    idle_hours_avoided = (
        round(max(0.0, state["tiempo_espera_h"] - eta_dynamic_h), 2)
        if eta_dynamic_h is not None else None
    )

    # fuel_saved_t: sólo con DWT real de thetis_mrv (dwt_real_t), nunca
    # con el DWT geométrico estimado — ver docstring del módulo.
    fuel_saved_t = None
    if (cii_inicial.dwt_real_t is not None
            and cii_inicial.co2_estimado_kg is not None
            and cii_jit.co2_estimado_kg is not None):
        co2_saved_kg = cii_inicial.co2_estimado_kg - cii_jit.co2_estimado_kg
        fuel_saved_t = round((co2_saved_kg / cii_calculus.CF_HFO) / 1000.0, 3)

    return {
        "event_id": event_id,
        "session_id": session_id,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "vessel": {
            "mmsi": paquete_1.get("mmsi"),
            "imo": paquete_1.get("imo"),
            "name": cii_inicial.detalles.get("vessel_name"),  # thetis_mrv.name; null si no hay IMO/no está en thetis_mrv
            "lat": state["vessel_lat"],
            "lon": state["vessel_lon"],
            "speed_kn": paquete_1.get("velocidad_buque"),
            "heading": paquete_1.get("direccion"),
            "nav_status": paquete_1.get("estado"),
            "destination_raw": paquete_1.get("puerto"),
            "eta_ais_raw": paquete_1.get("ETA_static"),
            "position_at": event_timestamp.isoformat(),
            "is_container": (tipo_normalizado == "container") if tipo_normalizado else None,
        },
        "port": {
            "locode": None,  # no disponible: sin resolución nombre->locode hoy
            "name": port.name,
            "lat": port.lat,
            "lon": port.lon,
            "context_radius_nm": None,  # lo define quien arma paquete_2, no lo conocemos
            **_conteos_puerto(paquete_2),
            "snapshot_at": None,  # paquete_2 no trae timestamp propio hoy
        },
        "context_vessels": _contexto_buques(
            paquete_2, str(paquete_1.get("mmsi")), state["estimaciones_puerto"]
        ),
        "route": {
            "distance_nm": state["distance_nm"],
            "duration_hours": state["route"].duration_hours,
            "waypoints": state["route"].waypoints,
        },
        "route_weather": route_weather,
        # Justificación de la recomendación: posición/espera en la cola
        # de ESTE buque — sin esto el frontal no puede explicar "por
        # qué" frenar. Ya lo calculaba fetch_tiempo_espera, sólo
        # faltaba copiarlo al evento.
        "queue": {
            "estimated_wait_hours": informe["cola_puerto"]["tiempo_espera_estimado_h"],
            "queue_position": informe["cola_puerto"]["posicion_cola"],
            "berth_segment": informe["cola_puerto"]["segmento_atraque"],
        },
        "recommendation": {
            "recommended_speed_kn": velocidad_jit.v_motor_kn,
            "speed_delta_kn": round(
                velocidad_jit.v_motor_kn - float(paquete_1.get("velocidad_buque", 0)), 2
            ),
            "eta_current": informe["eta"]["inicial_sin_cola"],
            "eta_optimized": informe["eta"]["recomendada_jit"],
            "idle_hours_avoided": idle_hours_avoided,
            "fuel_saved_t": fuel_saved_t,
            "rationale": resumen["texto"],
            # Sin status/confidence inventados: señales nativas del cálculo.
            "convergio": velocidad_jit.convergio,
            "excede_v_diseno": velocidad_jit.excede_v_diseno,
            "alerta_cii": resumen["alerta_cii"],
            "nota": velocidad_jit.nota,
            "weather_speed_loss_pct": velocidad_jit.perdida_media_pct,
            "cii": {
                "inicial": cii_inicial.cii,
                "jit": cii_jit.cii,
                "metodo": cii_inicial.metodo,
                "ahorro_pct": informe["cii"]["ahorro_pct"],
            },
        },
    }


def publicar_recomendacion(state: OracleState) -> dict:
    """
    Construye el evento (oracle_recommendation_v1) y lo publica en los
    dos destinos, en este orden:

    1. Supabase (oracle_recommendations) — FUENTE DE VERDAD: frontera de
       contrato con el frontal y historial que da contexto al LLM en la
       siguiente alerta (30 min después, mismo mmsi+puerto).
    2. ADLS Gen2 (adls_conn) — copia analítica para Databricks. Sólo se
       escribe si Supabase confirmó primero: si la fuente de verdad no
       tiene el evento, la capa analítica tampoco debe tenerlo. No hace
       falta await/async: psycopg es síncrono, así que al volver de
       guardar_recomendacion sin excepción el commit ya está hecho.

    Ninguno de los dos fallos tumba el grafo (se registra y se
    descarta, mismo criterio que la DLQ de ingestion/src/ais/tracker.py):
    perder el cálculo entero —incluida la llamada al LLM, ya pagada—
    por un problema de persistencia sería peor que no publicarlo.

    event_id = correlation_id del webhook (clave de idempotencia: un
    reintento no duplica fila en Supabase ni blob en ADLS, porque el
    nombre del blob es el propio event_id).
    session_id = el de la recomendación más reciente para este mismo
    mmsi+puerto en las últimas 24h, o uno nuevo si no hay ninguna —
    agrupa una misma aproximación para que el frontal la trate como
    una sola sesión en vez de puntos sueltos.
    """
    mmsi = str(state["paquete_1"].get("mmsi"))
    puerto = state["port"].name
    event_id = state["paquete_1"].get("correlation_id") or str(ulid.ULID())

    # Si Supabase no responde al buscar la sesión, se trata igual que
    # "no hay sesión previa" (nueva sesión) — no vale la pena tumbar el
    # cálculo entero por esto.
    try:
        session_id = db_conn.buscar_session_id(mmsi, puerto)
    except Exception:
        logger.exception(
            "buscar_session_id falló para mmsi=%s puerto=%s; se abre sesión nueva", mmsi, puerto
        )
        session_id = None
    session_id = session_id or str(ulid.ULID())

    evento = construir_evento_contrato(state, event_id, session_id)

    # --- 1. Supabase (fuente de verdad) ---
    supabase_ok = False
    try:
        insertado = db_conn.guardar_recomendacion(
            event_id=event_id,
            session_id=session_id,
            mmsi=mmsi,
            puerto=puerto,
            alerta_cii=state["resumen"]["alerta_cii"],
            payload=evento,
        )
        supabase_ok = True
        if not insertado:
            # ON CONFLICT DO NOTHING: el event_id ya estaba. Se sigue
            # publicando a ADLS igualmente (sobrescribe el mismo blob),
            # porque el intento anterior pudo fallar justo ahí y así el
            # reintento lo recupera.
            logger.info(
                "event_id=%s ya existía en oracle_recommendations (reintento); "
                "se republica en ADLS de todos modos (idempotente)", event_id,
            )
    except Exception:
        logger.exception(
            "guardar_recomendacion falló para event_id=%s (mmsi=%s, puerto=%s); "
            "se descarta la escritura, el resultado se devuelve igual",
            event_id, mmsi, puerto,
        )

    # --- 2. ADLS (copia analítica; sólo tras confirmar la fuente de verdad) ---
    if supabase_ok:
        if not adls_conn.esta_configurado():
            logger.info(
                "ADLS sin SAS token configurado; se omite la copia analítica "
                "de event_id=%s (Supabase sí tiene el evento)", event_id,
            )
        else:
            try:
                ruta = adls_conn.guardar_recomendacion(evento)
                logger.info("event_id=%s publicado en ADLS: %s", event_id, ruta)
            except Exception:
                logger.exception(
                    "Escritura en ADLS falló para event_id=%s; Supabase (fuente de "
                    "verdad) sí lo tiene, así que el resultado se devuelve igual",
                    event_id,
                )

    return {"evento_contrato": evento}


def build_graph():
    graph = StateGraph(OracleState)
    graph.add_node("fetch_datos_buque", fetch_datos_buque)
    graph.add_node("fetch_route", fetch_route)
    graph.add_node("fetch_weather", fetch_weather)
    graph.add_node("fetch_cii_inicial", fetch_cii_inicial)
    graph.add_node("fetch_tiempo_espera", fetch_tiempo_espera)
    graph.add_node("fetch_velocidad_jit", fetch_velocidad_jit)
    graph.add_node("fetch_cii_jit", fetch_cii_jit)
    graph.add_node("build_informe", build_informe)
    graph.add_node("fetch_historial", fetch_historial)
    graph.add_node("fetch_resumen_ahorro", fetch_resumen_ahorro)
    graph.add_node("fetch_resumen_alerta", fetch_resumen_alerta)
    graph.add_node("publicar_recomendacion", publicar_recomendacion)

    graph.add_edge(START, "fetch_datos_buque")
    graph.add_edge("fetch_datos_buque", "fetch_route")
    graph.add_edge("fetch_route", "fetch_weather")
    graph.add_edge("fetch_weather", "fetch_cii_inicial")
    graph.add_edge("fetch_cii_inicial", "fetch_tiempo_espera")
    graph.add_edge("fetch_tiempo_espera", "fetch_velocidad_jit")
    graph.add_edge("fetch_velocidad_jit", "fetch_cii_jit")
    graph.add_edge("fetch_cii_jit", "build_informe")
    graph.add_edge("build_informe", "fetch_historial")
    graph.add_conditional_edges(
        "fetch_historial",
        decidir_resumen,
        {
            "fetch_resumen_ahorro": "fetch_resumen_ahorro",
            "fetch_resumen_alerta": "fetch_resumen_alerta",
        },
    )
    graph.add_edge("fetch_resumen_ahorro", "publicar_recomendacion")
    graph.add_edge("fetch_resumen_alerta", "publicar_recomendacion")
    graph.add_edge("publicar_recomendacion", END)
    return graph.compile()


oracle_graph = build_graph()


if __name__ == "__main__":
    # Formato real del webhook (fixture de 284 alertas, Algeciras/Barcelona/
    # Valencia) — "estado" y "tipo_buque" son códigos AIS numéricos, no
    # texto; ingest_timestamp confirmado contra ese fixture. Los buques
    # de paquete_2 SÍ traen imo (100% de cobertura en la muestra real:
    # 6341/6341) — tipo_buque numérico es sólo el fallback de
    # jit_calculus.parse_contrato para cuando falte el imo o no resuelva
    # contra thetis_mrv, no el caso típico. Nótese que el propio buque
    # objetivo (mmsi 352986151) ya aparece dentro de "num_buques_en_camino"
    # en paquete_2 — es el caso real que ejercita fusionar_buque_objetivo
    # marcándolo in situ en vez de duplicarlo.
    paquete_1_ejemplo = {
        "correlation_id": "01M08APDG115DX8X6KEKVXKHQE",
        "mmsi": 352986151,
        "imo": 9520675,
        "puerto": "ALGECIRAS",
        "estado": 0,  # AIS: under way using engine -> en_camino
        "lat_buque": 35.983608333333336,
        "lon_buque": -5.365081666666667,
        "lat_port": 36.12972,
        "lon_port": -5.42278,
        "direccion": 74.0,
        "velocidad_buque": 9.8,
        "eslora": 190,
        "manga": 32,
        "calado_de_diseno": 9.2,
        "tipo_buque": 70,  # AIS: Cargo
        "ETA_dynamic": 0.9396741460583867,
        "ETA_static": "2026-08-17 18:00:00",  # no se usa
        "ingest_timestamp": "2026-08-21T09:00:00.000000+00:00",
    }

    paquete_2_ejemplo = {
        "puerto": "ALGECIRAS",
        "estados": {
            "num_buques_atracados": [
                {"mmsi": 538009654, "imo": 9210919, "eslora": 177, "latitud": 36.120945, "longitud": -5.418003333333333, "tipo_buque": 70},
                {"mmsi": 636093171, "imo": 9010929, "eslora": 368, "latitud": 36.141131666666666, "longitud": -5.435471666666667, "tipo_buque": 71},
            ],
            "num_buques_fondeados": [
                {"mmsi": 538006140, "imo": 1045045, "eslora": 199, "latitud": 36.15668333333333, "longitud": -5.421004999999999, "tipo_buque": 70},
                {"mmsi": 271052023, "eslora": 199, "latitud": 36.10551833333333, "longitud": -5.412706666666667, "tipo_buque": 70},  # sin imo: ejercita el fallback por código AIS
            ],
            "num_buques_en_camino": [
                {"mmsi": 636017075, "imo": 7043843, "eslora": 180, "latitud": 36.260146666666664, "longitud": -4.951068333333334, "tipo_buque": 70},
                # el propio buque objetivo, ya presente en el snapshot del puerto:
                {"mmsi": 352986151, "eslora": 190, "latitud": 36.002605, "longitud": -5.291625, "tipo_buque": 70},
                {"mmsi": 636020192, "imo": 9145413, "eslora": 186, "latitud": 36.050855, "longitud": -5.138205, "tipo_buque": 74},
            ],
        },
    }

    # Si hay GEMINI_API_KEY en el entorno, se usa Gemini de verdad para
    # el resumen; si no, informe_llm cae al resumen determinista sin LLM
    # (el grafo es ejecutable de punta a punta en ambos casos).
    import os
    invoke_config = {}
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if gemini_api_key:
        from app.agents.tools.gemini_client import crear_generar_texto
        invoke_config = {
            "configurable": {"generar_texto": crear_generar_texto(gemini_api_key)}
        }

    result = oracle_graph.invoke(
        {"paquete_1": paquete_1_ejemplo, "paquete_2": paquete_2_ejemplo},
        config=invoke_config,
    )

    print("=" * 60)
    print("  INFORME ADAPTIVE SLOW STEAMING")
    print("=" * 60)
    import json
    print(json.dumps(result["informe"], indent=2, ensure_ascii=False))
    print("-" * 60)
    print(f"  [alerta_cii={result['resumen']['alerta_cii']}] {result['resumen']['texto']}")
    print("=" * 60)
    print("  EVENTO oracle_recommendation_v1 (persistido en oracle_recommendations)")
    print("=" * 60)
    print(json.dumps(result["evento_contrato"], indent=2, ensure_ascii=False))
    print("=" * 60)
