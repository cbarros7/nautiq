"""
Grafo del Oráculo Matemático (LangGraph).

Orquesta, como un StateGraph de aristas fijas (sin tool-calling, ver decisión
tomada para el pipeline reactivo), los nodos deterministas que alimentan la
recomendación de Adaptive Slow Steaming. Los cálculos viven como funciones
puras en `sea_route.py` / `open_meteo.py` / `cii_calculus.py` /
`jit_calculus.py` / `kwon_euler.py`; este módulo solo los encadena.

Entrada del grafo: los dos paquetes que llegan del webhook.
  - paquete_1: mensaje individual del buque que dispara el proceso (mmsi,
    imo, puerto destino, estado, posición, velocidad, dimensiones, ETA...).
  - paquete_2: contrato agregado del estado del puerto (atracados/
    fondeados/en_camino) que consume jit_calculus.

Secuencia
---------
1. fetch_datos_buque  — traduce paquete_1 a los campos que necesita el
   resto del grafo y resuelve el puerto destino (paquete_1["puerto"],
   locode) contra la tabla `ports` (db_conn.get_port).
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
9. decidir_resumen     — arista condicional (add_conditional_edges): según
   si el CII con velocidad JIT mejora o empeora, enruta a...
   fetch_resumen_ahorro | fetch_resumen_alerta — resumen en lenguaje
   natural del informe (informe_llm.py, agnóstico al proveedor de LLM
   — el "generar_texto" se inyecta vía config["configurable"], ver
   _generar_texto_inyectado).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents.tools import cii_calculus, db_conn, informe_llm, jit_calculus, kwon_euler
from app.agents.tools.open_meteo import marine_weather_at_eta, waypoints_with_eta, wind_at_eta
from app.agents.tools.sea_route import Port, Route, route_to_port


class OracleState(TypedDict):
    paquete_1: dict
    paquete_2: dict
    vessel_lat: float
    vessel_lon: float
    port: Port
    speed_knot: float
    departure_time: datetime
    route: Route
    distance_nm: float
    weather: list[dict]
    wind: list[dict]
    cii_inicial: cii_calculus.CIIResult
    estimacion_jit: dict
    tiempo_espera_h: float
    velocidad_jit: kwon_euler.VelocidadJIT
    cii_jit: cii_calculus.CIIResult
    informe: dict
    resumen: dict


def fetch_datos_buque(state: OracleState) -> dict:
    """
    Traduce paquete_1 a vessel_lat/lon, speed_knot y departure_time (lo
    que ya consumen fetch_route/fetch_weather), y resuelve el puerto
    destino contra la tabla `ports` a partir de paquete_1["puerto"]
    (locode, p.ej. "ESBCN").
    """
    paquete_1 = state["paquete_1"]

    registro_puerto = db_conn.get_port(paquete_1["puerto"])
    if registro_puerto is None:
        raise ValueError(
            f"Puerto '{paquete_1['puerto']}' no encontrado en la tabla ports"
        )
    port = Port(
        locode=registro_puerto["locode"],
        name=registro_puerto["name"],
        lat=float(registro_puerto["lat"]),
        lon=float(registro_puerto["lon"]),
    )

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

    return {
        "vessel_lat": float(paquete_1["latitud"]),
        "vessel_lon": float(paquete_1["longitud"]),
        "port": port,
        "speed_knot": speed_knot,
        "departure_time": datetime.now(timezone.utc),
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
    agregado del puerto (paquete_2) y calcula su tiempo de espera hasta
    disponer de atraque — la ventana de tiempo que kwon_euler tiene que
    cumplir.
    """
    estimacion_jit = jit_calculus.eta_buque_objetivo(state["paquete_2"], state["paquete_1"])
    if estimacion_jit is None:
        raise ValueError("No se pudo estimar el tiempo de espera del buque objetivo")
    return {
        "estimacion_jit": estimacion_jit,
        "tiempo_espera_h": estimacion_jit["tiempo_espera_estimado_h"],
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
    """Informe final: compara CII inicial vs. CII con velocidad JIT."""
    cii_inicial = state["cii_inicial"]
    cii_jit = state["cii_jit"]
    velocidad_jit = state["velocidad_jit"]
    estimacion_jit = state["estimacion_jit"]

    ahorro_cii_pct: Optional[float] = None
    if cii_inicial.cii:
        ahorro_cii_pct = round(100 * (cii_inicial.cii - cii_jit.cii) / cii_inicial.cii, 1)

    informe = {
        "buque": {
            "mmsi": state["paquete_1"].get("mmsi"),
            "imo": state["paquete_1"].get("imo"),
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
            "actual_kn": state["paquete_1"].get("velocidad_buque"),
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

    Si no se pasa ningún "generar_texto" (todavía no se ha elegido
    modelo), informe_llm usa un resumen determinista sin LLM.
    """
    return (config.get("configurable") or {}).get("generar_texto")


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
    resumen = informe_llm.resumen_ahorro(state["informe"], _generar_texto_inyectado(config))
    return {"resumen": resumen}


def fetch_resumen_alerta(state: OracleState, config: RunnableConfig) -> dict:
    """Resumen en lenguaje natural — caso en que el CII empeora con la velocidad JIT."""
    resumen = informe_llm.resumen_alerta(state["informe"], _generar_texto_inyectado(config))
    return {"resumen": resumen}


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
    graph.add_node("fetch_resumen_ahorro", fetch_resumen_ahorro)
    graph.add_node("fetch_resumen_alerta", fetch_resumen_alerta)

    graph.add_edge(START, "fetch_datos_buque")
    graph.add_edge("fetch_datos_buque", "fetch_route")
    graph.add_edge("fetch_route", "fetch_weather")
    graph.add_edge("fetch_weather", "fetch_cii_inicial")
    graph.add_edge("fetch_cii_inicial", "fetch_tiempo_espera")
    graph.add_edge("fetch_tiempo_espera", "fetch_velocidad_jit")
    graph.add_edge("fetch_velocidad_jit", "fetch_cii_jit")
    graph.add_edge("fetch_cii_jit", "build_informe")
    graph.add_conditional_edges(
        "build_informe",
        decidir_resumen,
        {
            "fetch_resumen_ahorro": "fetch_resumen_ahorro",
            "fetch_resumen_alerta": "fetch_resumen_alerta",
        },
    )
    graph.add_edge("fetch_resumen_ahorro", END)
    graph.add_edge("fetch_resumen_alerta", END)
    return graph.compile()


oracle_graph = build_graph()


if __name__ == "__main__":
    paquete_1_ejemplo = {
        "mmsi": "123456789",
        "imo": 9104421,
        "puerto": "ESBCN",
        "estado": "en_camino",
        "longitud": 4.455705,
        "latitud": 41.492474,
        "direccion": 200,
        "velocidad_buque": 14.0,
        "eslora": 190.0,
        "manga": 32.0,
        "calado_de_diseño": 12.5,
    }

    paquete_2_ejemplo = {
        "puerto": "ESBCN",
        "estados": {
            "num_buques_atracados": [
                {"mmsi": "477000001", "imo": 9210919, "eslora": 290},
                {"mmsi": "477000002", "imo": 9010929, "eslora": 335},
            ],
            "num_buques_fondeados": [
                {"mmsi": "477000010", "imo": 1045045, "eslora": 225},
            ],
            "num_buques_en_camino": [
                {"mmsi": "477000020", "imo": 7043843, "eslora": 350},
            ],
        },
    }

    result = oracle_graph.invoke(
        {"paquete_1": paquete_1_ejemplo, "paquete_2": paquete_2_ejemplo}
    )

    print("=" * 60)
    print("  INFORME ADAPTIVE SLOW STEAMING")
    print("=" * 60)
    import json
    print(json.dumps(result["informe"], indent=2, ensure_ascii=False))
    print("-" * 60)
    print(f"  [alerta_cii={result['resumen']['alerta_cii']}] {result['resumen']['texto']}")
    print("=" * 60)

    # Para usar un LLM real en vez del resumen determinista, inyectar
    # "generar_texto" vía config en el invoke, p.ej.:
    #
    # def generar_texto(prompt: str) -> str:
    #     return mi_cliente_llm.invocar(prompt)
    #
    # oracle_graph.invoke(
    #     {"paquete_1": paquete_1_ejemplo, "paquete_2": paquete_2_ejemplo},
    #     config={"configurable": {"generar_texto": generar_texto}},
    # )
