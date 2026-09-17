from datetime import datetime, timedelta, timezone

from geopy.distance import geodesic
from pydantic import BaseModel, model_validator
import requests


class _MarineHourly(BaseModel):
    time: list[str]
    # Open-Meteo devuelve null en celdas que el modelo de olas no cubre
    # (típicamente costeras) — Optional aquí, no float, o Pydantic tumba
    # la recomendación entera (incluida la llamada al LLM ya pagada)
    # por un solo valor null en 168 horas × N waypoints.
    wave_height: list[float | None]
    wave_direction: list[float | None]
    wave_period: list[float | None]

    @model_validator(mode="after")
    def _series_alineadas(self) -> "_MarineHourly":
        n = len(self.time)
        if len(self.wave_height) != n or len(self.wave_direction) != n or len(self.wave_period) != n:
            raise ValueError("Series horarias de oleaje con longitudes inconsistentes")
        return self


class _MarineLocationResult(BaseModel):
    hourly: _MarineHourly


class _WindHourly(BaseModel):
    time: list[str]
    wind_speed_10m: list[float | None]
    wind_direction_10m: list[float | None]
    wind_gusts_10m: list[float | None]

    @model_validator(mode="after")
    def _series_alineadas(self) -> "_WindHourly":
        n = len(self.time)
        if len(self.wind_speed_10m) != n or len(self.wind_direction_10m) != n or len(self.wind_gusts_10m) != n:
            raise ValueError("Series horarias de viento con longitudes inconsistentes")
        return self


class _WindLocationResult(BaseModel):
    hourly: _WindHourly


def _parsed_locations(
    raw_results: list,
    points_with_eta: list[tuple[float, float, datetime]],
    model_cls: type[BaseModel],
) -> list:
    """Valida que Open-Meteo devolvió una ubicación por waypoint pedido, en el mismo orden."""
    if len(raw_results) != len(points_with_eta):
        raise ValueError(
            f"Open-Meteo devolvió {len(raw_results)} ubicaciones, "
            f"se esperaban {len(points_with_eta)} (una por waypoint)."
        )
    return [model_cls.model_validate(r) for r in raw_results]


def _nearest_hour_index(hourly_times: list[str], eta: datetime) -> int:
    """Índice de la hora del array más cercana a `eta`."""
    return min(
        range(len(hourly_times)),
        key=lambda i: abs(
            datetime.fromisoformat(hourly_times[i]).replace(tzinfo=timezone.utc) - eta
        ),
    )


def waypoints_with_eta(
    waypoints: list[tuple[float, float]],  # [(lon, lat), ...]
    speed_knot: float,
    departure_time: datetime,
) -> list[tuple[float, float, datetime]]:
    """Añade el ETA estimado a cada waypoint, acumulando distancia/velocidad."""
    result = [(*waypoints[0], departure_time)]
    accumulated_nm = 0.0

    for (lon1, lat1), (lon2, lat2) in zip(waypoints, waypoints[1:]):
        seg_nm = geodesic((lat1, lon1), (lat2, lon2)).nautical
        accumulated_nm += seg_nm
        hours_elapsed = accumulated_nm / speed_knot
        eta = departure_time + timedelta(hours=hours_elapsed)
        result.append((lon2, lat2, eta))

    return result


#: Máximo de puntos por los que se consulta meteo. Open-Meteo NO factura por
#: petición HTTP sino por LOCALIZACIÓN: una petición con 14 waypoints consume
#: 14 llamadas de cuota, no 1. Con rutas de 14 puntos de media (hasta 63) y dos
#: APIs, cada alerta costaba ~28 llamadas — suficiente para agotar el free tier
#: de 10.000/día y devolver 429 a todo el sistema.
#:
#: Seis puntos bastan: la integración de Euler conserva los tramos completos de
#: la derrota, solo toma la meteo del punto muestreado más próximo. Sobre 300
#: millas eso son muestras cada ~60 millas, escala a la que el estado del mar
#: no cambia lo bastante como para alterar la velocidad recomendada.
MAX_PUNTOS_METEO = 6

_CAMPOS_OLEAJE = ("wave_height", "wave_direction", "wave_period")
_CAMPOS_VIENTO = ("wind_speed_kn", "wind_direction", "wind_gusts_kn")


def submuestrear_para_meteo(
    points_with_eta: list[tuple[float, float, datetime]],
    maximo: int = MAX_PUNTOS_METEO,
) -> tuple[list[tuple[float, float, datetime]], list[int]]:
    """
    Reduce los puntos por los que se pregunta al proveedor de meteo.

    Devuelve (puntos_muestreados, mapa), donde `mapa[i]` es el índice del
    punto muestreado cuya meteo le corresponde al waypoint original `i`.
    Se conservan siempre el primero y el último, que son la posición
    actual del buque y el puerto.
    """
    n = len(points_with_eta)
    if n <= maximo:
        return points_with_eta, list(range(n))

    paso = (n - 1) / (maximo - 1)
    indices = sorted({round(k * paso) for k in range(maximo)})
    muestreados = [points_with_eta[i] for i in indices]
    mapa = [min(range(len(indices)), key=lambda k: abs(indices[k] - i)) for i in range(n)]
    return muestreados, mapa


def _expandir(
    valores: list[dict],
    mapa: list[int],
    points_with_eta: list[tuple[float, float, datetime]],
) -> list[dict]:
    """
    Reparte la meteo muestreada sobre todos los waypoints originales.

    Cada waypoint conserva SUS coordenadas y su ETA —son los que viajan al
    contrato— y toma los valores meteorológicos del punto muestreado más
    cercano.
    """
    salida = []
    for i, (lon, lat, eta) in enumerate(points_with_eta):
        registro = dict(valores[mapa[i]])
        registro.update({"lat": lat, "lon": lon, "eta": eta})
        salida.append(registro)
    return salida


def meteo_no_disponible(
    points_with_eta: list[tuple[float, float, datetime]],
    campos: tuple[str, ...],
) -> list[dict]:
    """
    Serie meteorológica vacía, con la forma y longitud que espera el resto
    del pipeline pero sin valores.

    Es lo que se usa cuando el proveedor no responde. Los `None` no son un
    parche: es el mismo valor que ya devuelve Open-Meteo para celdas que su
    modelo no cubre, y kwon_euler lo interpreta como "sin penalización por
    meteo" en vez de inventarse un estado del mar.
    """
    return [
        {"lat": lat, "lon": lon, "eta": eta, **{c: None for c in campos}}
        for lon, lat, eta in points_with_eta
    ]


def marine_weather_at_eta(
    points_with_eta: list[tuple[float, float, datetime]],
) -> list[dict]:
    lats = ",".join(str(lat) for _, lat, _ in points_with_eta)
    lons = ",".join(str(lon) for lon, _, _ in points_with_eta)

    # rango que cubre desde el primer hasta el último ETA
    start_date = min(eta for _, _, eta in points_with_eta).date().isoformat()
    end_date = max(eta for _, _, eta in points_with_eta).date().isoformat()

    response = requests.get(
        "https://marine-api.open-meteo.com/v1/marine",
        params={
            "latitude": lats,
            "longitude": lons,
            "hourly": "wave_height,wave_direction,wave_period",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        },
        timeout=10,
    )
    response.raise_for_status()
    results = _parsed_locations(response.json(), points_with_eta, _MarineLocationResult)
    # para cada waypoint, response da una lista de horas y valores de oleaje, pero no necesariamente coincide la hora exacta con el ETA del waypoint.
    # por eso, para cada waypoint, buscamos la hora más cercana al ETA y devolvemos los valores de oleaje correspondientes a esa hora.

    output = []
    for (lon, lat, eta), loc_result in zip(points_with_eta, results):
        idx = _nearest_hour_index(loc_result.hourly.time, eta)
        output.append({
            "lat": lat,
            "lon": lon,
            "eta": eta,
            "wave_height": loc_result.hourly.wave_height[idx],
            "wave_direction": loc_result.hourly.wave_direction[idx],
            "wave_period": loc_result.hourly.wave_period[idx],
        })
    return output


def wind_at_eta(
    points_with_eta: list[tuple[float, float, datetime]],
) -> list[dict]:
    """Viento (velocidad, dirección, rachas) para cada waypoint en su ETA estimado."""
    lats = ",".join(str(lat) for _, lat, _ in points_with_eta)
    lons = ",".join(str(lon) for lon, _, _ in points_with_eta)

    start_date = min(eta for _, _, eta in points_with_eta).date().isoformat()
    end_date = max(eta for _, _, eta in points_with_eta).date().isoformat()

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lats,
            "longitude": lons,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "wind_speed_unit": "kn",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "UTC",
        },
        timeout=10,
    )
    response.raise_for_status()
    results = _parsed_locations(response.json(), points_with_eta, _WindLocationResult)

    output = []
    for (lon, lat, eta), loc_result in zip(points_with_eta, results):
        idx = _nearest_hour_index(loc_result.hourly.time, eta)
        output.append({
            "lat": lat,
            "lon": lon,
            "eta": eta,
            "wind_speed_kn": loc_result.hourly.wind_speed_10m[idx],
            "wind_direction": loc_result.hourly.wind_direction_10m[idx],
            "wind_gusts_kn": loc_result.hourly.wind_gusts_10m[idx],
        })
    return output


def meteo_de_ruta(
    points_with_eta: list[tuple[float, float, datetime]],
) -> tuple[list[dict], list[dict]]:
    """
    Oleaje y viento para toda la derrota, submuestreando los puntos por los
    que se pregunta (ver MAX_PUNTOS_METEO).

    El submuestreo se hace UNA vez y se comparte entre las dos APIs, para
    que ambas consulten exactamente las mismas localizaciones.

    Propaga cualquier fallo del proveedor: decidir si un 429 degrada o
    interrumpe el cálculo es del orquestador, no de este módulo.
    """
    muestreados, mapa = submuestrear_para_meteo(points_with_eta)
    oleaje = _expandir(marine_weather_at_eta(muestreados), mapa, points_with_eta)
    viento = _expandir(wind_at_eta(muestreados), mapa, points_with_eta)
    return oleaje, viento


def meteo_de_ruta_no_disponible(
    points_with_eta: list[tuple[float, float, datetime]],
) -> tuple[list[dict], list[dict]]:
    """Series vacías de oleaje y viento, para el caso degradado."""
    return (
        meteo_no_disponible(points_with_eta, _CAMPOS_OLEAJE),
        meteo_no_disponible(points_with_eta, _CAMPOS_VIENTO),
    )
