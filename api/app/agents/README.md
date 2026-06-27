# Oráculo matemático — modelo de consumo + CII (documental)

> **Estado: documental (no implementado).** Esta capa pertenece a la API/FastAPI
> (ADR 004): el código determinista se incrustará como herramientas `@tool` de
> LangGraph. Aquí se conserva el **diseño y el código de referencia** del modelo de
> consumo y del early-warning CII; la integración efectiva (entradas desde Flink,
> wiring `@tool`) queda pendiente y se describe en `api/README.md`.
>
> Reemplaza a los antiguos módulos `consumption_curve.py`, `cii.py` y
> `cii_params.json` (consolidados aquí a petición del refactor).

---

## 1. Modelo de curva de consumo (bottom-up, IMO 4th GHG Study)

La curva de consumo **no se descarga** por buque (no existe como dato): se **modela**
bottom-up con la metodología del *IMO Fourth GHG Study (2020)*:

```
P(V)    = P_ref · (V / V_ref)³        (ley del cubo, acotada a la MCR)
Fuel/h  = P(V) · SFOC  + P_aux · SFOC_aux   (incluye idle/auxiliar)
CO₂     = Fuel · Cf
```

**Insumos** (todos gratuitos): DWT/calado/dimensiones → desplazamiento → `P_ref`
(coef. del Almirantazgo); EEXI (THETIS) → ancla de diseño; SFOC y potencia auxiliar
(idle) de tablas IMO 4th GHG; combustible y distancia **anuales** de THETIS +
velocidades AIS → **calibración fina** que corrige el sesgo de la ley del cubo.

**Limitación honesta:** sin noon-reports ni sensores, es una **estimación**
(apoyo a la decisión / early-warning), no medición. La curva base se corrige con
Kwon (penalización meteo) e integra con Euler en el flujo cognitivo.

### Código de referencia (`consumption_curve.py`)

```python
from __future__ import annotations

import math
from dataclasses import dataclass

# --- Tablas de referencia IMO 4th GHG Study (ilustrativas, parametrizables) ----
SFOC_MAIN_G_KWH = 185.0                                   # SFOC motor principal (g/kWh)
SFOC_AUX_G_KWH = 215.0                                    # SFOC auxiliares (g/kWh)
ADMIRALTY_COEFFICIENT = {"container": 480.0, "bulk_carrier": 520.0, "tanker": 500.0}
DESIGN_SPEED_KN = {"container": 22.0, "bulk_carrier": 14.5, "tanker": 15.0}
AUX_POWER_FRACTION = {"container": 0.06, "bulk_carrier": 0.04, "tanker": 0.05}
DWT_TO_DISPLACEMENT = {"container": 0.70, "bulk_carrier": 0.85, "tanker": 0.85}


@dataclass
class ConsumptionCurve:
    """Curva de consumo de un buque (t combustible/h en función de la velocidad)."""

    p_ref_kw: float          # potencia principal de diseño en V_ref
    v_ref_kn: float          # velocidad de diseño
    p_aux_kw: float          # potencia auxiliar media (idle/hotel)
    sfoc_main: float = SFOC_MAIN_G_KWH
    sfoc_aux: float = SFOC_AUX_G_KWH
    calibration_factor: float = 1.0  # ajuste a combustible anual THETIS

    def main_power_kw(self, speed_kn: float) -> float:
        if self.v_ref_kn <= 0:
            return 0.0
        power = self.p_ref_kw * (max(speed_kn, 0.0) / self.v_ref_kn) ** 3
        return min(power, self.p_ref_kw)

    def fuel_rate_tph(self, speed_kn: float) -> float:
        main_t = self.main_power_kw(speed_kn) * self.sfoc_main / 1e6  # g->t
        aux_t = self.p_aux_kw * self.sfoc_aux / 1e6
        return (main_t + aux_t) * self.calibration_factor

    def voyage_fuel_t(self, speed_kn: float, distance_nm: float) -> float:
        if speed_kn <= 0:
            return 0.0
        return self.fuel_rate_tph(speed_kn) * (distance_nm / speed_kn)

    def calibrate_to_annual(self, annual_fuel_t, annual_distance_nm) -> float:
        """Calibra contra combustible/distancia anuales de THETIS (autocorrige el cubo)."""
        if not annual_fuel_t or not annual_distance_nm:
            return self.calibration_factor
        v_service = 0.85 * self.v_ref_kn
        predicted = self.voyage_fuel_t(v_service, annual_distance_nm)
        if predicted > 0:
            self.calibration_factor = annual_fuel_t / predicted
        return self.calibration_factor


def _category(ship_type_text: str | None) -> str:
    t = (ship_type_text or "container").lower()
    return t if t in ADMIRALTY_COEFFICIENT else "container"


def build_curve(*, dwt, gt=None, draught_m=None, eexi=None,
                category=None, design_speed_kn=None) -> "ConsumptionCurve | None":
    """Construye la curva desde maestro + THETIS. None si no hay capacidad (sin CII)."""
    cat = _category(category)
    capacity = dwt or gt
    if not capacity:
        return None
    v_ref = design_speed_kn or DESIGN_SPEED_KN.get(cat, 22.0)
    disp = capacity / DWT_TO_DISPLACEMENT.get(cat, 0.70)
    cadm = ADMIRALTY_COEFFICIENT.get(cat, 480.0)
    p_ref = disp ** (2 / 3) * v_ref**3 / cadm
    p_aux = p_ref * AUX_POWER_FRACTION.get(cat, 0.06)
    return ConsumptionCurve(p_ref_kw=p_ref, v_ref_kn=v_ref, p_aux_kw=p_aux)
```

---

## 2. Early-warning CII (intensidad CO₂)

Contrasta la **intensidad de carbono por trayecto** contra el **CII requerido** del
buque y avisa al superarlo. Es early-warning, **no** cumplimiento legal. Solo CO₂.

```
CIIref       = a · Capacidad^(-c)               (MEPC.337(76))
CIIrequerido = CIIref · (1 − Z/100)             (MEPC.338(76))
CO₂_trayecto = Σ(combustible_j · Cf_j)          (incluye idle/auxiliar)
intensidad   = CO₂_trayecto / (Capacidad · distancia_nm)
AVISO si intensidad > CIIrequerido (o cruza banda D/E)   (MEPC.339(76))
```

> **Capacidad (DWT/GT):** ni AIS ni el fichero público de THETIS-MRV traen DWT/GT
> como dato directo. El DWT se **deriva** en `reference/thetis.py` (solo para los
> buques que reportan trabajo de transporte en base dwt). Sin capacidad no se
> calcula CII (no se inventa). Ver `ingestion/README.md`.

### Código de referencia (`cii.py`)

```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PARAMS_PATH = Path(__file__).resolve().parent / "cii_params.json"


@lru_cache(maxsize=1)
def params() -> dict:
    with open(_PARAMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def category_for_ais_type(ship_type: int | None) -> str:
    return params()["ais_type_to_category"]["default_cargo"]


def required_cii(category: str, capacity: float, year: int) -> tuple[float, str]:
    line = params()["reference_line"][category]
    a, c, basis = line["a"], line["c"], line["capacity_basis"]
    cii_ref = a * capacity ** (-c)
    z_table = params()["reduction_factor_z"]
    z = z_table.get(str(year), z_table["default"])
    return cii_ref * (1 - z / 100.0), basis


def co2_from_fuel(fuel_t: float, fuel_type: str = "HFO") -> float:
    cf = params()["carbon_factors"].get(fuel_type, params()["carbon_factors"]["HFO"])
    return fuel_t * cf


def carbon_intensity(co2_t: float, capacity: float, distance_nm: float) -> float:
    if capacity <= 0 or distance_nm <= 0:
        return 0.0
    return (co2_t * 1e6) / (capacity * distance_nm)   # g CO₂ / (dwt · nm)


def rating_band(category: str, intensity: float, required: float) -> str:
    bands = params().get("rating_bands", {}).get(category)
    if not bands or required <= 0:
        return "?"
    ratio = intensity / required
    d1, d2, d3, d4 = bands
    if ratio <= d1: return "A"
    if ratio <= d2: return "B"
    if ratio <= d3: return "C"
    if ratio <= d4: return "D"
    return "E"


def evaluate_voyage(*, category, capacity, distance_nm, fuel_t, year, fuel_type="HFO") -> dict:
    co2_t = co2_from_fuel(fuel_t, fuel_type)
    intensity = carbon_intensity(co2_t, capacity, distance_nm)
    req, basis = required_cii(category, capacity, year)
    band = rating_band(category, intensity, req)
    return {
        "co2_t": round(co2_t, 2),
        "carbon_intensity": round(intensity, 4),
        "required_cii": round(req, 4),
        "capacity_basis": basis,
        "rating_band": band,
        "cii_warning": intensity > req or band in {"D", "E"},
    }
```

### Parámetros (`cii_params.json`)

Constantes regulatorias parametrizadas (NO hardcodear). Fuentes: MEPC.337(76) (`a`,`c`),
MEPC.338(76) (`Z`), MEPC.339(76) (bandas `d`).

```json
{
  "reference_line": {
    "bulk_carrier":  { "a": 4745,  "c": 0.622, "capacity_basis": "dwt" },
    "tanker":        { "a": 5247,  "c": 0.610, "capacity_basis": "dwt" },
    "container":     { "a": 1984,  "c": 0.489, "capacity_basis": "dwt" },
    "gas_carrier":   { "a": 14405000000, "c": 2.071, "capacity_basis": "dwt" },
    "general_cargo": { "a": 31948, "c": 0.792, "capacity_basis": "dwt" },
    "ro_ro_cargo":   { "a": 5739,  "c": 0.631, "capacity_basis": "gt" },
    "cruise":        { "a": 930,   "c": 0.383, "capacity_basis": "gt" }
  },
  "reduction_factor_z": { "2023": 5, "2024": 7, "2025": 9, "2026": 11, "2027": 13, "default": 11 },
  "rating_bands": {
    "container":     [0.83, 0.94, 1.07, 1.19],
    "bulk_carrier":  [0.86, 0.94, 1.06, 1.18],
    "tanker":        [0.82, 0.93, 1.08, 1.28],
    "general_cargo": [0.83, 0.94, 1.06, 1.19]
  },
  "carbon_factors": { "HFO": 3.114, "MDO": 3.206, "MGO": 3.206, "LNG": 2.750 },
  "ais_type_to_category": { "default_cargo": "container" }
}
```

---

## Integración pendiente (en la API)

1. Cablear `consumption_curve` y `cii` como herramientas `@tool` de LangGraph.
2. Recibir de Flink (vía webhook) la ruta + meteo + capacidad/EEXI del maestro.
3. Calcular el combustible por trayecto (entrada del CII) desde la curva calibrada,
   aplicar Kwon (meteo) + Euler, y emitir la recomendación de *Adaptive Slow Steaming*.
