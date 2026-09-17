"""
Regresiones: fallos que ya ocurrieron y no deben volver.

No es una batería de cálculo —los módulos matemáticos no tienen tests
propios todavía—, sino la red mínima sobre los errores que se colaron en
producción. El criterio para entrar aquí es que el fallo fuera
SILENCIOSO: produjo números plausibles, nadie vio una excepción, y solo
se detectó comprobando el orden de magnitud a mano.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agents.tools import cii_calculus, open_meteo
from app.agents.tools.sea_route import Route


def test_fallo_de_meteo_degrada_en_vez_de_interrumpir(monkeypatch, paquete_1):
    """
    Regresión del incidente de la cuota de Open-Meteo.

    El proveedor empezó a devolver 429 al agotarse el free tier y, como la
    meteo se trataba de facto como un prerrequisito, CADA alerta moría: el
    sistema pasó 13 horas sin publicar una sola recomendación.

    La meteo es una CORRECCIÓN al cálculo, no un requisito. Sin ella la
    pérdida de Kwon es 0 y la recomendación sigue apoyada en la cola del
    puerto y la distancia navegable. Este test fija ese comportamiento: un
    fallo del proveedor no puede propagarse fuera del nodo.
    """
    from app.agents import math_oracle

    def _revienta(*_a, **_kw):
        raise RuntimeError("429 Too Many Requests")

    # Se parchea donde la función SE USA, no donde se define: math_oracle la
    # importó con `from ... import`, así que tiene su propia referencia y
    # parchear el módulo de origen no le afectaría.
    monkeypatch.setattr(math_oracle, "meteo_de_ruta", _revienta)
    fetch_weather = math_oracle.fetch_weather

    estado = {
        "paquete_1": paquete_1,
        "route": Route(distance_nm=325.9, duration_hours=27.9,
                       waypoints=[(7.13, 42.63), (4.0, 42.0), (2.17, 41.34)]),
        "speed_knot": 11.7,
        "departure_time": datetime(2026, 8, 16, 17, 20, tzinfo=timezone.utc),
    }
    salida = fetch_weather(estado)

    assert salida["meteo_degradada"] is True
    # Las series deben conservar la forma que espera kwon_euler: una entrada
    # por waypoint. Devolver listas vacías rompería la comprobación de
    # longitudes de construir_tramos y solo movería el fallo de sitio.
    assert len(salida["weather"]) == len(estado["route"].waypoints)
    assert len(salida["wind"]) == len(estado["route"].waypoints)
    assert salida["wind"][0]["wind_speed_kn"] is None


def test_submuestreo_conserva_extremos_de_la_derrota():
    """
    Open-Meteo factura por localización, no por petición: mandar los 14
    waypoints de media (hasta 63) de cada ruta agotaba la cuota diaria.

    El submuestreo debe conservar SIEMPRE el primer y el último punto —la
    posición del buque y el puerto—, que son los extremos de la
    integración, y no exceder el máximo.
    """
    puntos = [(float(i), 40.0 + i, datetime(2026, 9, 1, tzinfo=timezone.utc))
              for i in range(30)]
    muestreados, mapa = open_meteo.submuestrear_para_meteo(puntos, maximo=6)

    assert len(muestreados) <= 6
    assert muestreados[0] == puntos[0]
    assert muestreados[-1] == puntos[-1]
    # Cada waypoint original debe tener asignado un punto muestreado válido.
    assert len(mapa) == len(puntos)
    assert all(0 <= k < len(muestreados) for k in mapa)


def test_cii_por_almirantazgo_da_potencia_realista():
    """
    Regresión del fallo de unidades de `_cii_via_admiralty`.

    La potencia se calcula como P = Δ^(2/3) · V³ / C_adm, y los
    coeficientes de Almirantazgo tabulados están calibrados para V en
    NUDOS. Convertir a m/s antes de elevar al cubo dividía la potencia
    por (1/0,5144)³ ≈ 7,3, haciendo el CII siete veces más optimista de
    lo real — por la vía de respaldo, que es la habitual (la mayoría de
    buques no tienen EEXI declarado en THETIS).

    No saltó ninguna excepción: el CII salía ~0,8 en vez de ~5,9, una
    cifra que sigue pareciendo razonable si no se contrasta. Por eso el
    test comprueba ORDEN DE MAGNITUD, no un valor exacto: un CII
    operacional de un granelero se mueve entre 3 y 10 gCO₂/(t·nm).
    """
    webhook = {
        "eslora": 190, "manga": 32, "calado_de_diseno": 11.0,
        "velocidad_buque": 14.0, "tipo_buque": 70,   # AIS: carga
    }
    resultado = cii_calculus.estimar_cii(webhook, distancia_nm=300.0, db_record=None)

    assert resultado.metodo != "eexi", "sin db_record debe ir por la vía de respaldo"

    # Con el código correcto este buque da ~8,9; con el error de unidades daba
    # ~1,2. La cota INFERIOR es la que caza el fallo, y por eso no puede ser
    # laxa: un rango 1-20 dejaba pasar el valor erróneo. 3-20 cubre el rango
    # operacional razonable de un carguero de este porte con margen a ambos
    # lados, sin quedar tan ajustado que se rompa al recalibrar constantes.
    assert 3.0 < resultado.cii < 20.0, (
        f"CII fuera de rango físico: {resultado.cii}. Un valor ~7x menor de lo "
        "esperado apunta a haber convertido nudos a m/s en la potencia cúbica: "
        "los coeficientes de Almirantazgo están calibrados para NUDOS."
    )


def test_el_cii_baja_al_reducir_velocidad():
    """
    La propiedad que sostiene toda la recomendación: la potencia crece
    con el cubo de la velocidad, así que navegar más despacio tiene que
    mejorar el CII. Si esto dejara de cumplirse, el oráculo estaría
    recomendando frenar sin fundamento.
    """
    base = {"eslora": 190, "manga": 32, "calado_de_diseno": 11.0, "tipo_buque": 70}

    rapido = cii_calculus.estimar_cii({**base, "velocidad_buque": 14.0}, 300.0, db_record=None)
    lento = cii_calculus.estimar_cii({**base, "velocidad_buque": 10.0}, 300.0, db_record=None)

    assert lento.cii < rapido.cii


def test_fuel_saved_requiere_dwt_real_no_estimado():
    """
    `dwt_real_t` solo se rellena con el dato de THETIS-MRV; el DWT
    estimado desde las dimensiones del casco vive en `dwt_estimado` y no
    debe alimentar cifras de combustible ahorrado, que invitan a
    creérselas más de lo que la estimación permite.
    """
    webhook = {"eslora": 190, "manga": 32, "calado_de_diseno": 11.0,
               "velocidad_buque": 14.0, "tipo_buque": 70}
    resultado = cii_calculus.estimar_cii(webhook, 300.0, db_record=None)

    assert resultado.dwt_estimado is not None   # sí se estima, para el CII
    assert resultado.dwt_real_t is None         # pero no se hace pasar por real


@pytest.mark.parametrize("codigo,esperado", [
    (70, "general_cargo"),   # Cargo genérico
    (80, "oil_tanker"),      # Tanker
    (60, "passenger"),       # Passenger
])
def test_codigo_ais_se_traduce_a_tipo(codigo, esperado):
    """
    El código AIS es el último recurso cuando no hay IMO. Su mapeo
    decide el coeficiente de bloque y el Froude de diseño, así que un
    error aquí desplaza silenciosamente todo el cálculo de emisiones.
    """
    assert cii_calculus._tipo_desde_codigo_ais(codigo) == esperado
