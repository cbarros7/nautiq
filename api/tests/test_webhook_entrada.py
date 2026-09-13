"""
Frontera de ENTRADA: lo que el webhook acepta, rechaza y descarta.

Esta frontera importa porque el productor (Flink) no valida contra el
contrato: manda lo que tiene. El oráculo debe distinguir tres cosas que
se parecen y no lo son:

  - petición mal formada        -> 400, culpa del llamador
  - alerta que NO aplica        -> 422, nadie tiene la culpa, no reintentar
  - fallo del pipeline          -> 500, culpa nuestra, reintentar puede valer

Confundir el 422 con el 500 haría que Flink reintentara indefinidamente
alertas de buques atracados, y que los fallos reales se perdieran entre
ellas.
"""

from __future__ import annotations

import json

import azure.functions as func
import pytest

import function_app
from app.agents.math_oracle import BuqueNoNavegandoError


def _peticion(cuerpo) -> func.HttpRequest:
    """Construye una petición HTTP como la que recibiría la Function."""
    if cuerpo is None:
        datos = b"esto no es json"
    else:
        datos = json.dumps(cuerpo).encode("utf-8")
    return func.HttpRequest(
        method="POST", url="http://localhost/api/alerta", body=datos,
        headers={"Content-Type": "application/json"},
    )


def _llamar(handler, peticion):
    """El decorador devuelve un FunctionBuilder; dentro está la función real."""
    return handler._function.get_user_function()(peticion)


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.get_body().decode("utf-8"))


#: Evento mínimo con las claves que el handler lee para su log de éxito.
#: Si el contrato crece y el handler loguea más campos, este stub debe
#: crecer con él — es la señal de que el handler depende de la forma.
_EVENTO_MINIMO = {
    "event_id": "01M0TEST",
    "recommendation": {"recommended_speed_kn": 5.92},
    "queue": {"estimated_wait_hours": 75.3},
}


# ── Peticiones mal formadas: 400 ──────────────────────────────────────

def test_cuerpo_no_json_devuelve_400():
    r = _llamar(function_app.alerta, _peticion(None))
    assert r.status_code == 400
    assert "error" in _cuerpo(r)


@pytest.mark.parametrize("cuerpo", [
    {},                                  # vacío
    {"paquete_1": {"mmsi": 1}},          # falta paquete_2
    {"paquete_2": {"puerto": "X"}},      # falta paquete_1
    {"paquete_1": None, "paquete_2": {}},
    [1, 2, 3],                           # JSON válido pero no un objeto
])
def test_cuerpo_incompleto_devuelve_400(cuerpo):
    r = _llamar(function_app.alerta, _peticion(cuerpo))
    assert r.status_code == 400


# ── El contrato de entrada, campo a campo ─────────────────────────────

def test_campos_obligatorios_declarados():
    """
    Fija los campos de paquete_1 sin los que el oráculo no puede
    trabajar. Es documentación ejecutable del acuerdo con el productor:
    si Flink renombra uno, este test señala cuál era el esperado en vez
    de dejar un KeyError críptico dentro del grafo.

    Cambiar esta lista debe ser un acto consciente y coordinado con quien
    emite las alertas, no un efecto colateral de refactorizar.
    """
    assert set(function_app.CAMPOS_OBLIGATORIOS) == {
        "puerto", "lat_buque", "lon_buque", "lat_port", "lon_port", "velocidad_buque",
    }


@pytest.mark.parametrize("campo", [
    "puerto", "lat_buque", "lon_buque", "lat_port", "lon_port", "velocidad_buque",
])
def test_campo_obligatorio_ausente_devuelve_400_nombrandolo(alerta_valida, campo):
    """
    Un campo renombrado por el productor produce un JSON perfectamente
    válido: la validación de "¿están paquete_1 y paquete_2?" lo deja
    pasar, y antes reventaba dentro del grafo como 500 sin decir cuál.
    Ahora sale 400 con el nombre del campo.
    """
    alerta_valida["paquete_1"].pop(campo)
    r = _llamar(function_app.alerta, _peticion(alerta_valida))

    assert r.status_code == 400
    assert campo in _cuerpo(r)["campos_faltantes"]


def test_campos_opcionales_ausentes_no_bloquean(monkeypatch, alerta_valida):
    """
    Lo que NO es obligatorio debe degradar, no rechazar: sin IMO se cae
    al código AIS, sin correlation_id se genera un ULID nuevo. Tratar
    todo como obligatorio haría el webhook innecesariamente frágil.
    """
    for opcional in ("imo", "correlation_id", "ETA_dynamic", "direccion", "estado"):
        alerta_valida["paquete_1"].pop(opcional, None)

    monkeypatch.setattr(function_app, "_procesar_alerta", lambda a: _EVENTO_MINIMO)
    r = _llamar(function_app.alerta, _peticion(alerta_valida))
    assert r.status_code == 200


# ── Alerta no aplicable: 422 ──────────────────────────────────────────

def test_buque_parado_devuelve_422(monkeypatch, alerta_valida):
    """
    Un buque atracado o parado no es un error: no hay velocidad que
    recomendar. Debe salir 422 y NO 500, para que el llamador sepa que
    reintentar no va a cambiar nada.
    """
    def _no_navega(alerta):
        raise BuqueNoNavegandoError("velocidad_buque=0.0 (nav_status=5)")

    monkeypatch.setattr(function_app, "_procesar_alerta", _no_navega)
    r = _llamar(function_app.alerta, _peticion(alerta_valida))

    assert r.status_code == 422
    cuerpo = _cuerpo(r)
    assert cuerpo["descartada"] is True
    assert "motivo" in cuerpo


def test_velocidad_cero_lanza_error_tipado(paquete_1):
    """
    El error es de un tipo propio, no un ValueError genérico: es lo que
    permite al handler distinguir "descartar" de "ha fallado algo".
    """
    from app.agents.math_oracle import fetch_datos_buque

    parado = dict(paquete_1, velocidad_buque=0.0, estado=5)
    with pytest.raises(BuqueNoNavegandoError):
        fetch_datos_buque({"paquete_1": parado})


# ── Fallo real: 500 ───────────────────────────────────────────────────

def test_fallo_inesperado_devuelve_500(monkeypatch, alerta_valida):
    def _revienta(alerta):
        raise RuntimeError("Supabase inalcanzable")

    monkeypatch.setattr(function_app, "_procesar_alerta", _revienta)
    r = _llamar(function_app.alerta, _peticion(alerta_valida))

    assert r.status_code == 500
    assert "RuntimeError" in _cuerpo(r)["error"]


# ── Camino feliz: 200 ─────────────────────────────────────────────────

def test_alerta_valida_devuelve_200_con_el_evento(monkeypatch, alerta_valida):
    evento = {"event_id": "01M0TEST", "recommendation": {"recommended_speed_kn": 5.92},
              "queue": {"estimated_wait_hours": 75.3}}
    monkeypatch.setattr(function_app, "_procesar_alerta", lambda a: evento)

    r = _llamar(function_app.alerta, _peticion(alerta_valida))
    assert r.status_code == 200
    assert _cuerpo(r)["event_id"] == "01M0TEST"


# ── Normalización de la entrada ───────────────────────────────────────

def test_usa_coordenadas_del_puerto_del_mensaje(paquete_1):
    """
    El webhook ya trae lat_port/lon_port; no debe resolverse el puerto
    contra ninguna tabla (una consulta de más por alerta, y un punto de
    fallo que no hace falta).
    """
    from app.agents.math_oracle import fetch_datos_buque

    salida = fetch_datos_buque({"paquete_1": paquete_1})
    assert salida["port"].lat == paquete_1["lat_port"]
    assert salida["port"].lon == paquete_1["lon_port"]
    assert salida["port"].name == "BARCELONA"
    assert salida["speed_knot"] == 11.7


@pytest.mark.parametrize("valor,espera_utc", [
    ("2026-08-16T17:20:18.122700+00:00", True),   # ISO con zona
    ("2026-08-16T17:20:18.122700", True),         # ISO sin zona -> se asume UTC
])
def test_ingest_timestamp_se_normaliza_a_utc(paquete_1, valor, espera_utc):
    """
    `ingest_timestamp` es el instante de referencia contra el que se
    calculan las ETA. Sin zona horaria explícita, compararlo con un
    `datetime` con zona reventaría al restar.
    """
    from app.agents.math_oracle import fetch_datos_buque

    salida = fetch_datos_buque({"paquete_1": dict(paquete_1, ingest_timestamp=valor)})
    assert (salida["event_timestamp"].tzinfo is not None) is espera_utc


def test_sin_ingest_timestamp_no_revienta(paquete_1):
    """Contratos antiguos o de test pueden no traerlo: se usa 'ahora'."""
    from app.agents.math_oracle import fetch_datos_buque

    sin_ts = {k: v for k, v in paquete_1.items() if k != "ingest_timestamp"}
    salida = fetch_datos_buque({"paquete_1": sin_ts})
    assert salida["event_timestamp"].tzinfo is not None


# ── Salud ─────────────────────────────────────────────────────────────

def test_health_expone_el_entorno_activo():
    """
    /api/health es lo que delata una NAUTIQ_ENV mal puesta, que si no
    escribiría en las tablas del otro entorno sin dar ningún error.
    """
    peticion = func.HttpRequest(method="GET", url="http://localhost/api/health", body=b"")
    r = _llamar(function_app.health, peticion)

    assert r.status_code == 200
    cuerpo = _cuerpo(r)
    assert cuerpo["estado"] == "ok"
    assert cuerpo["entorno"] in ("DEV", "PRO")
    assert "tabla_recomendaciones" in cuerpo
    assert "build" in cuerpo
