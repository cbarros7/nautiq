from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from .. import config
from . import db

_REFERENCE_DIR = config.PROJECT_ROOT / "data" / "reference"
_CANDIDATE_PATHS = [_REFERENCE_DIR / "thetis_mrv.xlsx", _REFERENCE_DIR / "thetis_mrv.csv"]
_DOWNLOAD_HELP = (
    "Falta el fichero THETIS-MRV. Descárgalo (una vez) del portal público de EMSA:\n"
    "  https://mrv.emsa.europa.eu/#public/emission-report  ->  Export\n"
    f"y guárdalo como {_REFERENCE_DIR / 'thetis_mrv.xlsx'} (o .csv)."
)


class ThetisNotAvailable(FileNotFoundError):
    """No hay fichero THETIS-MRV en local (descarga manual pendiente)."""


def _resolve_path(path: str | Path | None) -> Path:
    if path:
        p = Path(path)
        if not p.exists():
            raise ThetisNotAvailable(f"{p} no existe.\n{_DOWNLOAD_HELP}")
        return p
    for cand in _CANDIDATE_PATHS:
        if cand.exists():
            return cand
    raise ThetisNotAvailable(_DOWNLOAD_HELP)


def _find_col(columns, *keywords, exclude=()):
    for col in columns:
        low = col.lower()
        if all(k in low for k in keywords) and not any(x in low for x in exclude):
            return col
    return None


def _read_raw(path: Path) -> pd.DataFrame:
    read = pd.read_excel if path.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv
    with warnings.catch_warnings():
        # El Excel de EMSA no incluye estilo por defecto; openpyxl avisa pero carga bien.
        warnings.filterwarnings("ignore", "Workbook contains no default style", UserWarning)
        preview = read(path, header=None, nrows=15, dtype=str)
        header_row = 0
        for i in range(len(preview)):
            if preview.iloc[i].astype(str).str.contains("imo", case=False, na=False).any():
                header_row = i
                break
        return read(path, header=header_row)


def _to_num(series: pd.Series) -> pd.Series:
    """
    Columna del fichero -> numérica.

    Las columnas que ya vienen numéricas se convierten directamente: pasarlas por el
    saneado de texto rompería la notación científica (`1e-05` -> `1-05` -> NaN). El
    saneado solo hace falta en las columnas de texto, donde EMSA mezcla separadores de
    millar y literales como 'Division by zero!' (que deben quedar en NaN).
    """
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return pd.to_numeric(series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                         errors="coerce")


def _first_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.extract(r"([0-9]+\.?[0-9]*)", expand=False),
                         errors="coerce")


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den).where(den > 0)


def load_thetis(path: str | Path | None = None) -> pd.DataFrame:
    """
    Normaliza el fichero THETIS-MRV real a:
    imo, name, ship_type, dwt, gt, eexi, annual_fuel_t, annual_distance_nm, annual_co2_t.
    DWT y distancia se DERIVAN (no son columnas directas del fichero público).
    """
    raw = _read_raw(_resolve_path(path))
    cols = [str(c) for c in raw.columns]

    c_imo = _find_col(cols, "imo")
    if c_imo is None:
        raise ValueError("THETIS-MRV: no se encontró la columna IMO.")
    c_name = _find_col(cols, "name", exclude=("verifier", "company", "accreditation", "port"))
    c_type = _find_col(cols, "ship", "type") or _find_col(cols, "type", exclude=("efficiency",))
    c_eff = _find_col(cols, "technical", "efficiency") or _find_col(cols, "eexi") \
        or _find_col(cols, "eedi")
    c_co2 = _find_col(cols, "total", "co", "emission", exclude=("eq", "ch", "n₂", "derogation"))
    c_fuel = _find_col(cols, "total", "fuel", "consumption")
    c_gt = _find_col(cols, "gross", "tonnage")
    c_dwt_direct = _find_col(cols, "deadweight", exclude=("per", "transport", "work", "carried"))
    c_fuel_per_dist = _find_col(cols, "fuel", "per", "distance",
                                exclude=("laden", "transport", "work", "time"))
    c_fuel_tw_dwt = _find_col(cols, "fuel", "transport", "dwt", exclude=("laden",))
    c_co2_per_dist = _find_col(cols, "co", "emission", "per", "distance",
                               exclude=("laden", "eq", "transport"))
    c_co2_tw_dwt = _find_col(cols, "co", "transport", "dwt", exclude=("laden", "eq"))
    c_dist_direct = _find_col(cols, "distance", "travelled") or _find_col(cols, "distance", "sailed")

    # --- Enriquecimiento: indicadores operacionales ---
    # 'per'/'fuel'/'emission' se excluyen para no capturar 'Fuel consumption per time
    # spent at sea' ni 'CO₂ emissions per time spent at sea', que contienen la frase.
    c_time_sea = _find_col(cols, "time", "spent", "sea",
                           exclude=("ice", "per", "fuel", "emission"))

    # Emisiones en puerto y CO₂eq. Se filtra por el subíndice ('co₂' / 'co₂eq') porque
    # las variantes de CH₄, N₂O y CO₂eq repiten el resto del texto palabra por palabra.
    c_period = _find_col(cols, "reporting", "period")
    c_co2_berth = _find_col(cols, "co₂", "berth", exclude=("eq", "ch₄", "n₂o"))
    c_co2_port = _find_col(cols, "co₂", "within", "ports",
                           exclude=("berth", "eq", "ch₄", "n₂o"))
    c_co2eq = _find_col(cols, "total", "co₂eq", "emission", exclude=("derogation",))

    fpd = _to_num(raw[c_fuel_per_dist]) if c_fuel_per_dist else None
    co2pd = _to_num(raw[c_co2_per_dist]) if c_co2_per_dist else None

    out = pd.DataFrame()
    out["imo"] = _to_num(raw[c_imo])
    out["name"] = raw[c_name].astype(str).str.strip() if c_name else None
    out["ship_type"] = raw[c_type].astype(str).str.strip() if c_type else None
    out["gt"] = _to_num(raw[c_gt]) if c_gt else pd.NA
    out["eexi"] = _first_number(raw[c_eff]) if c_eff else pd.NA
    out["annual_co2_t"] = _to_num(raw[c_co2]) if c_co2 else pd.NA
    out["annual_fuel_t"] = _to_num(raw[c_fuel]) if c_fuel else pd.NA

    # Indicadores operacionales, tal cual vienen del fichero (sin recortar outliers:
    # sanear es interpretación, y eso es de Flink). `_coherence_report` los audita.
    out["technical_efficiency"] = raw[c_eff].astype(str).str.strip() if c_eff else None
    out["time_at_sea_h"] = _to_num(raw[c_time_sea]) if c_time_sea else pd.NA
    out["fuel_per_distance_kg_per_nm"] = fpd if fpd is not None else pd.NA

    # Año del dato (la PK es solo el IMO: sin esto no se sabe de qué ejercicio es la fila).
    out["reporting_period"] = _to_num(raw[c_period]) if c_period else pd.NA
    # Emisiones en puerto: línea base del ahorro que persigue el JIT.
    out["annual_co2eq_t"] = _to_num(raw[c_co2eq]) if c_co2eq else pd.NA
    out["co2_at_berth_t"] = _to_num(raw[c_co2_berth]) if c_co2_berth else pd.NA
    out["co2_in_port_t"] = _to_num(raw[c_co2_port]) if c_co2_port else pd.NA
    out["co2_per_distance_kg_per_nm"] = co2pd if co2pd is not None else pd.NA

    if c_dwt_direct:
        out["dwt"] = _to_num(raw[c_dwt_direct])
        dwt_src = c_dwt_direct
    elif c_fuel_per_dist and c_fuel_tw_dwt:
        out["dwt"] = _safe_ratio(fpd * 1000.0, _to_num(raw[c_fuel_tw_dwt]))
        dwt_src = "derivado (fuel/transport-work-dwt)"
    elif c_co2_per_dist and c_co2_tw_dwt:
        out["dwt"] = _safe_ratio(co2pd * 1000.0, _to_num(raw[c_co2_tw_dwt]))
        dwt_src = "derivado (CO₂/transport-work-dwt)"
    else:
        out["dwt"] = pd.NA
        dwt_src = "no disponible"

    if c_dist_direct:
        out["annual_distance_nm"] = _to_num(raw[c_dist_direct])
    elif c_fuel_per_dist:
        out["annual_distance_nm"] = _safe_ratio(out["annual_fuel_t"] * 1000.0, fpd)
    elif c_co2_per_dist:
        out["annual_distance_nm"] = _safe_ratio(out["annual_co2_t"] * 1000.0, co2pd)
    else:
        out["annual_distance_nm"] = pd.NA

    out = out[out["imo"].notna()]
    out["imo"] = out["imo"].astype("int64")
    out = out[(out["imo"] >= 1_000_000) & (out["imo"] <= 9_999_999)]
    n_dwt = int(out["dwt"].notna().sum())
    print(f"[INFO][THETIS] {len(out)} buques; DWT {dwt_src} ({n_dwt} con valor); eff={c_eff!r}.")
    _coherence_report(out)
    return out.reset_index(drop=True)


# Cotas físicas para auditar (no para recortar): fuera de rango = dato de origen dudoso.
_LIMITES = {
    "time_at_sea_h": (0, 8784),                    # horas de un año bisiesto
    "fuel_per_distance_kg_per_nm": (0, 2000),      # un portacontenedores grande ronda 300
    "co2_per_distance_kg_per_nm": (0, 6000),       # ~3 kg CO₂ por kg de fuel
}


def _coherence_report(df: pd.DataFrame) -> None:
    """
    Audita cobertura y plausibilidad de los campos enriquecidos. Solo informa: los
    valores se cargan tal cual, para no destruir en la ingesta lo que Flink podría
    querer inspeccionar.
    """
    total = len(df)
    if not total:
        return
    print("[INFO][THETIS] cobertura de campos enriquecidos:")
    for col in ("ship_type", "reporting_period", "technical_efficiency", "time_at_sea_h",
                "fuel_per_distance_kg_per_nm", "co2_per_distance_kg_per_nm",
                "annual_co2eq_t", "co2_at_berth_t", "co2_in_port_t"):
        if col not in df.columns:
            print(f"    {col:30s} COLUMNA NO ENCONTRADA en el fichero")
            continue
        n = int(df[col].notna().sum())
        pct = 100 * n / total
        aviso = "  <-- prácticamente vacía" if pct < 1 else ""
        print(f"    {col:30s} {n:6d}/{total} ({pct:5.1f}%){aviso}")

    avisos = []
    for col, (lo, hi) in _LIMITES.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        fuera = int(((s < lo) | (s > hi)).sum())
        if fuera:
            avisos.append(f"{fuera} en {col} fuera de [{lo}, {hi}] (máx {s.max():.4g})")
    # Relaciones que deben cumplirse por definición: la parte no puede exceder al todo.
    # NO se compara co2_at_berth_t con co2_in_port_t: no están anidadas (ver el COMMENT
    # de esas columnas en schema.sql), así que "atraque > en puerto" no es una anomalía.
    for parte, todo in (("co2_at_berth_t", "annual_co2_t"),
                        ("co2_in_port_t", "annual_co2_t"),
                        ("annual_co2_t", "annual_co2eq_t")):
        if {parte, todo} <= set(df.columns):
            a = pd.to_numeric(df[parte], errors="coerce")
            b = pd.to_numeric(df[todo], errors="coerce")
            imposible = int((a > b).sum())
            if imposible:
                avisos.append(f"{imposible} con {parte} > {todo} (imposible por definición)")
    if avisos:
        print("[AVISO][THETIS] valores implausibles en el fichero de origen (se cargan igual):")
        for a in avisos:
            print(f"    {a}")
    else:
        print("[INFO][THETIS] sin valores fuera de rango físico.")


def _num(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def _text(v):
    """Texto -> str limpio o None. `astype(str)` deja la cadena literal 'nan'."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ("", "nan", "none") else s


def _int(v):
    """Entero o None (para columnas como el año de reporte)."""
    n = _num(v)
    return None if n is None else int(n)


def build_rows(path: str | Path | None = None) -> list[dict]:
    """Filas listas para `db.upsert_thetis` (NaN -> None)."""
    df = load_thetis(path)
    rows = []
    for r in df.itertuples(index=False):
        rows.append({
            "imo": int(r.imo), "name": r.name, "ship_type": r.ship_type,
            "dwt": _num(r.dwt), "gt": _num(r.gt), "eexi": _num(r.eexi),
            "annual_fuel_t": _num(r.annual_fuel_t),
            "annual_distance_nm": _num(r.annual_distance_nm),
            "annual_co2_t": _num(r.annual_co2_t),
            "technical_efficiency": _text(r.technical_efficiency),
            "time_at_sea_h": _num(r.time_at_sea_h),
            "fuel_per_distance_kg_per_nm": _num(r.fuel_per_distance_kg_per_nm),
            "reporting_period": _int(r.reporting_period),
            "annual_co2eq_t": _num(r.annual_co2eq_t),
            "co2_at_berth_t": _num(r.co2_at_berth_t),
            "co2_in_port_t": _num(r.co2_in_port_t),
            "co2_per_distance_kg_per_nm": _num(r.co2_per_distance_kg_per_nm),
        })
    return rows


def load(conn, path: str | Path | None = None) -> int:
    """Carga puntual: THETIS-MRV -> tabla `thetis_mrv` en PostgreSQL."""
    rows = build_rows(path)
    db.upsert_thetis(conn, rows)
    print(f"[INFO][THETIS] {len(rows)} buques cargados en PostgreSQL.")
    return len(rows)


def main() -> None:
    """Carga puntual standalone (`python -m ingestion.src.reference.thetis`)."""
    with db.connect() as conn:
        db.init_schema(conn)
        load(conn)


if __name__ == "__main__":
    main()
