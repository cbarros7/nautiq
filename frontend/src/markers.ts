/**
 * Marcadores HTML sobre el mapa: buque, puerto y flota de contexto.
 *
 * Se sigue el patrón de ÉNFASIS del sistema de visualización: el buque del evento
 * lleva el color de estado, y toda la flota de contexto va en gris. El contexto es
 * contexto: si compitiera en color, el buque que importa se perdería.
 *
 * Reglas que no se negocian:
 *  - La orientación es `heading`. Si llega `null` -> círculo, no triángulo: no se
 *    inventa un rumbo (el centinela 511 del AIS real hace que sea el caso normal).
 *  - El buque del evento aparece TAMBIÉN en `context_vessels.inbound` — verificado en
 *    el propio ejemplo del oráculo. Se deduplica por MMSI o se pinta dos veces.
 *  - `vessel.name` llega `null` siempre hoy, así que la etiqueta es el MMSI.
 */
import maplibregl, { type Map as MapLibreMap, type Marker } from 'maplibre-gl'
import type { OracleRecommendationV1 } from './types'
import { severidad, fiabilidad, titular, fondearaIgual, COLOR_SEVERIDAD, OPACIDAD_FIABILIDAD } from './status'
import { vigencia, opacidadPosicion, type FilaRecomendacion } from './feed'
import { etiquetaBuque, num, horaUtc, antiguedad, esperaEstimada, SIN_DATO } from './format'

export interface CapaMarcadores {
  limpiar(): void
  pintar(filas: FilaRecomendacion[], seleccionado: string | null,
         alSeleccionar: (fila: FilaRecomendacion) => void): void
}

function el(clase: string, texto?: string): HTMLElement {
  const n = document.createElement('div')
  n.className = clase
  if (texto !== undefined) n.textContent = texto
  return n
}

function marcadorBuque(
  fila: FilaRecomendacion,
  seleccionado: boolean,
  alSeleccionar: () => void,
): HTMLElement {
  const ev = fila.payload
  const sev = severidad(ev.recommendation)
  const fia = fiabilidad(ev.recommendation)

  const raiz = el('mk mk-buque' + (seleccionado ? ' mk-sel' : ''))
  raiz.style.setProperty('--c', COLOR_SEVERIDAD[sev])
  // Fiabilidad del dato x frescura del FIX (no de la decisión: ver opacidadPosicion).
  raiz.style.opacity = String(OPACIDAD_FIABILIDAD[fia] * opacidadPosicion(ev.vessel.position_at))
  raiz.setAttribute('role', 'button')
  raiz.setAttribute('tabindex', '0')

  const heading = ev.vessel.heading
  const forma = el(heading === null || heading === undefined ? 'mk-circulo' : 'mk-triangulo')
  if (heading !== null && heading !== undefined) {
    forma.style.transform = `rotate(${heading}deg)`
  }
  if (sev === 'critical') raiz.classList.add('mk-pulso')
  raiz.appendChild(forma)

  // El color de estado nunca va solo: la etiqueta lo acompaña siempre.
  const rotulo = el('mk-rotulo')
  rotulo.appendChild(el('mk-rotulo-id', etiquetaBuque(ev.vessel.mmsi, ev.vessel.name)))
  // El ancla no es decoracion: sin ella un buque que va a fondear 60 h sale en verde,
  // porque el color codifica la calidad de la RECOMENDACION, no el resultado JIT.
  const ancla = fondearaIgual(ev.recommendation) ? ' ⚓' : ''
  rotulo.appendChild(el('mk-rotulo-v',
    `${num(ev.vessel.speed_kn, 1)} → ${num(ev.recommendation.recommended_speed_kn, 1)} kn${ancla}`))
  raiz.appendChild(rotulo)

  const titulo = [
    etiquetaBuque(ev.vessel.mmsi, ev.vessel.name),
    `Destino: ${ev.vessel.destination_raw ?? SIN_DATO} (crudo del AIS)`,
    titular(ev.recommendation),
    heading === null || heading === undefined
      ? 'Sin rumbo en el AIS: se dibuja círculo, no se infiere'
      : `Rumbo ${Math.round(heading)}°`,
    `Fix a las ${horaUtc(ev.vessel.position_at)} (${antiguedad(ev.vessel.position_at)})`,
    `Decisión emitida ${antiguedad(fila.emitted_at)}`,
  ].join('\n')
  raiz.title = titulo
  raiz.setAttribute('aria-label', titulo.replace(/\n/g, '. '))

  raiz.addEventListener('click', (e) => { e.stopPropagation(); alSeleccionar() })
  raiz.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alSeleccionar() }
  })
  return raiz
}

function marcadorPuerto(ev: OracleRecommendationV1, alSeleccionar: () => void): HTMLElement {
  const p = ev.port
  const conCola = p.anchored_count > 0
  const raiz = el('mk mk-puerto' + (conCola ? ' mk-puerto-cola' : ''))
  raiz.appendChild(el('mk-puerto-anillo'))

  const rotulo = el('mk-rotulo')
  // La etiqueta es el NOMBRE: `port.locode` llega null siempre.
  rotulo.appendChild(el('mk-rotulo-id', p.name))
  rotulo.appendChild(el('mk-rotulo-v',
    `${p.berthed_count} atr · ${p.anchored_count} fond · ${p.inbound_count} cam`))
  raiz.appendChild(rotulo)

  raiz.title = [
    p.name,
    p.locode ? `LOCODE ${p.locode}` : 'Sin LOCODE: el webhook manda coordenadas, no código',
    `${p.berthed_count} amarrados · ${p.anchored_count} fondeados · ${p.inbound_count} en camino`,
    'El conteo de "en camino" incluye a este buque',
    p.snapshot_at
      ? `Contexto a las ${horaUtc(p.snapshot_at)}`
      : `Sin hora de contexto: se usa la de emisión, ${horaUtc(ev.emitted_at)}`,
  ].join('\n')
  raiz.addEventListener('click', (e) => { e.stopPropagation(); alSeleccionar() })
  return raiz
}

function marcadorContexto(
  clase: 'berthed' | 'anchored' | 'inbound',
  mmsi: string,
  esperaH: number | null | undefined,
): HTMLElement {
  const raiz = el(`mk mk-ctx mk-ctx-${clase}`)
  raiz.appendChild(el('mk-ctx-forma'))
  const nombres = { berthed: 'Amarrado', anchored: 'Fondeado', inbound: 'En camino' }
  raiz.title = [
    `${nombres[clase]} · MMSI ${mmsi}`,
    esperaH === null || esperaH === undefined
      ? 'Espera estimada: sin dato'
      : `Espera estimada ${esperaH.toFixed(1)} h (modelada, no observada)`,
  ].join('\n')
  return raiz
}

export function crearCapaMarcadores(mapa: MapLibreMap): CapaMarcadores {
  let vivos: Marker[] = []

  function limpiar() {
    vivos.forEach((m) => m.remove())
    vivos = []
  }

  function pintar(
    filas: FilaRecomendacion[],
    seleccionado: string | null,
    alSeleccionar: (fila: FilaRecomendacion) => void,
  ) {
    limpiar()
    const puertosPintados = new Set<string>()

    for (const fila of filas) {
      const ev = fila.payload
      if (vigencia(fila.emitted_at) === 'retirado') continue
      const esSel = fila.event_id === seleccionado
      const mmsiBuque = String(ev.vessel.mmsi)

      // Un solo marcador por puerto, del evento más reciente que lo mencione.
      if (!puertosPintados.has(ev.port.name)) {
        puertosPintados.add(ev.port.name)
        vivos.push(new maplibregl.Marker({
          element: marcadorPuerto(ev, () => alSeleccionar(fila)),
          anchor: 'center',
        }).setLngLat([ev.port.lon, ev.port.lat]).addTo(mapa))
      }

      // Contexto: solo del evento seleccionado. Pintarlo de todos a la vez llenaría
      // el mapa de marcas grises que compiten con lo que importa.
      if (esSel) {
        const grupos = [
          ['berthed', ev.context_vessels.berthed],
          ['anchored', ev.context_vessels.anchored],
          ['inbound', ev.context_vessels.inbound],
        ] as const
        for (const [clase, lista] of grupos) {
          for (const b of lista) {
            // El oraculo marca ya el buque del evento con `es_objetivo`; se compara el
            // MMSI solo como respaldo por si algun emisor no lo rellena.
            if (b.es_objetivo === true || String(b.mmsi) === mmsiBuque) continue
            if (b.lat === null || b.lon === null || b.lat === undefined || b.lon === undefined) continue
            vivos.push(new maplibregl.Marker({
              element: marcadorContexto(clase, String(b.mmsi), esperaEstimada(b)),
              anchor: 'center',
            }).setLngLat([b.lon, b.lat]).addTo(mapa))
          }
        }
      }

      vivos.push(new maplibregl.Marker({
        element: marcadorBuque(fila, esSel, () => alSeleccionar(fila)),
        anchor: 'center',
      }).setLngLat([ev.vessel.lon, ev.vessel.lat]).addTo(mapa))
    }
  }

  return { limpiar, pintar }
}
