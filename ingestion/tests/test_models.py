"""Tests de los contratos Pydantic de AIS (ingestion/src/ais/models.py)."""

import pytest

from ingestion.src.ais.models import (
    AISPosition,
    AISStatic,
    ContractError,
    _clean_ais_text,
    _normalize_time,
)


class TestNormalizeTime:
    def test_convierte_formato_aisstream_a_iso8601(self):
        resultado = _normalize_time("2026-07-28 17:13:08.621081171 +0000 UTC")
        assert resultado == "2026-07-28T17:13:08.621081+00:00"

    def test_admite_timestamp_sin_fraccion_de_segundo(self):
        resultado = _normalize_time("2026-07-28 17:13:08 +0000 UTC")
        assert resultado == "2026-07-28T17:13:08+00:00"

    def test_timestamp_vacio_lanza_contract_error(self):
        with pytest.raises(ContractError):
            _normalize_time("")

    def test_timestamp_no_parseable_lanza_contract_error(self):
        with pytest.raises(ContractError):
            _normalize_time("no es una fecha")


class TestCleanAisText:
    def test_quita_relleno_arroba_y_espacios(self):
        assert _clean_ais_text("ALGECIRAS@@@@  ") == "ALGECIRAS"

    def test_texto_solo_relleno_da_none(self):
        assert _clean_ais_text("@@@@@@") is None

    def test_none_da_none(self):
        assert _clean_ais_text(None) is None


class TestAISPosition:
    def _mensaje(self, **overrides):
        base = {
            "MetaData": {"MMSI": 224123456, "time_utc": "2026-07-28 17:13:08.621081171 +0000 UTC"},
            "Message": {
                "PositionReport": {
                    "Latitude": 36.1,
                    "Longitude": -5.3,
                    "Sog": 12.5,
                    "Cog": 88.0,
                    "TrueHeading": 90,
                    "NavigationalStatus": 0,
                }
            },
        }
        base.update(overrides)
        return base

    def test_construye_posicion_valida_desde_mensaje_crudo(self):
        pos = AISPosition.from_message(self._mensaje())
        assert pos.mmsi == 224123456
        assert pos.lat == 36.1
        assert pos.lon == -5.3
        assert pos.speed == 12.5
        assert pos.heading == 90
        assert pos.timestamp == "2026-07-28T17:13:08.621081+00:00"

    def test_mmsi_ausente_lanza_contract_error(self):
        mensaje = self._mensaje(MetaData={"time_utc": "2026-07-28 17:13:08 +0000 UTC"})
        with pytest.raises(ContractError):
            AISPosition.from_message(mensaje)

    def test_latitud_fuera_de_rango_lanza_contract_error(self):
        mensaje = self._mensaje()
        mensaje["Message"]["PositionReport"]["Latitude"] = 120.0
        with pytest.raises(ContractError):
            AISPosition.from_message(mensaje)


class TestAISStatic:
    def _mensaje(self, **overrides):
        base = {
            "MetaData": {"MMSI": 224123456},
            "Message": {
                "ShipStaticData": {
                    "UserID": 224123456,
                    "ImoNumber": 9321483,
                    "Name": "EVER GIVEN@@@",
                    "CallSign": "H3RC@",
                    "Type": 70,
                    "Dimension": {"A": 150, "B": 50, "C": 20, "D": 10},
                    "MaximumStaticDraught": 12.345,
                    "Destination": "ALGECIRAS@@@",
                    "Eta": {"Month": 7, "Day": 28, "Hour": 18, "Minute": 30},
                }
            },
        }
        base.update(overrides)
        return base

    def test_construye_estatico_valido_desde_mensaje_crudo(self):
        estatico = AISStatic.from_message(self._mensaje())
        assert estatico.mmsi == 224123456
        assert estatico.imo == 9321483
        assert estatico.name == "EVER GIVEN"
        assert estatico.callsign == "H3RC"
        assert estatico.length_m == 200
        assert estatico.beam_m == 30
        assert estatico.draught_m == 12.35
        assert estatico.destination == "ALGECIRAS"
        assert estatico.eta == '{"Day": 28, "Hour": 18, "Minute": 30, "Month": 7}'

    def test_sin_imo_da_none(self):
        mensaje = self._mensaje()
        mensaje["Message"]["ShipStaticData"]["ImoNumber"] = 0
        estatico = AISStatic.from_message(mensaje)
        assert estatico.imo is None

    def test_mmsi_ausente_lanza_contract_error(self):
        mensaje = self._mensaje(MetaData={})
        mensaje["Message"]["ShipStaticData"]["UserID"] = 0
        with pytest.raises(ContractError):
            AISStatic.from_message(mensaje)
