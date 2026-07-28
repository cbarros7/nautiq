"""
Contratos Pydantic de AIS

Validan rangos escalares y obligatoriedad sobre el crudo de AISStream y producen
un dict que cumple el esquema Avro de `contracts/` (`ais_position_v1.avsc`,
`ais_static_v1.avsc`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

# Fracción de segundo del time_utc de AISStream. Emite NANOsegundos (9 dígitos) y
# `%f` de strptime admite 6 como máximo, así que hay que truncarla.
_FRACTION_RE = re.compile(r"\.(\d+)")


class ContractError(ValueError):
    """El payload no cumple el contrato -> el productor lo descarta (no publica)."""


def _normalize_time(raw: str) -> str:
    """
    time_utc de AISStream ('2026-07-28 17:13:08.621081171 +0000 UTC') -> ISO-8601 UTC.

    El contrato Avro promete ISO-8601, así que un timestamp que no se pueda convertir
    es un incumplimiento y va a la DLQ. No se devuelve el crudo: eso publicaría un
    formato que Flink no sabe parsear haciéndolo pasar por válido.
    """
    if not raw:
        raise ContractError("timestamp ausente")
    cleaned = raw.replace(" UTC", "").strip()
    cleaned = _FRACTION_RE.sub(lambda m: "." + m.group(1)[:6], cleaned, count=1)
    fmt = "%Y-%m-%d %H:%M:%S.%f %z" if "." in cleaned else "%Y-%m-%d %H:%M:%S %z"
    try:
        return datetime.strptime(cleaned, fmt).astimezone(timezone.utc).isoformat()
    except ValueError as e:
        raise ContractError(f"timestamp no convertible a ISO-8601: {raw!r} ({e})") from e


def _clean_ais_text(value: str | None) -> str | None:
    """Limpia el relleno '@' y espacios del texto AIS."""
    if value is None:
        return None
    cleaned = value.replace("@", "").strip()
    return cleaned or None


class AISPosition(BaseModel):
    """Contrato del topic `vessel.positions.raw` (ais_position_v1.avsc)."""

    model_config = ConfigDict(populate_by_name=True)

    mmsi: int = Field(gt=0)
    timestamp: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed: float = Field(ge=0)
    cog: float | None = None
    heading: int | None = None
    nav_status: int | None = None
    ingested_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        alias="_ingested_at",
        description="Metadato de ingestion (momento de validación, no del reporte AIS).",
    )

    @classmethod
    def from_message(cls, message: dict) -> "AISPosition":
        """Valida un `PositionReport` crudo; ContractError si no cumple."""
        meta = message.get("MetaData", {})
        pr = message.get("Message", {}).get("PositionReport", {})
        mmsi = meta.get("MMSI") or pr.get("UserID")
        try:
            return cls(
                mmsi=int(mmsi) if mmsi else 0,
                timestamp=_normalize_time(meta.get("time_utc", "")),
                lat=pr.get("Latitude"),
                lon=pr.get("Longitude"),
                speed=pr.get("Sog"),
                cog=pr.get("Cog"),
                heading=pr.get("TrueHeading"),
                nav_status=pr.get("NavigationalStatus"),
            )
        except Exception as e:
            raise ContractError(str(e)) from e


class AISStatic(BaseModel):
    """Contrato del topic `vessel.static.raw` (ais_static_v1.avsc)."""

    model_config = ConfigDict(populate_by_name=True)

    mmsi: int = Field(gt=0)
    imo: int | None = None
    name: str | None = None
    callsign: str | None = None
    ship_type: int | None = None
    length_m: int | None = None
    beam_m: int | None = None
    draught_m: float | None = None
    destination: str | None = None
    eta: str | None = None
    ingested_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        alias="_ingested_at",
        description="Metadato de ingestion (momento de validación, no del reporte AIS).",
    )

    @classmethod
    def from_message(cls, message: dict) -> "AISStatic":
        """Valida un `ShipStaticData` crudo; ContractError si no cumple."""
        data = message.get("Message", {}).get("ShipStaticData", {})
        mmsi = data.get("UserID") or message.get("MetaData", {}).get("MMSI")
        imo = data.get("ImoNumber") or 0
        dim = data.get("Dimension", {}) or {}
        length = (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0)
        beam = (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0)
        raw_draught = data.get("MaximumStaticDraught")
        eta = data.get("Eta")
        try:
            return cls(
                mmsi=int(mmsi) if mmsi else 0,
                imo=int(imo) if imo else None,
                name=_clean_ais_text(data.get("Name")),
                callsign=_clean_ais_text(data.get("CallSign")),
                ship_type=data.get("Type"),
                length_m=length or None,
                beam_m=beam or None,
                draught_m=round(raw_draught, 2) if isinstance(raw_draught, (int, float)) else None,
                destination=_clean_ais_text(data.get("Destination")),
                # AISStream manda Eta como objeto {Month, Day, Hour, Minute}. `str()`
                # daría repr de Python (comillas simples) y no sería JSON parseable;
                # `sort_keys` fija el orden para no depender del dict de origen.
                # Los centinelas de "no disponible" (Month/Day=0, Hour=24, Minute=60)
                # se transportan tal cual: interpretarlos es de Flink.
                eta=json.dumps(eta, sort_keys=True) if eta else None,
            )
        except Exception as e:
            raise ContractError(str(e)) from e
