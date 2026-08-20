/**
 * Severidad y fiabilidad, derivadas de las señales nativas del oráculo.
 *
 * El oráculo NO emite `status` ni `confidence`, deliberadamente: un `status` calculado
 * aguas arriba habría sido una regla de presentación disfrazada de dato. Expone en su
 * lugar `convergio`, `excede_v_diseno`, `alerta_cii`, `nota` y `cii.metodo`, y la
 * traducción a color vive aquí — en un solo sitio, para que sea auditable.
 *
 * LO QUE NO HAY QUE HACER, y es la trampa evidente: usar `convergio === false` como
 * alerta. `convergio` no es un indicador de error, es un indicador de SATURACIÓN, y
 * cubre dos situaciones opuestas (ver `saturacion()`):
 *
 *   - sobra tiempo incluso a velocidad mínima  -> se recomienda el mínimo. Es el caso
 *     BUENO del JIT, y sobre datos reales del oráculo es además el más frecuente.
 *   - la ventana no llega ni a velocidad máxima -> el buque llega tarde aunque vaya a
 *     tope. Ese sí merece atención.
 *
 * Sobre los 11 eventos grabados en mock/events.json, `convergio` es false en 7. Tratarlo
 * como alerta pintaría de rojo casi todo el mapa y el color dejaría de informar.
 *
 * El discriminador robusto es el signo de `speed_delta_kn` (frenar vs. acelerar) junto a
 * `excede_v_diseno`. No se hace coincidencia de cadenas sobre `nota`: es prosa libre.
 */
import type { OracleRecommendationV1 } from './types'

export type Severidad = 'ok' | 'alert' | 'critical'
export type Fiabilidad = 'alta' | 'media' | 'baja'
export type Saturacion = 'ninguna' | 'frenando-al-minimo' | 'a-maxima-velocidad'

/**
 * Qué merece la atención de quien mira el mapa.
 *
 *  critical — la recomendación no es ejecutable: pide más velocidad que la de diseño
 *             del casco. El buque va a llegar tarde y no hay nada que hacer.
 *  alert    — la recomendación es ejecutable pero CUESTA emisiones: el CII empeora al
 *             seguirla. Es el resultado más interesante que produce el oráculo y se
 *             pinta, no se esconde.
 *  ok       — frenar mejora el CII. El caso que justifica el proyecto.
 */
export function severidad(r: OracleRecommendationV1['recommendation']): Severidad {
  if (r.excede_v_diseno) return 'critical'
  if (r.alerta_cii) return 'alert'
  return 'ok'
}

/**
 * Cuánto se puede afirmar del número, en un eje aparte del color. Nunca oculta nada:
 * degrada la opacidad Y añade un rótulo, porque un color más pálido no comunica
 * "este CII sale de un DWT geométrico".
 */
export function fiabilidad(r: OracleRecommendationV1['recommendation']): Fiabilidad {
  if (r.cii.metodo === 'fallback_admiralty') return 'baja'
  if (r.fuel_saved_t !== null && r.fuel_saved_t !== undefined) return 'alta'
  return 'media'
}

/** En qué extremo del rango realizable del casco se quedó la solución, si se quedó en uno. */
export function saturacion(r: OracleRecommendationV1['recommendation']): Saturacion {
  if (r.convergio) return 'ninguna'
  return r.speed_delta_kn < 0 ? 'frenando-al-minimo' : 'a-maxima-velocidad'
}

export const ETIQUETA_SEVERIDAD: Record<Severidad, string> = {
  ok: 'Frenar mejora el CII',
  alert: 'Frenar empeora el CII',
  critical: 'No ejecutable',
}

export const ETIQUETA_SATURACION: Record<Saturacion, string> = {
  ninguna: 'Ventana JIT alcanzable',
  'frenando-al-minimo': 'Slow steaming máximo',
  'a-maxima-velocidad': 'A máxima velocidad',
}

export const ETIQUETA_FIABILIDAD: Record<Fiabilidad, string> = {
  alta: 'CII declarado (EEXI) y DWT real',
  media: 'CII declarado (EEXI), sin DWT real',
  baja: 'CII estimado desde el casco',
}

/** Colores de estado. Separados del acento de la interfaz: codifican dato, no marca. */
export const COLOR_SEVERIDAD: Record<Severidad, string> = {
  ok: '#2f9e6f',
  alert: '#d99320',
  critical: '#d64545',
}

export const OPACIDAD_FIABILIDAD: Record<Fiabilidad, number> = {
  alta: 1,
  media: 0.9,
  baja: 0.62,
}
