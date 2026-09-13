"""
Regresiones: fallos que ya ocurrieron y no deben volver.

No es una batería de cálculo —los módulos matemáticos no tienen tests
propios todavía—, sino la red mínima sobre los errores que se colaron en
producción. El criterio para entrar aquí es que el fallo fuera
SILENCIOSO: produjo números plausibles, nadie vio una excepción, y solo
se detectó comprobando el orden de magnitud a mano.
"""

from __future__ import annotations

import pytest

from app.agents.tools import cii_calculus


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
