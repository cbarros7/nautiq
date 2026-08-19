"""
Módulo para estimar el CII (Carbon Intensity Indicator) operacional de un buque
a partir de datos del webhook (Kafka/Flink), registros de la BBDD (PostgreSQL,
tabla thetis_mrv) y la distancia navegable calculada por sea_route.
Se usará tanto con la velocidad inicial como con la velocidad JIT, con el objetivo de
comparar el consumo con una velocidad y otra.

La distancia restante al puerto (distancia_nm) no se calcula en este módulo:
la resuelve el grafo `math_oracle` (nodo fetch_route -> sea_route.route_to_port)
y se pasa como parámetro a estimar_cii, ya que es math_oracle quien orquesta
esta llamada.

Dos rutas de cálculo:
  1. EEXI disponible → CII ≈ EEXI × (V_actual / V_diseño)²  (sólo usa Froude como estimación)
  2. Fallback sin EEXI → estima DWT desde dimensiones del casco,
     calcula fuel con coeficiente de Almirantazgo y obtiene CII = CO₂ / (DWT × D).
 """
 

from __future__ import annotations
 
import math
from dataclasses import dataclass, field
from typing import Optional

try:
    from . import db_conn  # ejecución como paquete: -m app.agents.tools.cii_calculus
except ImportError:
    import db_conn  # ejecución como script suelto: python cii_calculus.py

# Constantes físicas y de emisión
G = 9.81  # m/s²
RHO_SW = 1.025  # densidad agua de mar (t/m³)
KN_TO_MS = 0.5144  # 1 nudo = 0.5144 m/s
SFC_HFO = 190.0  # consumo específico HFO (g/kWh) – valor conservador IMO
CF_HFO = 3.114  # factor de emisión CO₂ para HFO (g CO₂ / g fuel)


# ---------------------------------------------------------------------------
# Tablas por tipo de buque
# ---------------------------------------------------------------------------
# Froude típico de diseño (media del rango habitual)
# Watson, D.G.M. — Practical Ship Design (Elsevier) → tiene tablas de Cb, Froude, y ratios de peso por tipo en los capítulos de diseño preliminar
# Molland, Turnock & Hudson — Ship Resistance and Propulsion (Cambridge University Press)
FROUDE_POR_TIPO: dict[str, float] = {
    "bulk_carrier": 0.155,
    "oil_tanker": 0.150,
    "chemical_tanker": 0.150,
    "lng_carrier": 0.180,
    "lpg_carrier": 0.170,
    "container": 0.235,
    "general_cargo": 0.200,
    "refrigerated_cargo": 0.215,
    "ro_ro": 0.220,
    "cruise": 0.270,
    "passenger": 0.260,
    "ferry": 0.280,
}
 
# Coeficiente de bloque (Cb) – para estimar desplazamiento
# Watson, D.G.M. — Practical Ship Design (Elsevier)
# Schneekluth & Bertram — Ship Design for Efficiency and Economy (Butterworth-Heinemann)
CB_POR_TIPO: dict[str, float] = {
    "bulk_carrier": 0.82,
    "oil_tanker": 0.83,
    "chemical_tanker": 0.80,
    "lng_carrier": 0.75,
    "lpg_carrier": 0.75,
    "container": 0.62,
    "general_cargo": 0.70,
    "refrigerated_cargo": 0.65,
    "ro_ro": 0.60,
    "cruise": 0.58,
    "passenger": 0.58,
    "ferry": 0.55,
}
 
# Ratio DWT / Desplazamiento
# Watson & Gilfillan (1977) - SOME SHIP DESIGN METHODS
DWT_RATIO_POR_TIPO: dict[str, float] = {
    "bulk_carrier": 0.82,
    "oil_tanker": 0.83,
    "chemical_tanker": 0.80,
    "lng_carrier": 0.55,
    "lpg_carrier": 0.60,
    "container": 0.65,
    "general_cargo": 0.72,
    "refrigerated_cargo": 0.60,
    "ro_ro": 0.45,
    "cruise": 0.25,
    "passenger": 0.30,
    "ferry": 0.35,
}
 
# Coeficiente de Almirantazgo (C_adm) típico
# Harvald, S.A. — Resistance and Propulsion of Ships (Wiley)
C_ADM_POR_TIPO: dict[str, float] = {
    "bulk_carrier": 600.0,
    "oil_tanker": 550.0,
    "chemical_tanker": 500.0,
    "lng_carrier": 500.0,
    "lpg_carrier": 500.0,
    "container": 450.0,
    "general_cargo": 500.0,
    "refrigerated_cargo": 450.0,
    "ro_ro": 400.0,
    "cruise": 350.0,
    "passenger": 350.0,
    "ferry": 350.0,
}
 
# Mapa de nombres que pueden llegar del webhook / BBDD → clave normalizada
_ALIAS_TIPO: dict[str, str] = {
    "bulk carrier": "bulk_carrier",
    "bulker": "bulk_carrier",
    "oil tanker": "oil_tanker",
    "crude oil tanker": "oil_tanker",
    "chemical tanker": "chemical_tanker",
    "chemical/oil products tanker": "chemical_tanker",
    "lng carrier": "lng_carrier",
    "lng tanker": "lng_carrier",
    "lpg carrier": "lpg_carrier",
    "lpg tanker": "lpg_carrier",
    "container ship": "container",
    "container": "container",
    "containership": "container",
    "general cargo": "general_cargo",
    "general cargo ship": "general_cargo",
    "cargo": "general_cargo",
    "refrigerated cargo carrier": "refrigerated_cargo",
    "refrigerated cargo": "refrigerated_cargo",
    "reefer": "refrigerated_cargo",
    "ro-ro": "ro_ro",
    "ro-ro cargo ship": "ro_ro",
    "vehicles carrier": "ro_ro",
    "cruise": "cruise",
    "cruise ship": "cruise",
    "passenger ship": "passenger",
    "passenger": "passenger",
    "ferry": "ferry",
}

def _normalizar_tipo(raw: str) -> str:
    """Normaliza el tipo de buque a una clave interna."""
    key = raw.strip().lower()
    if key in _ALIAS_TIPO:
        return _ALIAS_TIPO[key]
    # Búsqueda parcial
    for alias, norm in _ALIAS_TIPO.items():
        if alias in key or key in alias:
            return norm
    # logger.warning("Tipo de buque '%s' no reconocido, usando general_cargo", raw)
    return "general_cargo"


@dataclass
class CIIResult:
    """Resultado del cálculo/estimación de CII."""
 
    cii: float  # gCO₂ / (t · nm)
    metodo: str  # "eexi" | "fallback_admiralty"
    v_diseno_kn: float  # velocidad de diseño estimada (nudos)
    v_actual_kn: float  # velocidad actual (nudos)
    distancia_nm: float  # distancia restante al puerto
    dwt_estimado: Optional[float] = None  # solo en fallback
    co2_estimado_kg: Optional[float] = None  # solo en fallback
    detalles: dict = field(default_factory=dict)
    
# ---------------------------------------------------------------------------
# Funciones de estimación
# ---------------------------------------------------------------------------
    
def estimar_v_diseno(eslora_m: float, tipo_buque: str) -> float:
    """
    Estima la velocidad de diseño (nudos) a partir de la eslora
    y el número de Froude típico del tipo de buque.
 
    V = Fr × √(g × Lwl),  Lwl ≈ 0.97 × LOA
    """
    tipo = _normalizar_tipo(tipo_buque)
    fr = FROUDE_POR_TIPO.get(tipo, 0.18)
    lwl = 0.97 * eslora_m
    v_ms = fr * math.sqrt(G * lwl)
    v_kn = v_ms / KN_TO_MS
    return round(v_kn, 2)

def estimar_dwt(eslora_m: float, manga_m: float, calado_m: float,
                tipo_buque: str) -> float:
    """
    Estima el DWT a partir de las dimensiones del casco.
 
    Desplazamiento = Cb × L × B × T × ρ
    DWT = Desplazamiento × ratio_carga
    """
    tipo = _normalizar_tipo(tipo_buque)
    cb = CB_POR_TIPO.get(tipo, 0.70)
    ratio = DWT_RATIO_POR_TIPO.get(tipo, 0.65)
 
    desplazamiento_t = cb * eslora_m * manga_m * calado_m * RHO_SW
    dwt = desplazamiento_t * ratio
    return round(dwt, 1)

# ---------------------------------------------------------------------------
# Cálculo CII — ruta principal (EEXI)
# ---------------------------------------------------------------------------
 
def _cii_via_eexi(eexi: float, v_actual_kn: float,
                  v_diseno_kn: float) -> float:
    """
    CII ≈ EEXI × (V_actual / V_diseño)²
 
    La potencia propulsiva escala con V³; para una distancia dada el fuel
    escala con V². Al normalizar por DWT×D, la dependencia queda en V².
    """
    if v_diseno_kn <= 0:
        raise ValueError("Velocidad de diseño debe ser > 0")
    ratio = v_actual_kn / v_diseno_kn
    return round(eexi * (ratio ** 2), 4)



 
# ---------------------------------------------------------------------------
# Cálculo CII — fallback (Almirantazgo)
# ---------------------------------------------------------------------------
 
def _cii_via_admiralty(eslora_m: float, manga_m: float, calado_m: float,
                       tipo_buque: str, v_actual_kn: float,
                       distancia_nm: float) -> tuple[float, float, float]:
    """
    Ruta fallback cuando no hay EEXI.
 
    1. Estima DWT desde dimensiones.
    2. Calcula potencia con coeficiente de Almirantazgo:
       P = Δ^(2/3) × V³ / C_adm
    3. Fuel = P × SFC × tiempo
    4. CO₂ = Fuel × CF
    5. CII = CO₂ / (DWT × D)
 
    Devuelve (cii, dwt, co2_kg).
    """
    tipo = _normalizar_tipo(tipo_buque)
    dwt = estimar_dwt(eslora_m, manga_m, calado_m, tipo_buque)
 
    cb = CB_POR_TIPO.get(tipo, 0.70)
    desplazamiento_t = cb * eslora_m * manga_m * calado_m * RHO_SW
    c_adm = C_ADM_POR_TIPO.get(tipo, 450.0)
 
    v_ms = v_actual_kn * KN_TO_MS
    # Potencia en kW
    potencia_kw = (desplazamiento_t ** (2 / 3)) * (v_ms ** 3) / c_adm
 
    # Tiempo de travesía restante (horas)
    if v_actual_kn <= 0:
        return 0.0, dwt, 0.0
    tiempo_h = distancia_nm / v_actual_kn
 
    # Fuel total (g) → kg
    fuel_g = potencia_kw * SFC_HFO * tiempo_h
    fuel_kg = fuel_g / 1000.0
 
    # CO₂ (kg)
    co2_kg = fuel_kg * CF_HFO
 
    # CII (gCO₂ / (t · nm))
    if dwt <= 0 or distancia_nm <= 0:
        return 0.0, dwt, co2_kg
    co2_g = co2_kg * 1000.0
    cii = co2_g / (dwt * distancia_nm)
 
    return round(cii, 4), round(dwt, 1), round(co2_kg, 1)
 
 
# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------
 
def estimar_cii(webhook: dict,
                distancia_nm: float,
                db_record: Optional[dict] = None) -> CIIResult:
    """
    Estima el CII operacional del buque.

    Parámetros
    ----------
    webhook : dict
        Datos del mensaje Kafka/Flink. Campos esperados:
        - velocidad_buque (float, nudos)
        - eslora (float, metros)
        - manga (float, metros)
        - calado_de_diseño (float, metros)
        - imo — usado para recuperar ship_type/eexi/dwt de Postgres si
          no se pasa db_record explícitamente. El webhook ya no trae
          el tipo de buque directamente.
    distancia_nm : float
        Distancia restante al puerto en millas náuticas. Ya no se
        calcula aquí a partir de ETA/velocidad: la resuelve el grafo
        `math_oracle` (nodo fetch_route -> sea_route.route_to_port ->
        Route.distance_nm) y se pasa directamente a esta función, ya
        que el propio math_oracle es quien orquesta la llamada a
        cii_calculus.
    db_record : dict | None
        Registro de PostgreSQL (tabla thetis_mrv). Si no se pasa, se
        recupera automáticamente a partir de webhook["imo"] mediante
        db_conn.get_thetis_mrv_record(). Campos útiles:
        - eexi (Decimal | float | None)
        - dwt (float | None)
        - ship_type (str)

    Devuelve
    --------
    CIIResult con el CII estimado y metadatos del cálculo.
    """
    if distancia_nm <= 0:
        raise ValueError("Se necesita distancia_nm > 0 para el cálculo")

    # --- Resolver ship_type/eexi/dwt desde Postgres si no vienen ya ---
    if db_record is None:
        imo = webhook.get("imo")
        if imo is not None:
            db_record = db_conn.get_thetis_mrv_record(imo)

    # --- Extraer y limpiar inputs ---
    v_actual = float(webhook.get("velocidad_buque", 0))
    eslora = float(webhook.get("eslora", 0))
    manga = float(webhook.get("manga", 0))
    calado = float(webhook.get("calado_de_diseño", 0))
    tipo_raw = ((db_record or {}).get("ship_type")
                or webhook.get("tipo_buque")
                or "general_cargo")

    # --- Velocidad de diseño ---
    if eslora <= 0:
        raise ValueError("Se necesita eslora > 0 para estimar V de diseño")
    v_diseno = estimar_v_diseno(eslora, tipo_raw)
 
    # --- Intentar ruta EEXI ---
    eexi = None
    if db_record:
        raw_eexi = db_record.get("eexi")
        if raw_eexi is not None:
            eexi = float(raw_eexi)
 
    if eexi and eexi > 0 and v_actual > 0:
        cii = _cii_via_eexi(eexi, v_actual, v_diseno)
        return CIIResult(
            cii=cii,
            metodo="eexi",
            v_diseno_kn=v_diseno,
            v_actual_kn=v_actual,
            distancia_nm=distancia_nm,
            detalles={
                "eexi_base": eexi,
                "ratio_v": round(v_actual / v_diseno, 4),
                "tipo_normalizado": _normalizar_tipo(tipo_raw),
            },
        )
 
    # --- Fallback: Almirantazgo ---
    # logger.info("Sin EEXI → fallback por coeficiente de Almirantazgo")
    if manga <= 0 or calado <= 0:
        raise ValueError("Sin EEXI ni dimensiones completas: cálculo imposible")
 
    cii, dwt, co2_kg = _cii_via_admiralty(
        eslora, manga, calado, tipo_raw, v_actual, distancia_nm
    )
    return CIIResult(
        cii=cii,
        metodo="fallback_admiralty",
        v_diseno_kn=v_diseno,
        v_actual_kn=v_actual,
        distancia_nm=distancia_nm,
        dwt_estimado=dwt,
        co2_estimado_kg=co2_kg,
        detalles={
            "tipo_normalizado": _normalizar_tipo(tipo_raw),
            "nota": "CII estimado sin EEXI — basado en dimensiones y C_adm",
        },
    )
    
    

# ---------------------------------------------------------------------------
# Ejemplo de uso
# ---------------------------------------------------------------------------
 
if __name__ == "__main__":
    # logging.basicConfig(level=logging.INFO)

    # Import local: sólo hace falta para este ejemplo (simula lo que
    # math_oracle.fetch_route ya resuelve en el grafo real).
    try:
        from . import sea_route
    except ImportError:
        import sea_route
    Port, route_to_port = sea_route.Port, sea_route.route_to_port

    # Datos simulados del webhook (ya no trae tipo_buque ni ETA para
    # calcular distancia: sólo imo, dimensiones y velocidad actual)
    ejemplo_webhook = {
        "mmsi": 123456789,
        "imo": 9104421,
        "puerto": "Bilbao",
        "velocidad_buque": 11.5,
        "eslora": 190.0,
        "manga": 32.0,
        "calado_de_diseño": 12.5,
    }

    # En producción esto lo entrega math_oracle vía
    # state["distance_nm"] (nodo fetch_route -> sea_route.route_to_port).
    # Aquí lo calculamos igual, en local, sólo para el ejemplo.
    ruta = route_to_port(
        vessel_lat=41.492474,
        vessel_lon=4.455705,
        port=Port("ESBCN", "Bilbao", 43.263085, -2.935423),
        speed_knot=ejemplo_webhook["velocidad_buque"],
    )

    # Registro de PostgreSQL (normalmente lo resuelve estimar_cii solo,
    # vía db_conn.get_thetis_mrv_record(webhook["imo"]); se pasa aquí
    # explícito para poder ejecutar el ejemplo sin conexión a BBDD)
    ejemplo_db = {
        "imo": 9104421,
        "name": "SEA MERAY",
        "ship_type": "Bulk carrier",
        "dwt": None,
        "eexi": 4.79,  # gCO₂/(t·nm)
    }

    resultado = estimar_cii(ejemplo_webhook, ruta.distance_nm, ejemplo_db)
 
    print(f"\n{'='*50}")
    print(f"  CII estimado:    {resultado.cii} gCO₂/(t·nm)")
    print(f"  Método:          {resultado.metodo}")
    print(f"  V diseño:        {resultado.v_diseno_kn} kn")
    print(f"  V actual:        {resultado.v_actual_kn} kn")
    print(f"  Distancia:       {resultado.distancia_nm} nm")
    print(f"  Detalles:        {resultado.detalles}")
    print(f"{'='*50}\n")