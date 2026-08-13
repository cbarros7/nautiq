"""
Generador de AIS sintético — sustituto temporal mientras AISStream no sirve datos
(ver aisstream/issues#257: conexión sana, sin errores, cero mensajes).

Bloque autocontenido y desactivable con una variable de entorno
(`AIS_SYNTHETIC`, en `constants.py`). Presenta la MISMA interfaz que
`AISStreamClient.stream()`, así que `tracker.py`, `client.py`, `models.py` y
`publisher.py` no cambian ni una línea: el productor valida y publica sin
distinguir el origen de los mensajes. Cuando AISStream se recupere, basta con
poner `AIS_SYNTHETIC=false` (o borrar este fichero y las ~10 líneas que lo
enganchan en `producer.py`/`constants.py`).

Los buques y sus IMO son reales — muestreados de `thetis_mrv` en
`synthetic_fixtures.json` — para que el LEFT JOIN por IMO que hará Flink
resuelva de verdad contra la taxonomía EMSA (en particular, los
"Container ship"). Las rutas son trayectos marítimos reales (`searoute`,
evita tierra). El MMSI 990xxxxxx es el marcador: ningún buque real usa ese
prefijo, así que el tráfico sintético es identificable sin ambigüedad si
algún día se mezcla con el real en Kafka.

Reproduce las rarezas del AIS real medidas en `docs/ais_catalogos.md`
(heading=511 ~27%, cog=360 ~10%, nav_status=15 ~10%, ETA centinela ~21%) para
no entrenar a Flink contra un mundo más limpio que el real.
"""

import asyncio
import json
import random
import time
from datetime import datetime, timedelta, timezone
from math import atan2, cos, degrees, radians, sin, sqrt
from pathlib import Path

import searoute as sr

from .. import constants

_FIXTURES_PATH = Path(__file__).parent / "synthetic_fixtures.json"
_TARGET_LOCODES = {"ESVLC", "ESALG", "ESBCN"}
_PROB_DEST_OBJETIVO = 0.55  # fracción de buques (sin puerto base) con destino a los 3 puertos
# Buques "residentes": alternan SIEMPRE entre su puerto base y otro cualquiera, en vez
# de elegir destino al azar. Sin esto, la congestión (>=1 buque atracado/fondeado cerca
# del puerto en la MISMA ventana de 1 min en que otro se aproxima) es una coincidencia
# rara con 242 buques repartidos entre 21 puertos: el puerto objetivo casi nunca tiene
# tráfico. Con 3 residentes por puerto, siempre hay alguien atracado o volviendo.
_RESIDENTES_POR_PUERTO = 3

# (rango_length_m, rango_beam_m, rango_draught_m) por categoría.
_DIM_RANGES = {
    "container": ((150, 400), (25, 59), (8, 16)),
    "bulk": ((150, 300), (23, 50), (8, 18)),
    "general_cargo": ((90, 200), (15, 30), (5, 10)),
    "ro_ro": ((150, 240), (25, 36), (6, 9)),
    "tanker": ((100, 330), (16, 60), (6, 22)),
    "passenger": ((100, 330), (18, 38), (6, 9)),
    "recreational": ((6, 30), (2, 8), (1, 3)),
    "fishing": ((10, 40), (3, 9), (2, 5)),
    "tug": ((20, 40), (6, 12), (3, 6)),
    "sailing": ((8, 25), (2.5, 6), (1, 3)),
    "other": ((20, 100), (5, 18), (2, 8)),
}
# Velocidad de crucero típica (nudos) por categoría.
_SPEED_RANGES = {
    "container": (16, 24), "bulk": (11, 15), "general_cargo": (10, 14),
    "ro_ro": (16, 22), "tanker": (10, 15), "passenger": (18, 25),
    "recreational": (4, 12), "fishing": (6, 10), "tug": (8, 14),
    "sailing": (4, 9), "other": (8, 14),
}
# nav_status "normal" en tránsito para categorías que no navegan a motor.
_UNDERWAY_STATUS = {"fishing": 7, "sailing": 8}
_DWELL_HOURS = (2.0, 18.0)  # tiempo amarrado antes de zarpar a otro destino
_NAME_FIELD_LEN, _CALLSIGN_FIELD_LEN = 20, 7

# Fondeo por congestión: al llegar, un buque solo amarra si el puerto tiene hueco
# libre (menos de `_BERTH_CAPACITY` buques ya amarrados). Si no, se queda fondeado
# (nav_status=1) y lo reintenta cada tick hasta que se libere una plaza — el
# "idle burn" que el JIT de Nautiq busca evitar. `_MAX_ANCHOR_WAIT_HOURS` es una
# válvula de seguridad: pasado ese tiempo atraca igual, para no dejar un buque
# fondeado indefinidamente si la carga de la flota supera la capacidad elegida.
_BERTH_CAPACITY = 2
_MAX_ANCHOR_WAIT_HOURS = 30.0


def _haversine_nm(lat1, lon1, lat2, lon2):
    r_nm = 3440.065
    p1, p2 = radians(lat1), radians(lat2)
    dphi, dlmb = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * r_nm * atan2(sqrt(a), sqrt(1 - a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = radians(lat1), radians(lat2)
    dl = radians(lon2 - lon1)
    y = sin(dl) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return (degrees(atan2(y, x)) + 360) % 360


def _point_along(coords, target_nm):
    """coords: [[lon,lat], ...]. Devuelve (lat, lon, rumbo_grados) a target_nm del inicio."""
    if len(coords) < 2:
        lon, lat = coords[0]
        return lat, lon, 0.0
    acc = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        seg = _haversine_nm(lat1, lon1, lat2, lon2)
        if acc + seg >= target_nm or i == len(coords) - 2:
            frac = 0.0 if seg <= 0 else min(1.0, max(0.0, (target_nm - acc) / seg))
            return (lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac,
                    _bearing_deg(lat1, lon1, lat2, lon2))
        acc += seg
    lon, lat = coords[-1]
    return lat, lon, 0.0


def _pad(s, n):
    """Relleno '@' de ancho fijo, como los campos de texto reales de AIS."""
    s = (s or "")[:n]
    return s + "@" * (n - len(s))


def _time_utc_now() -> str:
    """Formato crudo de AISStream, con nanosegundos: '2026-07-28 17:13:08.621081171 +0000 UTC'."""
    dt = datetime.now(timezone.utc)
    nanos = random.randint(0, 999_999_999)
    return f"{dt:%Y-%m-%d %H:%M:%S}.{nanos:09d} +0000 UTC"


class SyntheticVessel:
    """Estado mutable de un buque simulado: identidad fija + posición/ruta vivas."""

    def __init__(self, tpl: dict, ports: dict):
        cat = tpl["category"]
        len_r, beam_r, draught_r = _DIM_RANGES[cat]
        self.mmsi = tpl["mmsi"]
        self.imo = tpl["imo"]
        self.name = tpl["name"]
        self.callsign = tpl["callsign"]
        self.category = cat
        self.ais_types = tpl["ais_types"]
        self.length_m = round(random.uniform(*len_r))
        self.beam_m = round(random.uniform(*beam_r))
        self.draught_m = round(random.uniform(*draught_r), 1)
        self.speed_knots = round(random.uniform(*_SPEED_RANGES[cat]), 1)

        origin_locode = random.choice(list(ports))
        self.lat = ports[origin_locode]["lat"]
        self.lon = ports[origin_locode]["lon"]
        self.heading = 0.0
        self.phase = "moored"          # arranca "en puerto"; el primer tick lo despacha
        self.moored_until = 0.0
        self.route: list = []
        self.route_nm = 0.0
        self.progress_nm = 0.0
        self.dest_locode: str | None = None
        self.home_locode: str | None = None  # residente: siempre vuelve a este puerto
        self.fondeado_desde: float | None = None  # time.monotonic() al empezar a esperar
        self.eta_dt: datetime | None = None
        self.next_static_at = 0.0
        self.next_position_at = 0.0

    async def route_to(self, dest_locode: str, ports: dict) -> None:
        """Traza una ruta marítima real (searoute) desde la posición actual."""
        d = ports[dest_locode]
        try:
            feat = await asyncio.to_thread(
                sr.searoute, [self.lon, self.lat], [d["lon"], d["lat"]], units="naut")
            coords = feat["geometry"]["coordinates"]
            length_nm = feat["properties"]["length"]
        except Exception:  # noqa: BLE001 — degradación a línea recta si searoute falla
            coords = [[self.lon, self.lat], [d["lon"], d["lat"]]]
            length_nm = _haversine_nm(self.lat, self.lon, d["lat"], d["lon"])
        self.route = coords
        self.route_nm = max(length_nm, 0.1)
        self.progress_nm = 0.0
        self.dest_locode = dest_locode
        self.phase = "transit"
        hours = self.route_nm / max(self.speed_knots, 1.0)
        self.eta_dt = datetime.now(timezone.utc) + timedelta(hours=hours)

    def advance(self, dt_hours: float) -> None:
        """Avanza la posición según la velocidad; detecta llegada a destino."""
        if self.phase != "transit":
            return
        self.progress_nm += self.speed_knots * dt_hours
        if self.progress_nm >= self.route_nm:
            self.progress_nm = self.route_nm
            self.phase = "arriving"    # un tick "anclado" antes de amarrar
        self.lat, self.lon, self.heading = _point_along(self.route, self.progress_nm)


def _choose_destination(vessel: SyntheticVessel, ports: dict) -> str:
    """
    Residente (`home_locode` fijado): alterna sin excepción entre su puerto base y
    cualquier otro — garantiza tráfico recurrente hacia los 3 puertos objetivo.

    Resto de la flota: con `_PROB_DEST_OBJETIVO` va a uno de los 3 puertos; si no,
    a cualquier otro. Aleatorio, sin garantía de converger en un puerto concreto.
    """
    if vessel.home_locode:
        if vessel.dest_locode == vessel.home_locode:
            candidates = [lc for lc in ports if lc != vessel.home_locode]
            return random.choice(candidates)
        return vessel.home_locode

    if random.random() < _PROB_DEST_OBJETIVO:
        pool = [lc for lc in _TARGET_LOCODES if lc in ports and lc != vessel.dest_locode]
        if pool:
            return random.choice(pool)
    candidates = [lc for lc in ports if lc != vessel.dest_locode]
    return random.choice(candidates)


def _asignar_residentes(vessels: list[SyntheticVessel], ports: dict) -> None:
    """
    Fija `home_locode` en `_RESIDENTES_POR_PUERTO` portacontenedores por puerto
    objetivo (categoría "container": su `ship_type` siempre cae en carga 70-79,
    el rango que exige el filtro de destino de Flink). Sin residentes, un puerto
    objetivo concreto puede pasar horas sin un solo buque real, porque la flota se
    reparte al azar entre los 21 puertos del fixture.
    """
    candidatos = [v for v in vessels if v.category == "container"]
    random.shuffle(candidatos)
    i = 0
    for locode in _TARGET_LOCODES:
        if locode not in ports:
            continue
        for v in candidatos[i:i + _RESIDENTES_POR_PUERTO]:
            v.home_locode = locode
        i += _RESIDENTES_POR_PUERTO


class SyntheticFleet:
    """Flota simulada: reloj de avance + generación de mensajes AIS crudos."""

    def __init__(self, vessels: list[SyntheticVessel], ports: dict):
        self.vessels = vessels
        self.ports = ports
        self._last_tick = time.monotonic()
        self._rerouting: set[int] = set()

    @classmethod
    def build(cls) -> "SyntheticFleet":
        data = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
        ports = data["ports"]
        vessels = [SyntheticVessel(tpl, ports) for tpl in data["vessels"]]
        _asignar_residentes(vessels, ports)
        return cls(vessels, ports)

    async def start(self) -> None:
        """Asigna el primer destino/ruta a cada buque y desincroniza sus relojes."""
        now = time.monotonic()
        for v in self.vessels:
            await v.route_to(_choose_destination(v, self.ports), self.ports)
            v.next_static_at = now + random.uniform(0, constants.SYNTHETIC_STATIC_INTERVAL_SECONDS)
            v.next_position_at = now + random.uniform(0, constants.SYNTHETIC_POSITION_INTERVAL_SECONDS)

    async def tick(self) -> None:
        """
        Avanza el reloj de la flota. Idempotente por tiempo real (no por nº de
        llamadas): varios consumidores pueden llamarla sin duplicar el avance.
        """
        now = time.monotonic()
        dt = now - self._last_tick
        if dt < 1.0:
            return
        self._last_tick = now
        dt_hours = dt / 3600.0

        # Ocupación por puerto AL EMPEZAR el tick. Se mutará según se van resolviendo
        # llegadas/zarpes DENTRO de este mismo tick, para no dar el mismo hueco libre
        # a dos buques que llegan a la vez (el orden de `self.vessels` decide cuál de
        # los dos lo gana — arbitrario pero determinista, es sintético).
        ocupacion: dict[str, int] = {}
        for v in self.vessels:
            if v.phase == "moored":
                ocupacion[v.dest_locode] = ocupacion.get(v.dest_locode, 0) + 1

        for v in self.vessels:
            if v.phase == "moored":
                if now >= v.moored_until and id(v) not in self._rerouting:
                    self._rerouting.add(id(v))
                    asyncio.create_task(self._reroute(v))
                continue
            if v.phase == "transit":
                v.advance(dt_hours)
                if v.phase == "arriving":
                    self._resolver_llegada(v, ocupacion, now)
                continue
            if v.phase == "arriving":  # por si una ruta de longitud ~0 llega en el mismo tick
                self._resolver_llegada(v, ocupacion, now)
                continue
            if v.phase == "fondeado":
                hay_hueco = ocupacion.get(v.dest_locode, 0) < _BERTH_CAPACITY
                esperando_demasiado = (now - v.fondeado_desde) > _MAX_ANCHOR_WAIT_HOURS * 3600
                if hay_hueco or esperando_demasiado:
                    self._amarrar(v, ocupacion, now)

    def _resolver_llegada(self, v: SyntheticVessel, ocupacion: dict[str, int], now: float) -> None:
        """Al llegar: amarra si hay hueco en el puerto; si no, se queda fondeado."""
        if ocupacion.get(v.dest_locode, 0) < _BERTH_CAPACITY:
            self._amarrar(v, ocupacion, now)
        else:
            v.phase = "fondeado"
            v.fondeado_desde = now

    @staticmethod
    def _amarrar(v: SyntheticVessel, ocupacion: dict[str, int], now: float) -> None:
        v.phase = "moored"
        v.fondeado_desde = None
        v.moored_until = now + random.uniform(*_DWELL_HOURS) * 3600
        ocupacion[v.dest_locode] = ocupacion.get(v.dest_locode, 0) + 1  # reserva el hueco

    async def _reroute(self, vessel: SyntheticVessel) -> None:
        try:
            await vessel.route_to(_choose_destination(vessel, self.ports), self.ports)
        finally:
            self._rerouting.discard(id(vessel))


def _dimension_split(vessel: SyntheticVessel) -> dict:
    a = round(vessel.length_m * 0.6)
    c = round(vessel.beam_m * 0.5)
    return {"A": a, "B": vessel.length_m - a, "C": c, "D": vessel.beam_m - c}


def build_static_message(vessel: SyntheticVessel, ports: dict) -> dict:
    dest_name = ports[vessel.dest_locode]["name"].upper()
    destination = vessel.dest_locode if (vessel.dest_locode in _TARGET_LOCODES
                                         and random.random() < 0.5) else dest_name
    eta = ({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60} if random.random() < 0.21
           or vessel.eta_dt is None else
           {"Month": vessel.eta_dt.month, "Day": vessel.eta_dt.day,
            "Hour": vessel.eta_dt.hour, "Minute": vessel.eta_dt.minute})
    return {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": vessel.mmsi, "time_utc": _time_utc_now()},
        "Message": {"ShipStaticData": {
            "UserID": vessel.mmsi,
            "ImoNumber": vessel.imo or 0,
            "Name": _pad(vessel.name, _NAME_FIELD_LEN),
            "CallSign": _pad(vessel.callsign, _CALLSIGN_FIELD_LEN),
            "Type": random.choice(vessel.ais_types),
            "Dimension": _dimension_split(vessel),
            "MaximumStaticDraught": vessel.draught_m,
            "Destination": destination,
            "Eta": eta,
        }},
    }


def build_position_message(vessel: SyntheticVessel) -> dict:
    if vessel.phase == "moored":
        sog, nav = 0.0, 5
    elif vessel.phase in ("fondeado", "arriving"):
        # Fondeado de verdad: velocidad casi nula (deriva/garreo sobre el ancla),
        # no la fracción de la velocidad de crucero que tendría navegando.
        sog, nav = round(random.uniform(0.0, 0.3), 1), 1
    else:
        sog = max(0.0, vessel.speed_knots + random.uniform(-1.5, 1.5))
        nav = _UNDERWAY_STATUS.get(vessel.category, 0)
        if vessel.category == "tug" and random.random() < 0.3:
            nav = random.choice([11, 12])
    if random.random() < 0.10:
        nav = 15
    cog = 360 if random.random() < 0.10 else round((vessel.heading + random.uniform(-3, 3)) % 360, 1)
    heading = 511 if random.random() < 0.27 else round(vessel.heading) % 360
    return {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": vessel.mmsi, "time_utc": _time_utc_now()},
        "Message": {"PositionReport": {
            "UserID": vessel.mmsi,
            "Latitude": round(vessel.lat, 6),
            "Longitude": round(vessel.lon, 6),
            "Sog": round(sog, 1),
            "Cog": cog,
            "TrueHeading": heading,
            "NavigationalStatus": nav,
        }},
    }


class SyntheticAISClient:
    """Sustituto de `AISStreamClient`: misma interfaz `.stream()`, datos simulados."""

    def __init__(self, fleet: SyntheticFleet):
        self.fleet = fleet

    async def stream(self, bounding_boxes=None, message_types=None, filter_mmsis=None):
        """`bounding_boxes`/`filter_mmsis` se ignoran: aquí no hay servidor que filtre."""
        want_static = not message_types or "ShipStaticData" in message_types
        want_position = not message_types or "PositionReport" in message_types
        while True:
            await self.fleet.tick()
            now = time.monotonic()
            for v in self.fleet.vessels:
                if want_static and now >= v.next_static_at:
                    v.next_static_at = now + random.uniform(0.7, 1.3) * constants.SYNTHETIC_STATIC_INTERVAL_SECONDS
                    yield build_static_message(v, self.fleet.ports)
                if want_position and now >= v.next_position_at:
                    v.next_position_at = now + random.uniform(0.7, 1.3) * constants.SYNTHETIC_POSITION_INTERVAL_SECONDS
                    yield build_position_message(v)
            await asyncio.sleep(1.0)


async def build_fleet() -> SyntheticFleet:
    fleet = SyntheticFleet.build()
    await fleet.start()
    return fleet
