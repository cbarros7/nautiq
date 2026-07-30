"""
Grafo del Oráculo Matemático (LangGraph).

Orquesta, como un StateGraph de aristas fijas (sin tool-calling, ver decisión
tomada para el pipeline reactivo), los nodos deterministas que alimentan la
recomendación de Adaptive Slow Steaming. Los cálculos viven como funciones
puras en `sea_route.py` / `open_meteo.py`; este módulo solo los encadena.

Secuencia actual: fetch_route (SeaRoute) -> fetch_weather (Open-Meteo sobre
los waypoints de la ruta). Próximos nodos (curva de consumo, CII, JIT,
Kwon-Euler) se añadirán sobre este mismo grafo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.tools.open_meteo import marine_weather_at_eta, waypoints_with_eta, wind_at_eta
from app.agents.tools.sea_route import Port, Route, route_to_port


class OracleState(TypedDict):
    vessel_lat: float
    vessel_lon: float
    port: Port
    speed_knot: float
    departure_time: datetime
    route: Route
    weather: list[dict]
    wind: list[dict]


def fetch_route(state: OracleState) -> dict:
    route = route_to_port(
        state["vessel_lat"],
        state["vessel_lon"],
        state["port"],
        speed_knot=state["speed_knot"],
    )
    return {"route": route}


def fetch_weather(state: OracleState) -> dict:
    points_with_eta = waypoints_with_eta(
        state["route"].waypoints,
        state["speed_knot"],
        state["departure_time"],
    )
    return {"weather": marine_weather_at_eta(points_with_eta), 'wind': wind_at_eta(points_with_eta)}



def build_graph():
    graph = StateGraph(OracleState)
    graph.add_node("fetch_route", fetch_route)
    graph.add_node("fetch_weather", fetch_weather)
    graph.add_edge(START, "fetch_route")
    graph.add_edge("fetch_route", "fetch_weather")
    graph.add_edge("fetch_weather", END)
    return graph.compile()


oracle_graph = build_graph()


if __name__ == "__main__":
    result = oracle_graph.invoke(
        {
            "vessel_lat": 41.492474,
            "vessel_lon": 4.455705,
            "port": Port("ESBCN", "Barcelona", 41.324340, 2.161924),
            "speed_knot": 14.0,
            "departure_time": datetime.now(timezone.utc),
        }
    )
    # print(result["route"])
    # print(result["weather"])
    print(result["wind"])
