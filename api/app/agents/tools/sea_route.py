"""
Cálculo de ruta navegable buque -> puerto (SeaRoute).

Resuelve la ruta marítima más corta entre la posición AIS de un buque y un
puerto destino sobre el grafo de corredores navegables de `searoute` (no es
una llamada de red: el grafo se carga una vez en memoria al importar este
módulo, para no pagar ese coste dentro del presupuesto de latencia del
webhook). Nodo determinista del grafo LangGraph del oráculo matemático
(`math_oracle.py`); su salida (distancia + waypoints) alimenta la corrección
Kwon (meteo) y la integración Euler para la velocidad JIT.

Convención de coordenadas: [lon, lat] en la salida (waypoints), igual que el
resto del pipeline (SAD §6, "Rutas (SeaRoute)"). Los parámetros de entrada
aceptan lat/lon por separado para no obligar al llamador a conocer esa
convención (coincide con los campos `lat`/`lon` de `ais_position_v1.avsc`).
"""

from __future__ import annotations

from dataclasses import dataclass

import searoute as sr
from searoute.classes.passages import Passage

# Grafo de marnet + puertos: se carga una sola vez en memoria al importar el
# módulo (proceso de arranque de FastAPI), no en cada request.
_MARNET, _PORTS = sr.get_graphs()

DEFAULT_RESTRICTIONS = [Passage.northwest]  # mismo default que la librería, ya que el ártico está congelado.


@dataclass(frozen=True)
class Port:
    """Puerto destino resuelto desde la tabla `ports` (locode, name, lat, lon)."""

    locode: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    distance_nm: float
    duration_hours: float
    waypoints: list[tuple[float, float]]  # [(lon, lat), ...] en orden de navegación


class NoRouteFoundError(RuntimeError):
    """No existe ruta navegable entre origen y destino (paso restringido, red sin cobertura, etc.)."""


def route_to_port(
    vessel_lat: float,
    vessel_lon: float,
    port: Port,
    *,
    speed_knot: float = 24.0,
    restrictions: list[str] | None = DEFAULT_RESTRICTIONS,
) -> Route:
    """Ruta navegable más corta desde la posición AIS del buque hasta `port`.

    `speed_knot` solo determina el `duration_hours` informativo que devuelve
    la librería; la velocidad real para llegar JIT la resuelve el solver
    Kwon-Euler aguas abajo, no este cálculo.
    """
    origin = [vessel_lon, vessel_lat]
    destination = [port.lon, port.lat]

    feature = sr.searoute(
        origin,
        destination,
        units="naut",
        speed_knot=speed_knot,
        restrictions=restrictions,
        M=_MARNET,
        P=_PORTS,
        append_orig_dest=True, #para que la ruta incluya el punto de origen y destino en los waypoints.
        include_ports=True, #incluye metadata del puerto en properties.
    )

    waypoints = [tuple(coord) for coord in feature.geometry.coordinates]
    distance_nm = feature.properties["length"]

    if not waypoints or not distance_nm:
        raise NoRouteFoundError(
            f"Sin ruta navegable entre buque ({vessel_lat}, {vessel_lon}) "
            f"y puerto {port.locode} ({port.lat}, {port.lon})."
        )

    return Route(
        distance_nm=distance_nm,
        duration_hours=feature.properties["duration_hours"],
        waypoints=waypoints,
    )

if __name__ == "__main__":
    a =route_to_port(39.093914, 3.250987, Port("ESBCN", "Barcelona", 41.324340, 2.161924), speed_knot=24.0, restrictions=["northwest"])
    print("{:.1f} {}".format(a.distance_nm, "naut"))
    print("{:.1f} {}".format(a.duration_hours, "hours"))
    print("Waypoints:")
    for lon, lat in a.waypoints:
        print(f"  {lat:.6f}, {lon:.6f}")
        