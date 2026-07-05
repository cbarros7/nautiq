"""
AIS Scraper — descubrimiento de la flota objetivo hacia los puertos españoles.

Escucha `ShipStaticData`, filtra carga (70-79) cuyo destino AIS apunta a Valencia,
Algeciras o Barcelona, y devuelve el conjunto de MMSIs a seguir. Es solo
descubrimiento: NO publica ni mantiene maestro (eso es Flink).
"""

import time

from .. import constants
from .client import AISStreamClient
from .models import AISStatic, ContractError

# Palabras clave de destino de los tres puertos objetivo.
_DEST_KEYWORDS = {kw for p in constants.PORTS.values() for kw in p["dest_keywords"]}


def _matches_target_port(destination: str | None) -> bool:
    if not destination:
        return False
    dest = destination.upper()
    return any(kw in dest for kw in _DEST_KEYWORDS)


async def find_target_fleet(client: AISStreamClient, duration: int) -> set[int]:
    """Escanea ShipStaticData `duration` s y devuelve MMSIs de carga hacia los puertos."""
    targets: set[int] = set()
    start = time.time()
    print(f"[INICIO][Scraper] Buscando flota -> Valencia/Algeciras/Barcelona ({duration}s)...")

    stream = client.stream(
        bounding_boxes=constants.WESTERN_MED_BBOX,
        message_types=["ShipStaticData"],
    )
    async for message in stream:
        if time.time() - start >= duration:
            break
        if message.get("MessageType") != "ShipStaticData":
            continue
        try:
            static = AISStatic.from_message(message)
        except ContractError:
            continue
        if static.is_cargo and _matches_target_port(static.destination) \
                and static.mmsi not in targets:
            targets.add(static.mmsi)
            print(f"[INFO][Scraper] Objetivo: MMSI {static.mmsi} | {static.name} "
                  f"| dest. {static.destination}")

    print(f"[FIN][Scraper] {len(targets)} buques objetivo.")
    return targets
