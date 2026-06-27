"""
Reference: UN/LOCODE -> tabla `ports` en PostgreSQL.

EVALUACIÓN (§1) — librería `locode` de Python vs persistencia del dataset:
  * La librería `locode` (PyPI) expone códigos ISO-3166 y ciudades, pero **NO trae
    coordenadas**. searoute necesita lat/lon, así que la librería NO cubre el caso.
  * `pyunlocode` parsea el CSV de la UNECE a SQLite (sigue siendo persistencia) y
    su cobertura de coordenadas es la oficial (~80%, con huecos en puertos clave
    como Valencia/Algeciras/Barcelona).
  * Persistir el dataset `improved-un-locodes` (código UNECE + coordenadas
    decimales de OSM/Wikidata, 98,6%) en PostgreSQL da cobertura completa y queda
    consultable/joinable por Flink y la API.
  => DECISIÓN: **persistencia en PostgreSQL** (más simple y mantenible para nuestro
     caso). La librería se descarta por falta de coordenadas.

El dataset se auto-descarga a `data/reference/un_locode.csv` si falta.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

from .. import config
from . import db

_REFERENCE_DIR = config.PROJECT_ROOT / "data" / "reference"
_LOCODE_CSV = _REFERENCE_DIR / "un_locode.csv"
_LOCODE_URL = (
    "https://raw.githubusercontent.com/cristan/improved-un-locodes/main/"
    "data/code-list-improved.csv"
)


def ensure_dataset(path: Path | None = None) -> Path:
    """Descarga el dataset UN/LOCODE si no está en local."""
    path = path or _LOCODE_CSV
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[INFO][LOCODE] Descargando UN/LOCODE de {_LOCODE_URL} ...")
        urllib.request.urlretrieve(_LOCODE_URL, path)
    return path


def _parse_decimal(coord: str) -> tuple[float | None, float | None]:
    """'39.4697,-0.3763' -> (39.4697, -0.3763)."""
    if not isinstance(coord, str) or "," not in coord:
        return (None, None)
    try:
        lat, lon = coord.split(",", 1)
        return (round(float(lat), 6), round(float(lon), 6))
    except (ValueError, TypeError):
        return (None, None)


def build_rows(path: str | Path | None = None) -> list[dict]:
    """Parsea el CSV y devuelve filas de puertos marítimos con coordenadas (sin DB)."""
    csv_path = ensure_dataset(Path(path) if path else None)
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df = df[df["Location"].str.strip() != ""]
    df = df[df["Function"].str.startswith("1")]  # '1' en pos 0 = Puerto (Rec. 16)

    rows = []
    for r in df.itertuples(index=False):
        lat, lon = _parse_decimal(r.CoordinatesDecimal)
        if lat is None or lon is None:
            continue
        rows.append({"locode": f"{r.Country}{r.Location}", "name": r.Name,
                     "country": r.Country, "lat": lat, "lon": lon})
    return rows


def load(conn, path: str | Path | None = None) -> int:
    """Carga puntual: UN/LOCODE -> tabla `ports` en PostgreSQL."""
    rows = build_rows(path)
    db.upsert_ports(conn, rows)
    print(f"[INFO][LOCODE] {len(rows)} puertos marítimos cargados en PostgreSQL.")
    return len(rows)


def main() -> None:
    """Carga puntual standalone (`python -m ingestion.src.reference.locode`)."""
    with db.connect() as conn:
        db.init_schema(conn)
        load(conn)


if __name__ == "__main__":
    main()
