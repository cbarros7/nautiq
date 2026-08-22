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

/**
 * Solo para la LEYENDA del mapa, que explica qué codifica el color. Y el color codifica
 * la calidad del AJUSTE de velocidad, no el resultado JIT: el verde cubre tambien a los
 * buques que van a fondear igual, porque frenar sigue siendo buen consejo. Enunciar ahi
 * «llega a tiempo» era falso en la mitad de los casos.
 *
 * El resultado JIT de un evento concreto lo dice `titular()`, y el fondeo inevitable lo
 * marca `fondearaIgual()` con un simbolo aparte del color.
 */
export const ETIQUETA_SEVERIDAD: Record<Severidad, string> = {
  ok: 'Ajuste que reduce emisiones',
  alert: 'Ajuste que aumenta emisiones',
  critical: 'Ajuste no ejecutable',
}

/**
 * En jerga, esto era «slow steaming máximo» y «a máxima velocidad». Dicho en lo que le
 * pasa al buque: si ni al minimo consigue llegar tarde, va a esperar fondeado de todas
 * formas; si ni a maxima llega, pierde el atraque.
 */
export const ETIQUETA_SATURACION: Record<Saturacion, string> = {
  ninguna: 'Velocidad ajustada al hueco de atraque',
  'frenando-al-minimo': 'Incluso al mínimo llega antes de tener atraque',
  'a-maxima-velocidad': 'Ni a máxima velocidad alcanza el hueco',
}

/**
 * Solo se rotula la fiabilidad BAJA, y con una palabra: es el unico caso en que el
 * numero no es comparable con el de otro buque. Rotular «media» no informaba de nada y
 * hacia parecer que faltaban datos.
 */
export const ETIQUETA_FIABILIDAD: Record<Fiabilidad, string | null> = {
  alta: null,
  media: null,
  baja: 'estimado',
}

/** Explicacion larga, para el `title` del rotulo. No ocupa sitio en pantalla. */
export const DETALLE_FIABILIDAD: Record<Fiabilidad, string> = {
  alta: 'CII a partir del EEXI declarado del buque y su peso muerto real.',
  media: 'CII a partir del EEXI declarado del buque.',
  baja: 'CII calculado desde las dimensiones del casco, porque el buque no declara EEXI. '
      + 'Sirve para comparar este buque consigo mismo a dos velocidades, no con otros buques.',
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


/**
 * El enunciado de UN evento. Combina severidad y saturacion, porque por separado se
 * contradicen: el caso mas frecuente (`frenando-al-minimo`) es `ok` —- la recomendacion es
 * buena y el CII mejora— pero el buque NO llega a tiempo: fondea igual. Anunciar «llega a
 * tiempo» ahi era falso (ver §7.9 de FRONTEND.md).
 *
 * El orden de las comprobaciones importa: que la recomendacion no sea ejecutable manda
 * sobre todo lo demas, y `excede_v_diseno` puede darse con `convergio` true (la biseccion
 * encuentra solucion, pero por encima de la velocidad de diseno del casco).
 */
export function titular(r: OracleRecommendationV1['recommendation']): string {
  if (r.excede_v_diseno) return 'Necesita más velocidad de la de diseño'
  if (saturacion(r) === 'frenando-al-minimo') return 'Fondeará igual: solo recorta el consumo'
  if (r.alerta_cii) return 'Llega a tiempo, emitiendo más'
  return 'Llega a tiempo emitiendo menos'
}

/**
 * El buque va a fondear esperando atraque hagamos lo que hagamos. Es la señal que faltaba
 * en el mapa: sin ella, media flota sale en verde y parece que el JIT esta funcionando
 * cuando en realidad el puerto esta saturado.
 */
export function fondearaIgual(r: OracleRecommendationV1['recommendation']): boolean {
  return saturacion(r) === 'frenando-al-minimo'
}
