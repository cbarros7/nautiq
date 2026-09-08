/**
 * Escala de estado del mar — bandas Douglas reales, no cuantiles del fixture.
 *
 * Se usa la escala del propio dominio en vez de partir los datos en cinco trozos
 * iguales: un marino lee "marejada" y sabe qué significa, y una escala derivada de
 * once eventos haría parecer dramático un Mediterráneo en calma. Los cortes son los
 * de la escala Douglas de mar de viento (altura significativa, en metros).
 *
 * La rampa es secuencial de un solo tono (naranja), validada con
 * `validate_palette.js --ordinal --mode dark` sobre la superficie del mapa:
 * lightness monótona, huecos ΔL >= 0.06, tono dentro de 21°, y el paso más cercano
 * a la superficie a 2.08:1. Naranja y no azul a propósito: el mapa es oscuro y el
 * mar es azul, así que un secuencial azul se perdería en el fondo — es además lo
 * que hacen las cartas náuticas, notación cálida sobre agua fría.
 *
 * Las bandas están alineadas para que el rango habitual del Mediterráneo (medido en
 * el fixture: 0,24–1,74 m) caiga en los pasos centrales, los más brillantes.
 */
export interface BandaMar {
  /** Límite superior de la banda, en metros. `Infinity` en la última. */
  hasta: number
  nombre: string
  color: string
}

export const BANDAS_DOUGLAS: BandaMar[] = [
  { hasta: 0.1,      nombre: 'Mar en calma',    color: '#7a3d18' },
  { hasta: 0.5,      nombre: 'Rizada',           color: '#a85a20' },
  { hasta: 1.25,     nombre: 'Marejada',         color: '#d17a2a' },
  { hasta: 2.5,      nombre: 'Fuerte marejada',  color: '#ee9f45' },
  { hasta: Infinity, nombre: 'Gruesa o más',     color: '#ffc98a' },
]

/** Color para una altura de ola. `null` (sin cobertura del modelo) -> gris apagado. */
export const COLOR_SIN_OLEAJE = '#5a5a57'

export function bandaDe(alturaM: number | null | undefined): BandaMar | null {
  if (alturaM === null || alturaM === undefined) return null
  return BANDAS_DOUGLAS.find((b) => alturaM < b.hasta) ?? BANDAS_DOUGLAS[BANDAS_DOUGLAS.length - 1]!
}

export function colorOleaje(alturaM: number | null | undefined): string {
  return bandaDe(alturaM)?.color ?? COLOR_SIN_OLEAJE
}

export function nombreOleaje(alturaM: number | null | undefined): string {
  return bandaDe(alturaM)?.nombre ?? 'Sin dato del modelo'
}

/**
 * Expresión `step` de MapLibre equivalente, para que el tintado lo haga la GPU sobre
 * la propiedad `wave` de cada tramo en vez de recalcularse en JS.
 */
export function expresionColorOleaje(): unknown[] {
  const expr: unknown[] = ['step', ['get', 'wave'], BANDAS_DOUGLAS[0]!.color]
  for (const b of BANDAS_DOUGLAS) {
    if (b.hasta === Infinity) break
    expr.push(b.hasta, BANDAS_DOUGLAS[BANDAS_DOUGLAS.indexOf(b) + 1]!.color)
  }
  return expr
}
