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
    return out.reset_index(drop=True)


def _num(v):
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


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
