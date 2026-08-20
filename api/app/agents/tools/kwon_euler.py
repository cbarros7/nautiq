"""
Velocidad JIT (Just-In-Time) por el método Kwon-Euler.

Resuelve el problema inverso de weather routing: dado el tiempo que le
queda al buque hasta que su atraque esté disponible (jit_calculus,
"tiempo_espera_estimado_h") y la ruta + meteo que ya ha resuelto
math_oracle (sea_route + open_meteo), calcula la velocidad de motor
(agua tranquila) que hay que mantener CONSTANTE durante toda la
travesía para llegar justo a tiempo — ni antes (quema combustible de
más para acabar esperando fondeado) ni después (llega tarde y genera
más congestión). La velocidad se mantiene constante a propósito: variar
de velocidad en tránsito quema más combustible que mantenerla estable,
aunque en la práctica pueda haber que corregirla por agenda o mar
gruesa.

Nota de contexto (jit_calculus): los buques bulk registran la mayor
frecuencia de espera externa en puerto, seguidos de tankers y
portacontenedores — son los que más se benefician de esta corrección.

Método
------
1. Kwon (2008) — "Speed loss due to added resistance in wind and waves":
   estima el % de pérdida de velocidad de un buque por mal tiempo en
   función del número de Beaufort, el ángulo relativo buque/meteo y la
   forma del casco (Cb). Kwon publicó una TABLA, no una fórmula cerrada;
   aquí se usa un ajuste polinómico simplificado que reproduce el orden
   de magnitud de esa tabla (ver KWON_C_BETA / KWON_CB_FACTOR) — si el
   TFM necesita precisión de cita académica, sustituir por los valores
   exactos de la tabla original.
2. Integración de Euler: se recorre la ruta discretizada (waypoints de
   sea_route) tramo a tramo; en cada tramo se calcula la velocidad
   efectiva sobre el fondo (V_motor corregida por la pérdida Kwon de la
   meteo de ESE tramo) y se acumula el tiempo de tránsito.
3. Problema inverso: se busca, por bisección, la V_motor constante que
   hace que el tiempo total de tránsito integrado coincida con el
   tiempo objetivo (tiempo_espera_estimado_h de jit_calculus). El
   rango de búsqueda se acota a [0.4, 1.2] × velocidad de diseño real
   del buque (cii_calculus.estimar_v_diseno), no a un rango genérico
   — si no, la bisección puede "converger" sin ningún aviso a
   velocidades físicamente irreales para ese casco concreto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from geopy.distance import geodesic

try:
    from . import cii_calculus  # para reusar CB_POR_TIPO / _normalizar_tipo
except ImportError:
    import cii_calculus


# ──────────────────────────────────────────────────────────────────────
#  ESCALA DE BEAUFORT (estándar meteorológico, umbrales en nudos)
# ──────────────────────────────────────────────────────────────────────

BEAUFORT_UMBRALES_KN: list[tuple[float, int]] = [
    (1, 0), (3, 1), (6, 2), (10, 3), (16, 4), (21, 5),
    (27, 6), (33, 7), (40, 8), (47, 9), (55, 10), (63, 11),
]


def beaufort_desde_viento(wind_speed_kn: float) -> int:
    """Número de Beaufort a partir de la velocidad del viento (nudos)."""
    for umbral, bn in BEAUFORT_UMBRALES_KN:
        if wind_speed_kn < umbral:
            return bn
    return 12


# ──────────────────────────────────────────────────────────────────────
#  PÉRDIDA DE VELOCIDAD (Kwon, 2008 — ajuste simplificado)
# ──────────────────────────────────────────────────────────────────────
# NOTA: Kwon (2008) publica una TABLA (no una fórmula cerrada) de % de
# pérdida de velocidad por Beaufort × ángulo relativo × forma de casco.
# Lo de abajo es un ajuste polinómico propio que reproduce el orden de
# magnitud de esa tabla (referencia habitual en literatura de weather
# routing: pérdidas de ~20-40% en mar de proa a partir de BN7-8 para
# buques de forma media)

KWON_C_BETA: list[tuple[float, float, float]] = [
    # (angulo_min, angulo_max, coeficiente) — 0°=proa (head), 180°=popa (following)
    (0,   30,  1.7),   # mar de proa: máxima resistencia añadida
    (30,  60,  1.4),   # amura
    (60,  90,  1.0),   # a través
    (90,  150, 0.7),   # aleta
    (150, 180, 0.4),   # mar de popa: mínima resistencia añadida
]

KWON_CB_FACTOR: dict[str, float] = {
    # Forma de casco (coeficiente de bloque) -> factor multiplicador.
    # Cascos llenos (bulk/tanker) pierden proporcionalmente más
    # velocidad en mar gruesa que los cascos finos (container/ro-ro).
    "full": 1.15,      # Cb >= 0.78 (bulk, tanker, lng...)
    "average": 1.00,   # 0.65 <= Cb < 0.78
    "fine": 0.85,       # Cb < 0.65 (container, ro-ro, passenger...)
}

PERDIDA_MAXIMA_PCT = 60.0


def _clase_casco(cb: float) -> str:
    if cb >= 0.78:
        return "full"
    if cb >= 0.65:
        return "average"
    return "fine"


def _coeficiente_direccional(angulo_rel_deg: float) -> float:
    for lo, hi, c in KWON_C_BETA:
        if lo <= angulo_rel_deg <= hi:
            return c
    return KWON_C_BETA[-1][2]


def perdida_velocidad_pct(beaufort: int, angulo_rel_deg: float, cb: float) -> float:
    """
    % de pérdida de velocidad de un buque en calado según el ajuste
    simplificado de Kwon (2008): Beaufort, ángulo relativo buque/meteo
    y forma de casco. Devuelve un valor en [0, PERDIDA_MAXIMA_PCT].
    """
    c_beta = _coeficiente_direccional(angulo_rel_deg)
    cb_factor = KWON_CB_FACTOR[_clase_casco(cb)]
    perdida = c_beta * cb_factor * (beaufort ** 1.5)
    return max(0.0, min(PERDIDA_MAXIMA_PCT, perdida))


def _resolver_cb(cb: Optional[float], tipo_buque: Optional[str]) -> float:
    """cb explícito > cb por tipo_buque (tabla de cii_calculus) > 0.70 (media)."""
    if cb is not None:
        return cb
    if tipo_buque:
        tipo_norm = cii_calculus._normalizar_tipo(tipo_buque)
        return cii_calculus.CB_POR_TIPO.get(tipo_norm, 0.70)
    return 0.70


# ──────────────────────────────────────────────────────────────────────
#  RANGO DE BÚSQUEDA DE V_MOTOR: acotado por la velocidad de diseño real
#  del buque (cii_calculus.estimar_v_diseno), no un rango genérico.
# ──────────────────────────────────────────────────────────────────────
# Sin esto, la bisección busca en [4, 30] nudos para CUALQUIER buque, lo
# que puede "converger" (convergio=True, sin ningún aviso) a velocidades
# físicamente irreales para el casco concreto — p.ej. 22kn para un bulk
# carrier cuya velocidad de diseño real es ~13kn.

V_MIN_KN_GENERICO = 4.0
V_MAX_KN_GENERICO = 30.0
MARGEN_V_MAX = 1.20  # +20% sobre la velocidad de diseño: los buques sí
                      # navegan algo por encima de su velocidad de diseño
                      # nominal en la práctica, así que un tope igual a
                      # v_diseno_kn sería demasiado estricto.
FACTOR_V_MIN = 0.40   # slow steaming razonable: 40% de la velocidad de diseño


def _resolver_bounds(
    v_min_kn: Optional[float],
    v_max_kn: Optional[float],
    v_diseno_kn: Optional[float],
) -> tuple[float, float]:
    """
    Prioridad: bound explícito > derivado de v_diseno_kn > genérico.
    """
    if v_min_kn is None:
        v_min_kn = v_diseno_kn * FACTOR_V_MIN if v_diseno_kn else V_MIN_KN_GENERICO
    if v_max_kn is None:
        v_max_kn = v_diseno_kn * MARGEN_V_MAX if v_diseno_kn else V_MAX_KN_GENERICO
    return v_min_kn, v_max_kn


# ──────────────────────────────────────────────────────────────────────
#  GEOMETRÍA: rumbo entre waypoints y ángulo relativo al viento
# ──────────────────────────────────────────────────────────────────────

def rumbo_inicial_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumbo inicial (bearing, 0-360°) del gran círculo de (lat1,lon1) a (lat2,lon2)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    x = math.sin(delta_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angulo_relativo_deg(rumbo_buque_deg: float, direccion_meteo_deg: float) -> float:
    """
    Ángulo relativo (0-180°) entre el rumbo del buque y la dirección
    DESDE la que viene el viento (convención meteorológica de Open-Meteo).
    0° = viento/mar de proa (peor caso); 180° = de popa (mejor caso).
    """
    diff = abs(rumbo_buque_deg - direccion_meteo_deg) % 360
    return diff if diff <= 180 else 360 - diff


# ──────────────────────────────────────────────────────────────────────
#  INTEGRACIÓN DE EULER: tiempo de tránsito para una V_motor constante
# ──────────────────────────────────────────────────────────────────────

@dataclass
class TramoRuta:
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    distancia_nm: float
    # Optional: Open-Meteo devuelve null en celdas que el modelo no
    # cubre (ver _perdida_pct_tramo para cómo se trata la ausencia).
    wind_speed_kn: Optional[float]
    wind_direction_deg: Optional[float]


def construir_tramos(
    waypoints: list[tuple[float, float]],  # [(lon, lat), ...] (sea_route.Route.waypoints)
    wind: list[dict],                      # alineado con waypoints (open_meteo.wind_at_eta)
) -> list[TramoRuta]:
    """
    Construye los tramos de la ruta discretizada, emparejando cada
    tramo con la meteo del waypoint de LLEGADA de ese tramo (la
    condición que se va a encontrar el buque al final del tramo).

    `wind` es la meteo precalculada UNA vez por math_oracle (con una
    velocidad nominal, no la que resuelve este módulo); se trata como
    una foto fija indexada por posición a lo largo de la ruta, no se
    vuelve a pedir a Open-Meteo por cada candidato de velocidad que
    prueba la bisección — el pronóstico apenas cambia en la ventana de
    horas relevante y evitarlo ahorra llamadas de red repetidas.
    """
    if len(waypoints) != len(wind):
        raise ValueError(
            f"waypoints ({len(waypoints)}) y wind ({len(wind)}) deben tener la misma longitud"
        )
    if len(waypoints) < 2:
        raise ValueError("La ruta necesita al menos 2 waypoints")

    tramos = []
    for i in range(len(waypoints) - 1):
        lon1, lat1 = waypoints[i]
        lon2, lat2 = waypoints[i + 1]
        dist_nm = geodesic((lat1, lon1), (lat2, lon2)).nautical
        meteo = wind[i + 1]
        tramos.append(TramoRuta(
            lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2,
            distancia_nm=dist_nm,
            wind_speed_kn=meteo["wind_speed_kn"],
            wind_direction_deg=meteo["wind_direction"],
        ))
    return tramos


def _perdida_pct_tramo(tramo: TramoRuta, cb: float) -> float:
    if tramo.wind_speed_kn is None or tramo.wind_direction_deg is None:
        # Open-Meteo no cubre esta celda (frecuente en tramos costeros,
        # a veces la propia posición del buque) — sin dato de viento no
        # se puede estimar Beaufort ni el ángulo relativo. Se trata
        # como sin penalización en vez de adivinar un peor/mejor caso
        # arbitrario a partir de un dato que no existe.
        return 0.0
    rumbo = rumbo_inicial_deg(tramo.lat1, tramo.lon1, tramo.lat2, tramo.lon2)
    angulo_rel = angulo_relativo_deg(rumbo, tramo.wind_direction_deg)
    bn = beaufort_desde_viento(tramo.wind_speed_kn)
    return perdida_velocidad_pct(bn, angulo_rel, cb)


def tiempo_transito_h(tramos: list[TramoRuta], v_motor_kn: float, cb: float) -> float:
    """
    Integración de Euler: tiempo total de tránsito (horas) manteniendo
    una V_motor constante, tramo a tramo, corrigiendo por la pérdida
    Kwon de la meteo de cada tramo.
    """
    if v_motor_kn <= 0:
        raise ValueError("v_motor_kn debe ser > 0")

    total_h = 0.0
    for tramo in tramos:
        perdida_pct = _perdida_pct_tramo(tramo, cb)
        v_efectiva = v_motor_kn * (1 - perdida_pct / 100.0)
        v_efectiva = max(v_efectiva, 0.5)  # evita división por ~0 en temporal extremo
        total_h += tramo.distancia_nm / v_efectiva

    return total_h


def _perdida_media_pct(tramos: list[TramoRuta], cb: float) -> float:
    """Pérdida Kwon media (%) ponderada por distancia — informativa, no afecta al cálculo."""
    total_dist = sum(t.distancia_nm for t in tramos)
    if total_dist <= 0:
        return 0.0
    acumulado = sum(_perdida_pct_tramo(t, cb) * t.distancia_nm for t in tramos)
    return acumulado / total_dist


# ──────────────────────────────────────────────────────────────────────
#  PROBLEMA INVERSO: velocidad JIT para llegar en tiempo_objetivo_h
# ──────────────────────────────────────────────────────────────────────

@dataclass
class VelocidadJIT:
    v_motor_kn: float
    tiempo_transito_estimado_h: float
    tiempo_objetivo_h: float
    perdida_media_pct: float
    iteraciones: int
    convergio: bool
    nota: Optional[str] = None
    excede_v_diseno: bool = False  # v_motor_kn > v_diseno_kn (si se pasó)


def resolver_velocidad_jit(
    waypoints: list[tuple[float, float]],
    wind: list[dict],
    tiempo_objetivo_h: float,
    tipo_buque: Optional[str] = None,
    cb: Optional[float] = None,
    v_diseno_kn: Optional[float] = None,
    v_min_kn: Optional[float] = None,
    v_max_kn: Optional[float] = None,
    tolerancia_h: float = 0.05,
    max_iter: int = 50,
) -> VelocidadJIT:
    """
    Resuelve, por bisección sobre `tiempo_transito_h` (Euler), la
    velocidad de motor constante V0 tal que el buque llegue a puerto
    exactamente en `tiempo_objetivo_h` horas desde ahora — el
    "tiempo_espera_estimado_h" que jit_calculus ha calculado para este
    buque (eta_buque_objetivo / construir_respuesta_eta).

    `tiempo_transito_h(V0)` es monótona decreciente en V0 (a más
    velocidad, menos tiempo), así que basta con bisección clásica sobre
    [v_min_kn, v_max_kn].

    Parameters
    ----------
    waypoints : list[(lon, lat)]
        Ruta discretizada (sea_route.Route.waypoints /
        state["route"].waypoints en math_oracle).
    wind : list[dict]
        Meteo por waypoint (open_meteo.wind_at_eta / state["wind"] en
        math_oracle), mismo orden y longitud que `waypoints`.
    tiempo_objetivo_h : float
        Horas desde ahora en las que debe llegar el buque (de
        jit_calculus).
    tipo_buque, cb : opcionales
        Forma de casco del buque para el ajuste Kwon. `cb` explícito
        tiene prioridad; si no, se resuelve desde `tipo_buque` con la
        tabla CB_POR_TIPO de cii_calculus; si no se da ninguno, 0.70
        (forma media).
    v_diseno_kn : opcional
        Velocidad de diseño real del buque (p.ej. CIIResult.v_diseno_kn
        de cii_calculus). Si se da, y no se pasan v_min_kn/v_max_kn
        explícitos, el rango de búsqueda se acota a
        [0.4×v_diseno_kn, 1.2×v_diseno_kn] en vez del rango genérico
        [4, 30] nudos — evita que la bisección "converja" (convergio
        =True, sin ningún aviso) a velocidades físicamente irreales
        para el casco concreto.
    v_min_kn, v_max_kn : opcionales
        Fuerzan el rango de búsqueda explícitamente (tienen prioridad
        sobre `v_diseno_kn`). Útiles si se conoce la velocidad mínima
        de gobierno o un límite operativo real del buque.

    Returns
    -------
    VelocidadJIT
        Con `convergio=False` y `nota` explicativa en los dos casos
        límite: la ventana JIT es más corta que ir a v_max_kn (el
        buque ya llega justo o tarde: se recomienda v_max_kn), o más
        larga que ir a v_min_kn (se recomienda v_min_kn, slow steaming
        máximo — sobra tiempo incluso yendo al mínimo). `excede_v_diseno`
        es True si v_motor_kn > v_diseno_kn (cuando se pasó este dato):
        útil para avisar aunque `convergio=True`, ya que converger no
        implica que la velocidad sea la habitual para ese buque.
    """
    tramos = construir_tramos(waypoints, wind)
    cb_resuelto = _resolver_cb(cb, tipo_buque)
    v_min_kn, v_max_kn = _resolver_bounds(v_min_kn, v_max_kn, v_diseno_kn)

    def _excede(v_motor_kn: float) -> bool:
        return v_diseno_kn is not None and v_motor_kn > v_diseno_kn

    def _resultado(v_motor_kn: float, t_transito_h: float, iteraciones: int,
                    convergio: bool, nota: Optional[str] = None) -> VelocidadJIT:
        return VelocidadJIT(
            v_motor_kn=round(v_motor_kn, 2),
            tiempo_transito_estimado_h=round(t_transito_h, 2),
            tiempo_objetivo_h=round(tiempo_objetivo_h, 2),
            perdida_media_pct=round(_perdida_media_pct(tramos, cb_resuelto), 1),
            iteraciones=iteraciones,
            convergio=convergio,
            nota=nota,
            excede_v_diseno=_excede(v_motor_kn),
        )

    t_min = tiempo_transito_h(tramos, v_max_kn, cb_resuelto)  # tránsito más corto posible
    t_max = tiempo_transito_h(tramos, v_min_kn, cb_resuelto)  # tránsito más largo posible

    if tiempo_objetivo_h <= t_min:
        return _resultado(
            v_max_kn, t_min, 0, False,
            nota="Ventana JIT insuficiente incluso a v_max_kn: el buque llega "
                 "justo o tarde yendo a máxima velocidad.",
        )

    if tiempo_objetivo_h >= t_max:
        return _resultado(
            v_min_kn, t_max, 0, False,
            nota="Sobra tiempo incluso a v_min_kn: slow steaming máximo, el "
                 "buque llegaría antes de tiempo aun así.",
        )

    lo, hi = v_min_kn, v_max_kn
    v_motor = (lo + hi) / 2
    for i in range(1, max_iter + 1):
        v_motor = (lo + hi) / 2
        t_actual = tiempo_transito_h(tramos, v_motor, cb_resuelto)
        error_h = t_actual - tiempo_objetivo_h

        if abs(error_h) <= tolerancia_h:
            return _resultado(v_motor, t_actual, i, True)

        # tiempo_transito_h decrece con v: si tardamos más de lo
        # objetivo, hay que subir el suelo de búsqueda (ir más rápido).
        if t_actual > tiempo_objetivo_h:
            lo = v_motor
        else:
            hi = v_motor

    t_final = tiempo_transito_h(tramos, v_motor, cb_resuelto)
    return _resultado(
        v_motor, t_final, max_iter, False,
        nota=f"No convergió dentro de {tolerancia_h}h en {max_iter} iteraciones; "
             "se devuelve la mejor aproximación.",
    )


def velocidad_jit_desde_oracle_state(
    state: dict,
    tiempo_objetivo_h: float,
    tipo_buque: Optional[str] = None,
    cb: Optional[float] = None,
    v_diseno_kn: Optional[float] = None,
    **kwargs,
) -> VelocidadJIT:
    """
    Azúcar sintáctico: resuelve la velocidad JIT directamente a partir
    de un OracleState de math_oracle (state["route"].waypoints,
    state["wind"]), sin que el llamador tenga que desempaquetarlo.
    """
    return resolver_velocidad_jit(
        waypoints=state["route"].waypoints,
        wind=state["wind"],
        tiempo_objetivo_h=tiempo_objetivo_h,
        tipo_buque=tipo_buque,
        cb=cb,
        v_diseno_kn=v_diseno_kn,
        **kwargs,
    )


# ──────────────────────────────────────────────────────────────────────
#  EJEMPLO DE USO
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import datetime, timezone

    try:
        from . import sea_route, open_meteo
    except ImportError:
        import sea_route
        import open_meteo

    origen_lat, origen_lon = 41.492474, 4.455705
    puerto = sea_route.Port("ESBCN", "Barcelona", 41.324340, 2.161924)

    # 1) Lo que ya resuelve math_oracle (fetch_route -> fetch_weather),
    #    con una velocidad nominal cualquiera sólo para fijar el pronóstico.
    ruta = sea_route.route_to_port(origen_lat, origen_lon, puerto, speed_knot=14.0)
    puntos_con_eta = open_meteo.waypoints_with_eta(
        ruta.waypoints, 14.0, datetime.now(timezone.utc)
    )
    viento = open_meteo.wind_at_eta(puntos_con_eta)

    # 2) Lo que da jit_calculus para el buque objetivo (aquí, a mano,
    #    en vez de eta_buque_objetivo(...)["tiempo_espera_estimado_h"]).
    tiempo_objetivo_h = 18.0

    # 3) Lo que da cii_calculus (CIIResult.v_diseno_kn) — acota la
    #    búsqueda a [0.4, 1.2] × v_diseno_kn en vez del rango genérico.
    v_diseno_kn = cii_calculus.estimar_v_diseno(eslora_m=190.0, tipo_buque="Bulk carrier")

    resultado = resolver_velocidad_jit(
        waypoints=ruta.waypoints,
        wind=viento,
        tiempo_objetivo_h=tiempo_objetivo_h,
        tipo_buque="Bulk carrier",
        v_diseno_kn=v_diseno_kn,
    )

    print("=" * 60)
    print("  VELOCIDAD JIT (Kwon-Euler)")
    print("=" * 60)
    print(f"  Distancia ruta:             {ruta.distance_nm:.1f} nm")
    print(f"  Tiempo objetivo (jit_calc): {tiempo_objetivo_h:.1f} h")
    print(f"  Velocidad de diseño:        {v_diseno_kn:.2f} kn (rango de búsqueda: "
          f"{v_diseno_kn * FACTOR_V_MIN:.1f}-{v_diseno_kn * MARGEN_V_MAX:.1f} kn)")
    print(f"  Velocidad JIT recomendada:  {resultado.v_motor_kn:.2f} kn")
    print(f"  Tiempo tránsito estimado:   {resultado.tiempo_transito_estimado_h:.1f} h")
    print(f"  Pérdida Kwon media:         {resultado.perdida_media_pct:.1f} %")
    print(f"  Excede v_diseno:            {resultado.excede_v_diseno}")
    print(f"  Convergió:                  {resultado.convergio} ({resultado.iteraciones} it.)")
    if resultado.nota:
        print(f"  Nota:                       {resultado.nota}")
    print("=" * 60)
