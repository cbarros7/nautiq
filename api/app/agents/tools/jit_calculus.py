"""
Módulo de estimación de tiempos de espera portuaria para el buque.

Basado en datos empíricos de:
  - Ma, Zhou & Zhu (2023) — "Identification and analysis of ship waiting
    behavior outside the port based on AIS data", Scientific Reports 13:11267
  - Wijaya & Nakamura (2024) — "Port performance indicators construction
    based on AIS-generated trajectory segmentation and classification"
  - Wu & Aarsnes (2017) — "An Introduction to Assessing Bunkering Operations
    Through AIS Data", NTNU

Sistema de colas segmentado por compatibilidad de atraque (eslora),
con tiempos de servicio diferenciados por tipo de buque y factor de corrección
por tamaño.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

try:
    from . import db_conn  # ejecución como paquete: -m app.agents.tools.jit_calculus
except ImportError:
    import db_conn  # ejecución como script suelto: python jit_calculus.py


# ──────────────────────────────────────────────────────────────────────
#  CONSTANTES EMPÍRICAS (calibradas con los papers)
# ──────────────────────────────────────────────────────────────────────

class TipoBuque(str, Enum):
    CONTAINER = "container"
    BULK = "bulk"
    TANKER = "tanker"
    GENERAL_CARGO = "general_cargo"
    RORO = "roro"
    LNG = "lng"
    OFFSHORE = "offshore"
    PASSENGER = "passenger"
    OTHER = "other"


# Tiempo medio de servicio en puerto (horas) por tipo de buque.
# Fuente: Ma et al. (2023), Table 3 — "harbour operation time"
#   Container: 27.8h  |  Bulk: 41.5h  |  Tanker: 48.8h
# Complementado con Wijaya & Nakamura (2024) para contenedores (~22h en
# Singapur).  Se usa la media de Qingdao como referencia conservadora.
TIEMPO_SERVICIO_HORAS: dict[str, float] = {
    TipoBuque.CONTAINER:     28.0,
    TipoBuque.BULK:          42.0,
    TipoBuque.TANKER:        49.0,
    TipoBuque.GENERAL_CARGO: 36.0,   # estimado entre container y bulk
    TipoBuque.RORO:          24.0,   # Wijaya (2024): RO-RO 24-48h fondeo
    TipoBuque.LNG:           52.0,   # Wu & Aarsnes (2017): ~14h bunkering + ops
    TipoBuque.OFFSHORE:      20.0,   # operaciones más cortas
    TipoBuque.PASSENGER:     10.0,   # estimado: turnaround de crucero/ferry,
                                      # no cubierto por los papers citados
                                      # (solo tratan buques de carga)
    TipoBuque.OTHER:         36.0,   # media general
}


# Coeficiente de variación (CV = σ/μ) del tiempo de servicio por tipo.
# Estimado a partir de las distribuciones de probabilidad de Ma et al.
# (2023), Figuras 6 y 7: rango visible ≈ 3.3σ (intervalo 5%-95%).
#   Container: rango ~35h / 3.3 ≈ σ=10.5h → CV=10.5/28 = 0.38
#   Bulk:      rango ~52h / 3.3 ≈ σ=15.8h → CV=15.8/42 = 0.38
#   Tanker:    rango ~80h / 3.3 ≈ σ=24.2h → CV=24.2/49 = 0.49
CV_SERVICIO: dict[str, float] = {
    TipoBuque.CONTAINER:     0.38,
    TipoBuque.BULK:          0.38,
    TipoBuque.TANKER:        0.49,
    TipoBuque.GENERAL_CARGO: 0.40,
    TipoBuque.RORO:          0.30,
    TipoBuque.LNG:           0.50,
    TipoBuque.OFFSHORE:      0.35,
    TipoBuque.PASSENGER:     0.25,   # estimado: operativa programada/regular,
                                      # menos variable que la carga
    TipoBuque.OTHER:         0.40,
}
# Factor de corrección del tiempo de espera por rango de eslora.
# Fuente: Ma et al. (2023), Table 4.
#   <100m → 39.5h   100-200m → 38.2h   200-300m → 48.8h   ≥300m → 54.6h
# Normalizado respecto al grupo 100-200m (referencia = 1.0):
FACTOR_ESLORA: list[tuple[float, float, float]] = [
    # (eslora_min, eslora_max, factor)
    (0,    100,  1.03),
    (100,  200,  1.00),
    (200,  300,  1.28),
    (300,  600,  1.43),
]

# Tiempo medio de maniobra fondeo ↔ atraque (horas).
# Fuente: Wijaya & Nakamura (2024) — mediana en Singapur: 0.92h ≈ 55 min
TIEMPO_MANIOBRA_H: float = 1.0

# Rangos de eslora para segmentar la compatibilidad de atraques.
# Un buque de un rango sólo compite por atraques de su rango o superior.
SEGMENTOS_ATRAQUE: list[tuple[float, float, str]] = [
    (0,    150,  "small"),
    (150,  250,  "medium"),
    (250,  350,  "large"),
    (350,  600,  "vlarge"),
]


# ──────────────────────────────────────────────────────────────────────
#  CÓDIGO DE TIPO DE BUQUE AIS (ITU-R M.1371-5, tabla 53, "Type of
#  ship and cargo type") — cuando no hay texto ni IMO para resolver el
#  ship_type real (p.ej. los buques de la cola del puerto en paquete_2,
#  que llegan con "tipo_buque" como código numérico 0-99 en vez de imo
#  o un string tipo "Bulk carrier").
# ──────────────────────────────────────────────────────────────────────
# LIMITACIÓN DE FONDO (no es que falten códigos por mapear: el propio
# estándar no los tiene): AIS no distingue la FORMA del buque dentro de
# "Carga" (70-79) ni de "Tanque" (80-89) — un Ro-Ro, un granelero, un
# portacontenedores y un general cargo son TODOS "70..79" (esas
# subdivisiones son por categoría de PELIGROSIDAD de la carga, no por
# forma del casco); un petrolero, un químico y un LNG carrier son
# TODOS "80..89" por el mismo motivo. No existe ningún código AIS que
# permita recuperar Ro-Ro/bulk/container/LNG/chemical por separado —
# eso sólo se resuelve con precisión vía IMO contra thetis_mrv, por eso
# esta función es el ÚLTIMO fallback en parse_contrato (después de
# intentar la BBDD), nunca la primera opción.
#
# Tabla completa de rangos (0-99):
#   20-29 WIG · 30 pesca · 31-32 remolque · 33 dragado/obras submarinas
#   34 buceo · 35 militar · 36 vela · 37 recreo · 40-49 alta velocidad
#   (HSC) · 50 práctico · 51 SAR · 52 remolcador · 53 tender de puerto
#   54 antipolución · 55 fuerzas del orden · 58 transporte médico
#   59 no combatiente · 60-69 Pasaje · 70-79 Carga · 80-89 Tanque
#   90-99 Otro tipo

def _tipo_desde_codigo_ais(codigo: int) -> TipoBuque:
    if 60 <= codigo <= 69:
        return TipoBuque.PASSENGER
    if 70 <= codigo <= 79:
        return TipoBuque.GENERAL_CARGO
    if 80 <= codigo <= 89:
        return TipoBuque.TANKER
    if 40 <= codigo <= 49:
        return TipoBuque.PASSENGER  # HSC: mayoritariamente ferries rápidos
    if codigo in (31, 32, 33, 50, 51, 52, 53, 54):
        return TipoBuque.OFFSHORE  # remolque, dragado, práctico, SAR, tender, antipolución
    return TipoBuque.OTHER


# ──────────────────────────────────────────────────────────────────────
#  DATACLASSES
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Buque:
    mmsi: str
    eslora: float
    tipo: str
    imo: Optional[str] = None
    es_objetivo: bool = False  # True si es el buque del "paquete 1" fusionado

    @property
    def tipo_enum(self) -> TipoBuque:
        """Mapea el string de tipo a TipoBuque, con fallback a OTHER."""
        raw = self.tipo.strip().lower().replace(" ", "_")
        if raw.isdigit():
            # Código AIS numérico (p.ej. "70"), no texto — ver
            # _tipo_desde_codigo_ais para la nota de precisión.
            return _tipo_desde_codigo_ais(int(raw))
        try:
            return TipoBuque(raw)
        except ValueError:
            # Intentar mapeos comunes
            alias = {
                "contenedor": TipoBuque.CONTAINER,
                "portacontenedores": TipoBuque.CONTAINER,
                "granelero": TipoBuque.BULK,
                "bulk_carrier": TipoBuque.BULK,
                "petrolero": TipoBuque.TANKER,
                "oil_tanker": TipoBuque.TANKER,
                "chemical_tanker": TipoBuque.TANKER,
                "gas_carrier": TipoBuque.LNG,
                "lng_tanker": TipoBuque.LNG,
                "ro-ro": TipoBuque.RORO,
                "roro_cargo": TipoBuque.RORO,
                "cargo": TipoBuque.GENERAL_CARGO,
                "general": TipoBuque.GENERAL_CARGO,
                "supply": TipoBuque.OFFSHORE,
                "offshore_supply": TipoBuque.OFFSHORE,

                # Categorías AIS/EMSA reales (campo "ship_type" del feed)
                "container_ship": TipoBuque.CONTAINER,
                "container/ro-ro_cargo_ship": TipoBuque.CONTAINER,
                "general_cargo_ship": TipoBuque.GENERAL_CARGO,
                "refrigerated_cargo_carrier": TipoBuque.GENERAL_CARGO,
                "combination_carrier": TipoBuque.BULK,  # OBO: bulk/oil híbrido
                "vehicle_carrier": TipoBuque.RORO,       # PCTC, opera por rampa como ro-ro
                "ro-ro_ship": TipoBuque.RORO,
                "lng_carrier": TipoBuque.LNG,
                "passenger_ship": TipoBuque.PASSENGER,
                "passenger_ship_(cruise_passenger_ship)": TipoBuque.PASSENGER,
                "ro-pax_ship": TipoBuque.PASSENGER,      # dominado por operativa de pasaje
                "other_ship_types_(offshore)": TipoBuque.OFFSHORE,
                "other_ship_types": TipoBuque.OTHER,
            }
            return alias.get(raw, TipoBuque.OTHER)

    @property
    def segmento_atraque(self) -> str:
        for lo, hi, seg in SEGMENTOS_ATRAQUE:
            if lo <= self.eslora < hi:
                return seg
        return "vlarge"

    @property
    def factor_eslora(self) -> float:
        for lo, hi, f in FACTOR_ESLORA:
            if lo <= self.eslora < hi:
                return f
        return 1.43  # ≥300m

    @property
    def cv_servicio(self) -> float:
        """Coeficiente de variación del tiempo de servicio."""
        return CV_SERVICIO.get(self.tipo_enum, 0.40)
 
    @property
    def tiempo_servicio_h(self) -> float:
        """Tiempo medio de servicio en puerto (horas), ajustado por eslora."""
        base = TIEMPO_SERVICIO_HORAS.get(self.tipo_enum, 36.0)
        return base * self.factor_eslora    
    
    @property
    def varianza_servicio_h2(self) -> float:
        """Varianza del tiempo de servicio (h²)."""
        mu = self.tiempo_servicio_h
        cv = self.cv_servicio
        return (cv * mu) ** 2


@dataclass
class Puerto:
    nombre: str
    # Número total de atraques por segmento.
    # Si no se conoce, se infiere del nº de buques atracados + margen.
    atraques_por_segmento: dict[str, int] = field(default_factory=dict)


@dataclass
class EstimacionEspera:
    mmsi: str
    eslora: float
    tipo: str
    segmento: str
    estado: str                    # "fondeado" | "en_camino"
    posicion_cola: int
    atraques_compatibles: int
    tiempo_servicio_estimado_h: float
    tiempo_espera_estimado_h: float
    componentes: dict = field(default_factory=dict)
    es_objetivo: bool = False  # True si es el buque del "paquete 1" fusionado


# ──────────────────────────────────────────────────────────────────────
#  MOTOR DE CÁLCULO
# ──────────────────────────────────────────────────────────────────────

class EstimadorTiempoEspera:
    """
    Estima el tiempo de espera de cada buque fondeado y en camino,
    modelando el puerto como un sistema de colas M/G/c segmentado
    por compatibilidad de atraque (eslora).

    Parámetros del modelo
    ---------------------
    - Segmentación de atraques: los buques compiten sólo por atraques
      compatibles con su eslora.
    - Tiempo de servicio: μ(tipo) × factor(eslora).
    - Posición en cola: los fondeados van primero (FIFO), después los
      en camino (orden de entrada en el JSON, proxy de ETA).
    - Tiempo de liberación del próximo atraque: se estima como
      μ_medio_atracados / 2 (media de la distribución residual uniforme).

    Fórmula
    -------
    T_espera(buque_k) =
        T_liberacion_primer_atraque
        + (posicion_cola_k - 1) × μ(k) / c_compatibles
        + T_maniobra

    Donde:
    - T_liberacion = μ_medio_atracados_compatibles/2
    - c_compatibles = atraques que pueden servir al segmento del buque
    - T_maniobra = 1.0 h (Wijaya & Nakamura, 2024)

    Nota sobre T_liberacion: el tiempo residual esperado de un servicio
    en curso es, en general, E[S²]/(2·E[S]) = E[S]/2 + Var(S)/(2·E[S])
    (teoría de renovación). Sin datos reales de varianza por tipo de
    buque, usar μ/2 equivale a asumir servicio determinista (Var=0),
    el caso más optimista posible. Aquí se usa μ/2 más CV (coeficiente varianza)

    El término (posicion_cola_k - 1) × μ(k) / c_compatibles modela la
    liberación de atraques como un proceso continuo (aproximación fluida):
    cada atraque adicional del segmento libera, en media, cada μ(k)/c
    horas, en vez de asumir que los 'c' atraques se liberan todos a la
    vez en T_liberacion. Esto evita el escalón artificial que tendría un
    modelo por lotes, en el que las posiciones 2..c obtendrían la misma
    espera que la posición 1.
    """

    def __init__(
        self,
        puerto: Puerto,
        atracados: list[Buque],
        fondeados: list[Buque],
        en_camino: list[Buque],
    ):
        self.puerto = puerto
        self.atracados = atracados
        self.fondeados = fondeados
        self.en_camino = en_camino

        # Inferir atraques por segmento si no se proporcionan
        if not self.puerto.atraques_por_segmento:
            self.puerto.atraques_por_segmento = self._inferir_atraques()

    def _inferir_atraques(self) -> dict[str, int]:
        """
        Si no se conoce el nº total de atraques, se infiere del nº de
        buques atracados + un margen del 20% (redondeado arriba).
        Esto asume una ocupación ~83%, coherente con el umbral de
        congestión del 85% citado por UNCTAD.
        """
        conteo: dict[str, int] = {}
        for b in self.atracados:
            seg = b.segmento_atraque
            conteo[seg] = conteo.get(seg, 0) + 1

        # Asegurar que todos los segmentos con demanda tengan al menos 1
        for b in self.fondeados + self.en_camino:
            seg = b.segmento_atraque
            if seg not in conteo:
                conteo[seg] = 0

        atraques: dict[str, int] = {}
        for seg, n in conteo.items():
            atraques[seg] = max(1, math.ceil(n * 1.2))

        return atraques

    def _tiempo_liberacion_segmento(self, segmento: str) -> float:
        """
        Estima cuánto falta para que se libere el próximo atraque en un
        segmento, usando la fórmula del tiempo residual de inspección:
 
            E[R] = E[S²] / (2·E[S]) = μ/2 · (1 + CV²)
 
        Donde CV = σ/μ es el coeficiente de variación del servicio.
        Esto corrige el sesgo de asumir distribución uniforme (μ/2),
        que subestima el residual cuando la varianza es alta.
 
        Para múltiples buques atracados, E[R] se calcula como la media
        ponderada de los residuales individuales, y luego se toma el
        mínimo esperado de c servidores: E[R_min] ≈ E[R] / c.
        """
        atracados_seg = [b for b in self.atracados
                         if b.segmento_atraque == segmento]
        if not atracados_seg:
            return 0.0  # atraque libre → sin espera por liberación
 
        # Tiempo residual medio por buque: μ/2 · (1 + CV²)
        residuales = []
        for b in atracados_seg:
            mu = b.tiempo_servicio_h
            cv = b.cv_servicio
            r = (mu / 2.0) * (1.0 + cv ** 2)
            residuales.append(r)
 
        # Media de los residuales
        r_medio = sum(residuales) / len(residuales)
 
        # Con c atraques ocupados, el primero en liberarse tiene
        # un residual ≈ R_medio / c (aprox. mínimo de c variables)
        c = self._atraques_compatibles(segmento)
        c_ocupados = min(len(atracados_seg), c)
 
        return r_medio / max(1, c_ocupados)

    def _atraques_compatibles(self, segmento: str) -> int:
        """
        Devuelve el nº de atraques que pueden servir a un segmento dado.
        Un buque puede usar atraques de su segmento y de segmentos superiores,
        pero en la práctica un buque pequeño no suele ir a un atraque de VLCC.
        Simplificación: sólo compite en su propio segmento.
        """
        return max(1, self.puerto.atraques_por_segmento.get(segmento, 1))

    def estimar(self) -> list[EstimacionEspera]:
        """
        Calcula el tiempo de espera estimado para cada buque fondeado
        y en camino.

        Returns
        -------
        list[EstimacionEspera]
            Lista ordenada de estimaciones (fondeados primero, luego en camino).
        """
        resultados: list[EstimacionEspera] = []

        # Construir la cola por segmento: fondeados primero, luego en camino
        cola_por_segmento: dict[str, list[tuple[Buque, str]]] = {}
        for b in self.fondeados:
            seg = b.segmento_atraque
            cola_por_segmento.setdefault(seg, []).append((b, "fondeado"))
        for b in self.en_camino:
            seg = b.segmento_atraque
            cola_por_segmento.setdefault(seg, []).append((b, "en_camino"))

        for segmento, cola in cola_por_segmento.items():
            c = self._atraques_compatibles(segmento)
            t_lib = self._tiempo_liberacion_segmento(segmento)

            for pos_idx, (buque, estado) in enumerate(cola):
                pos = pos_idx + 1  # posición 1-indexed

                # Tiempo de espera por cola: aproximación fluida/continua.
                # El primer atraque se libera en t_lib; a partir de ahí,
                # los siguientes atraques compatibles se van liberando de
                # forma continua a un ritmo medio de μ(k)/c cada uno (en
                # vez de asumir que los 'c' atraques se liberan todos a la
                # vez, lo que infraestimaría la espera de las posiciones
                # 2..c).
                mu_buque = buque.tiempo_servicio_h
                t_cola = t_lib + (pos - 1) * (mu_buque / c)

                t_total = t_cola + TIEMPO_MANIOBRA_H

                resultados.append(EstimacionEspera(
                    mmsi=buque.mmsi,
                    eslora=buque.eslora,
                    tipo=buque.tipo,
                    segmento=segmento,
                    estado=estado,
                    posicion_cola=pos,
                    atraques_compatibles=c,
                    tiempo_servicio_estimado_h=round(buque.tiempo_servicio_h, 1),
                    tiempo_espera_estimado_h=round(t_total, 1),
                    componentes={
                        "t_liberacion_h": round(t_lib, 1),
                        "t_cola_h": round(t_cola, 1),
                        "t_maniobra_h": TIEMPO_MANIOBRA_H,
                        "factor_eslora": buque.factor_eslora,
                        "mu_base_h": TIEMPO_SERVICIO_HORAS.get(
                            buque.tipo_enum, 36.0
                        ),
                    },
                    es_objetivo=buque.es_objetivo,
                ))

        # Ordenar por tiempo de espera estimado descendente
        resultados.sort(key=lambda r: r.tiempo_espera_estimado_h, reverse=True)
        return resultados


# ──────────────────────────────────────────────────────────────────────
#  PARSING DEL CONTRATO JSON
# ──────────────────────────────────────────────────────────────────────

def _valor_tipo_raw(item: dict):
    return (
        item.get("tipo_buque")
        or item.get("tipo")
        or item.get("ship_type")
        or item.get("type")
    )


def _es_codigo_numerico(valor) -> bool:
    return isinstance(valor, (int, float)) or (
        isinstance(valor, str) and valor.strip().isdigit()
    )


def _tipo_directo(item: dict) -> Optional[str]:
    """
    Tipo de buque ya resuelto como texto (p.ej. "Bulk carrier"), si lo
    trae — compatibilidad con contratos/tests antiguos. Un código AIS
    numérico (p.ej. "tipo_buque": 70) NO cuenta como tipo "directo":
    es una categoría basta (ver _tipo_desde_codigo_ais) que sólo debe
    usarse si no hay IMO con el que resolver el tipo real contra
    thetis_mrv — por eso no debe saltarse la resolución por IMO.
    """
    valor = _valor_tipo_raw(item)
    if valor is None or _es_codigo_numerico(valor):
        return None
    return valor


def _tipo_codigo_ais_item(item: dict) -> Optional[int]:
    """Código AIS numérico de tipo de buque del item, si lo trae (último fallback)."""
    valor = _valor_tipo_raw(item)
    if valor is None or not _es_codigo_numerico(valor):
        return None
    return int(valor)


def _extraer_estados(data: dict) -> dict:
    """Sub-dict "estados", tanto si viene anidado como en la raíz del contrato."""
    return data.get("estados", data)


def _listas_buques_raw(estados: dict) -> tuple[list, list, list]:
    """Devuelve (atracados_raw, fondeados_raw, en_camino_raw) del sub-dict "estados"."""
    def _get_lista(*claves) -> list:
        for clave in claves:
            if clave in estados:
                return estados[clave]
        return []

    atracados_raw = _get_lista("num_buques_atracados", "n_atracados", "atracados")
    fondeados_raw = _get_lista("num_buques_fondeados", "n_fondeados", "fondeados")
    en_camino_raw = _get_lista("num_buques_en_camino", "n_en_camino", "en_camino")
    return atracados_raw, fondeados_raw, en_camino_raw


def parse_contrato(data: dict | str) -> tuple[Puerto, list[Buque], list[Buque], list[Buque]]:
    """
    Parsea el contrato en el formato que entrega el webhook.

    Formato esperado (webhook)
    ---------------------------
    {
        "puerto": 12345,
        "estados": {
            "num_buques_atracados": [
                {"mmsi": "...", "imo": 9104421, "eslora": 290},
                ...
            ],
            "num_buques_fondeados": [...],
            "num_buques_en_camino": [...]
        }
    }

    "puerto" puede ser un id numérico o un nombre; se guarda como string.
    Las listas de buques pueden venir en la raíz del contrato o anidadas
    bajo "estados" (se acepta cualquiera de las dos formas).

    Resolución del tipo de buque, por prioridad:
    1. Texto explícito ya resuelto ("tipo_buque": "Bulk carrier") —
       compatibilidad con contratos/tests antiguos, no consulta BBDD.
    2. IMO -> ship_type real de thetis_mrv (Postgres), en una sola
       query batch para todos los buques del contrato que lo necesiten.
    3. Código AIS numérico ("tipo_buque": 70, ITU-R M.1371) — fallback
       cuando no hay IMO (típicamente los buques de la cola del puerto
       en paquete_2) o el IMO no está en thetis_mrv. Mucho más basto
       que el texto/IMO: no distingue bulk/container/general_cargo.
    4. "other" si no hay nada de lo anterior.

    También acepta variantes de claves, tanto para las listas de buques:
    - "num_buques_atracados" / "n_atracados" / "atracados"
    - "num_buques_fondeados" / "n_fondeados" / "fondeados"
    - "num_buques_en_camino" / "n_en_camino" / "en_camino"
    como para los campos de cada buque:
    - "tipo_buque", "tipo", "ship_type", "type" (texto o código AIS)
    - "imo"
    - "eslora", "loa", "length"
    """
    if isinstance(data, str):
        data = json.loads(data)

    puerto = Puerto(nombre=str(data.get("puerto", "unknown")))

    # Las listas de buques pueden venir anidadas bajo "estados" (formato
    # webhook) o directamente en la raíz del contrato (formato legacy).
    estados = _extraer_estados(data)
    atracados_raw, fondeados_raw, en_camino_raw = _listas_buques_raw(estados)

    # Resolver en una sola query los IMOs de los buques que no traen
    # tipo explícito.
    todos_los_items = [*atracados_raw, *fondeados_raw, *en_camino_raw]
    imos_a_resolver = [
        item.get("imo")
        for item in todos_los_items
        if item.get("imo") is not None and not _tipo_directo(item)
    ]
    tipos_por_imo = (
        db_conn.get_ship_types(imos_a_resolver) if imos_a_resolver else {}
    )

    def _parse_buques(lista) -> list[Buque]:
        buques = []
        for item in (lista or []):
            mmsi = str(item.get("mmsi", ""))
            imo = item.get("imo")
            eslora = float(
                item.get("eslora")
                or item.get("loa")
                or item.get("length")
                or 150
            )
            codigo_ais = _tipo_codigo_ais_item(item)
            tipo = (
                _tipo_directo(item)
                or (tipos_por_imo.get(str(imo)) if imo is not None else None)
                or (str(codigo_ais) if codigo_ais is not None else None)
                or "other"
            )
            buques.append(Buque(
                mmsi=mmsi,
                imo=str(imo) if imo is not None else None,
                eslora=eslora,
                tipo=str(tipo),
                es_objetivo=bool(item.get("_es_objetivo", False)),
            ))
        return buques

    atracados = _parse_buques(atracados_raw)
    fondeados = _parse_buques(fondeados_raw)
    en_camino = _parse_buques(en_camino_raw)

    return puerto, atracados, fondeados, en_camino


def estimar_desde_contrato(
    contrato: dict | str,
    atraques_por_segmento: Optional[dict[str, int]] = None,
) -> list[dict]:
    """
    Función principal: recibe un contrato JSON y devuelve la lista
    de estimaciones de tiempo de espera.

    Parameters
    ----------
    contrato : dict | str
        Contrato en el formato especificado (dict o JSON string).
    atraques_por_segmento : dict, optional
        Nº total de atraques por segmento. Si no se pasa, se infiere.

    Returns
    -------
    list[dict]
        Lista de estimaciones con todos los campos.
    """
    puerto, atracados, fondeados, en_camino = parse_contrato(contrato)

    if atraques_por_segmento:
        puerto.atraques_por_segmento = atraques_por_segmento

    estimador = EstimadorTiempoEspera(puerto, atracados, fondeados, en_camino)
    resultados = estimador.estimar()

    return [
        {
            "mmsi": r.mmsi,
            "eslora": r.eslora,
            "tipo": r.tipo,
            "segmento_atraque": r.segmento,
            "estado": r.estado,
            "posicion_cola": r.posicion_cola,
            "atraques_compatibles": r.atraques_compatibles,
            "tiempo_servicio_estimado_h": r.tiempo_servicio_estimado_h,
            "tiempo_espera_estimado_h": r.tiempo_espera_estimado_h,
            "componentes": r.componentes,
            "es_objetivo": r.es_objetivo,
        }
        for r in resultados
    ]


# ──────────────────────────────────────────────────────────────────────
#  ETA DEL BUQUE OBJETIVO (mensaje individual del webhook/Kafka)
# ──────────────────────────────────────────────────────────────────────
#
# math_oracle recibe dos paquetes independientes del webhook:
#   - "paquete 1": mensaje individual del buque que dispara el proceso
#     (mmsi, imo, estado, posición, velocidad, dimensiones...).
#   - "paquete 2": contrato agregado del puerto (atracados/fondeados/
#     en_camino) que consume parse_contrato/estimar_desde_contrato.
#
# El objetivo real de jit_calculus es dar el tiempo de espera del buque
# del paquete 1 — pero ese buque no tiene por qué estar ya en el
# paquete 2 (llegan por canales/tiempos distintos). fusionar_buque_objetivo
# lo inyecta en la lista que corresponda a su "estado" (o lo marca in
# situ si ya estaba, para no duplicarlo en la cola) con "_es_objetivo":
# True, de forma que después se pueda recuperar sin ambigüedad de entre
# los resultados — en vez de asumir una posición fija como "el último de
# en_camino".

ESTADO_A_CLAVE_CANONICA: dict[str, str] = {
    "atracado": "num_buques_atracados",
    "fondeado": "num_buques_fondeados",
    "en_camino": "num_buques_en_camino",
}


# Estado AIS "Navigational Status" (ITU-R M.1371) del campo "estado" de
# paquete_1 — código numérico, no texto. Sólo se listan los códigos
# relevantes para el modelo de cola (atracado/fondeado/en_camino); el
# resto (not under command, aground, fishing...) cae al fallback
# "en_camino" por defecto, igual que cualquier código no reconocido.
AIS_ESTADO_A_CLAVE: dict[int, str] = {
    0: "en_camino",  # under way using engine
    1: "fondeado",   # at anchor
    5: "atracado",   # moored
    8: "en_camino",  # under way sailing
}


def _normalizar_estado_buque(estado_raw) -> str:
    """
    Normaliza el campo "estado" del mensaje individual (paquete 1) a
    una de las tres listas del contrato agregado del puerto. Acepta
    tanto el código AIS numérico real (0=en camino, 1=fondeado,
    5=atracado...) como texto (compatibilidad con contratos/tests
    antiguos). Por defecto (valor ausente o no reconocido) asume
    "en_camino", el caso de uso principal de jit_calculus: recomendar
    velocidad JIT a un buque que todavía navega hacia el puerto.
    """
    if estado_raw is None:
        return "en_camino"

    if isinstance(estado_raw, bool):
        # bool es subclase de int en Python; no es un código AIS válido.
        return "en_camino"

    if isinstance(estado_raw, (int, float)) or (
        isinstance(estado_raw, str) and estado_raw.strip().isdigit()
    ):
        return AIS_ESTADO_A_CLAVE.get(int(estado_raw), "en_camino")

    raw = str(estado_raw).strip().lower().replace(" ", "_")
    alias = {
        "atracado": "atracado",
        "atracados": "atracado",
        "berthed": "atracado",
        "moored": "atracado",
        "alongside": "atracado",
        "fondeado": "fondeado",
        "fondeados": "fondeado",
        "anchored": "fondeado",
        "at_anchor": "fondeado",
        "en_camino": "en_camino",
        "en_ruta": "en_camino",
        "underway": "en_camino",
        "under_way_using_engine": "en_camino",
        "navegando": "en_camino",
        "sailing": "en_camino",
    }
    return alias.get(raw, "en_camino")


def fusionar_buque_objetivo(contrato_puerto: dict | str, mensaje_buque: dict) -> dict:
    """
    Inyecta el buque objetivo (paquete 1) dentro del contrato agregado
    del puerto (paquete 2), en la lista que corresponda a su "estado",
    y lo marca con "_es_objetivo": True para poder recuperarlo después
    sin ambigüedad.

    Si el buque ya estaba presente en alguna de las tres listas
    (mismo mmsi), se marca in situ en vez de duplicarlo en la cola.

    No muta `contrato_puerto` ni `mensaje_buque`: devuelve un contrato
    nuevo, con las listas normalizadas a las claves canónicas
    num_buques_atracados/num_buques_fondeados/num_buques_en_camino.
    """
    if isinstance(contrato_puerto, str):
        contrato_puerto = json.loads(contrato_puerto)

    mmsi_objetivo = str(mensaje_buque.get("mmsi", ""))
    if not mmsi_objetivo:
        raise ValueError("mensaje_buque necesita 'mmsi' para poder fusionarse")

    estados = _extraer_estados(contrato_puerto)
    atracados_raw, fondeados_raw, en_camino_raw = _listas_buques_raw(estados)
    listas = {
        "num_buques_atracados": [dict(item) for item in atracados_raw],
        "num_buques_fondeados": [dict(item) for item in fondeados_raw],
        "num_buques_en_camino": [dict(item) for item in en_camino_raw],
    }

    # ¿Ya estaba en alguna lista? Se marca ahí, no se duplica.
    for lista in listas.values():
        for item in lista:
            if str(item.get("mmsi", "")) == mmsi_objetivo:
                item["_es_objetivo"] = True
                item.setdefault("imo", mensaje_buque.get("imo"))
                item.setdefault("eslora", mensaje_buque.get("eslora"))
                return {"puerto": contrato_puerto.get("puerto", "unknown"), "estados": listas}

    # No estaba: se añade a la lista de su estado actual.
    clave_destino = ESTADO_A_CLAVE_CANONICA[
        _normalizar_estado_buque(mensaje_buque.get("estado"))
    ]
    item_objetivo = {
        "mmsi": mensaje_buque.get("mmsi"),
        "imo": mensaje_buque.get("imo"),
        "eslora": mensaje_buque.get("eslora"),
        "_es_objetivo": True,
    }
    tipo_raw = _valor_tipo_raw(mensaje_buque)
    if tipo_raw is not None:
        # Se copia tal cual (texto o código AIS numérico): la cadena de
        # prioridad texto > IMO/thetis_mrv > código AIS de parse_contrato
        # decide qué hacer con ello al parsear el contrato fusionado.
        item_objetivo["tipo_buque"] = tipo_raw
    listas[clave_destino].append(item_objetivo)

    return {"puerto": contrato_puerto.get("puerto", "unknown"), "estados": listas}


def eta_buque_objetivo(
    contrato_puerto: dict | str,
    mensaje_buque: dict,
    atraques_por_segmento: Optional[dict[str, int]] = None,
) -> Optional[dict]:
    """
    Calcula la estimación de espera del buque objetivo (paquete 1),
    fusionándolo primero en el contrato agregado del puerto (paquete 2)
    vía `fusionar_buque_objetivo` y recuperando su resultado por la
    marca "_es_objetivo" — no por posición ni por asumir que ya estaba
    en el contrato.

    Caso especial: si el "estado" del buque objetivo normaliza a
    "atracado", ya está en el muelle y no compite por la cola —
    estimar_desde_contrato no lo incluiría en sus resultados (los
    atracados no forman parte de la cola), así que se devuelve
    directamente una estimación con espera 0.

    Parameters
    ----------
    contrato_puerto : dict | str
        Contrato agregado del puerto (formato webhook de "estados").
    mensaje_buque : dict
        Mensaje individual del buque objetivo (con al menos "mmsi";
        idealmente también "imo", "eslora" y "estado").
    atraques_por_segmento : dict, optional
        Nº total de atraques por segmento, si se conoce.

    Returns
    -------
    dict | None
        Estimación (mismo formato que `estimar_desde_contrato`) del
        buque objetivo, o None si no se pudo localizar tras fusionarlo.
    """
    if _normalizar_estado_buque(mensaje_buque.get("estado")) == "atracado":
        return {
            "mmsi": str(mensaje_buque.get("mmsi", "")),
            "eslora": mensaje_buque.get("eslora"),
            "tipo": _tipo_directo(mensaje_buque),
            "segmento_atraque": None,
            "estado": "atracado",
            "posicion_cola": 0,
            "atraques_compatibles": None,
            "tiempo_servicio_estimado_h": None,
            "tiempo_espera_estimado_h": 0.0,
            "componentes": {"nota": "buque ya atracado, sin espera de cola"},
            "es_objetivo": True,
        }

    contrato_fusionado = fusionar_buque_objetivo(contrato_puerto, mensaje_buque)
    resultados = estimar_desde_contrato(contrato_fusionado, atraques_por_segmento)

    for r in resultados:
        if r.get("es_objetivo"):
            return r
    return None


def construir_respuesta_eta(
    mensaje_buque: dict,
    contrato_puerto: dict | str,
    atraques_por_segmento: Optional[dict[str, int]] = None,
) -> dict:
    """
    Completa el mensaje individual del buque (paquete 1, formato
    Kafka/webhook) con el tiempo de espera estimado, fusionándolo con
    el contrato agregado del puerto (paquete 2) vía `eta_buque_objetivo`
    (fusión + marca "_es_objetivo", ver comentario de cabecera de esta
    sección).

    El resto de campos del mensaje (mmsi, puerto, estado, longitud,
    latitud, direccion, velocidad_buque, eslora, manga,
    calado_de_diseno, imo...) se devuelven sin modificar; sólo se
    añade/sobrescribe "tiempo_espera_estimado_h" con la espera estimada
    en horas hasta disponer de atraque (0 si el buque ya está atracado).

    NOTA: se rellena como una duración en horas, no como una marca
    temporal absoluta. Si el contrato con Flink/Kafka espera un
    timestamp (p.ej. ISO 8601) para el campo "ETA", hay que sumarle la
    hora actual antes de emitir el mensaje.

    Si el buque objetivo no se puede localizar tras fusionarlo (caso
    anómalo: contrato del puerto vacío/corrupto), el campo se devuelve
    como None.
    """
    estimacion = eta_buque_objetivo(
        contrato_puerto, mensaje_buque, atraques_por_segmento
    )

    respuesta = dict(mensaje_buque)
    respuesta["tiempo_espera_estimado_h"] = (
        estimacion["tiempo_espera_estimado_h"] if estimacion else None
    )
    return respuesta


# ──────────────────────────────────────────────────────────────────────
#  EJEMPLO DE USO
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # El contrato ya no trae tipo_buque: sólo mmsi/imo/eslora. El ship_type
    # se resuelve en una sola query batch contra thetis_mrv (parse_contrato
    # -> db_conn.get_ship_types). Los IMOs de abajo son reales (existen en
    # thetis_mrv), uno por cada categoría de ship_type distinta, para
    # ejercitar la resolución completa:
    #   9210919 Combination carrier   | 9010929 Oil tanker
    #   8714205 Container ship        | 1013664 Bulk carrier
    #   8917883 Container/ro-ro cargo | 8415794 Vehicle carrier
    #   1045045 General cargo ship    | 9085613 LNG carrier
    #   6602898 Passenger ship        | 8125454 Chemical tanker
    #   7043843 Ro-ro ship            | 7822457 Passenger ship (Cruise)
    #   9145413 Other ship types (Offshore)
    contrato_ejemplo = {
        "puerto": 12345,
        "estados": {
            "num_buques_atracados": [
                {"mmsi": "477000001", "imo": 9210919, "eslora": 290},
                {"mmsi": "477000002", "imo": 9010929, "eslora": 335},
                {"mmsi": "477000003", "imo": 8714205, "eslora": 210},
                {"mmsi": "477000004", "imo": 1013664, "eslora": 180},
                {"mmsi": "477000005", "imo": 8917883, "eslora": 175},
                {"mmsi": "477000006", "imo": 8415794, "eslora": 260},
            ],
            "num_buques_fondeados": [
                {"mmsi": "477000010", "imo": 1045045, "eslora": 225},
                {"mmsi": "477000011", "imo": 9085613, "eslora": 300},
                {"mmsi": "477000012", "imo": 6602898, "eslora": 190},
                {"mmsi": "477000013", "imo": 8125454, "eslora": 280},
            ],
            "num_buques_en_camino": [
                {"mmsi": "477000020", "imo": 7043843, "eslora": 350},
                {"mmsi": "477000021", "imo": 7822457, "eslora": 200},
                {"mmsi": "477000022", "imo": 9145413, "eslora": 150},
            ],
        },
    }

    print("=" * 72)
    print("  ESTIMADOR DE TIEMPOS DE ESPERA PORTUARIA")
    print("  Basado en Ma et al. (2023), Wijaya & Nakamura (2024)")
    print("=" * 72)

    resultados = estimar_desde_contrato(contrato_ejemplo)

    estados_ejemplo = contrato_ejemplo["estados"]
    print(f"\n  Puerto: {contrato_ejemplo['puerto']}")
    print(f"  Atracados: {len(estados_ejemplo['num_buques_atracados'])}")
    print(f"  Fondeados: {len(estados_ejemplo['num_buques_fondeados'])}")
    print(f"  En camino: {len(estados_ejemplo['num_buques_en_camino'])}")
    print("-" * 72)

    print(f"\n  {'MMSI':<14} {'Estado':<11} {'Tipo':<12} {'Eslora':>6} "
          f"{'Seg.':>7} {'Pos':>4} {'μ(h)':>6} {'T_esp(h)':>9}")
    print("  " + "-" * 68)

    for r in resultados:
        print(
            f"  {r['mmsi']:<14} {r['estado']:<11} {r['tipo']:<12} "
            f"{r['eslora']:>5.0f}m {r['segmento_atraque']:>7} "
            f"{r['posicion_cola']:>4} {r['tiempo_servicio_estimado_h']:>6.1f} "
            f"{r['tiempo_espera_estimado_h']:>9.1f}"
        )

    print("\n" + "-" * 72)
    print("  Desglose del buque con mayor espera estimada:")
    top = resultados[0]
    c = top["componentes"]
    print(f"    MMSI:                   {top['mmsi']}")
    print(f"    Tipo:                   {top['tipo']} (μ_base = {c['mu_base_h']}h)")
    print(f"    Eslora:                 {top['eslora']}m (factor = {c['factor_eslora']})")
    print(f"    μ ajustado:             {top['tiempo_servicio_estimado_h']}h")
    print(f"    T_liberación:           {c['t_liberacion_h']}h")
    print(f"    T_cola:                 {c['t_cola_h']}h")
    print(f"    T_maniobra:             {c['t_maniobra_h']}h")
    print(f"    >>> T_espera total:     {top['tiempo_espera_estimado_h']}h")
    print("=" * 72)

    # --- Buque objetivo (paquete 1): no está en contrato_ejemplo, lo
    # fusiona fusionar_buque_objetivo() dentro de "en_camino" al no
    # traer "estado" explícito (mismo IMO que el ejemplo de cii_calculus).
    print("\n  Buque objetivo (paquete 1, fusionado con el paquete 2):")
    mensaje_buque_ejemplo = {
        "mmsi": "123456789",
        "imo": 9104421,
        "puerto": 12345,
        "estado": "en_camino",
        "eslora": 190.0,
        "velocidad_buque": 11.5,
    }
    respuesta = construir_respuesta_eta(mensaje_buque_ejemplo, contrato_ejemplo)
    print(f"    {respuesta}")
    print("=" * 72)