/**
 * La ruta navegable, teñida por el estado del mar. Es el elemento visual principal
 * del frontal, y sale de dos cosas que el oráculo ya calcula: `route.waypoints`
 * (searoute, esquiva tierra) y `route_weather` (Open-Meteo en el ETA de cada
 * waypoint). Ningún cálculo nuevo.
 *
 * Un tramo por par de waypoints, con la altura de ola del waypoint de SALIDA como
 * propiedad, y el color resuelto por una expresión `step` en la GPU. Se dibuja
 * discontinua porque es una ruta PREVISTA, no la derrota observada: animar o
 * suavizar aquí sería inventar datos.
 */
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { OracleRecommendationV1 } from './types'
import { expresionColorOleaje } from './douglas'

export const FUENTE_RUTA = 'ruta'
export const CAPA_RUTA_HALO = 'ruta-halo'
export const CAPA_RUTA = 'ruta-linea'
export const CAPA_WAYPOINTS = 'ruta-waypoints'

type FC = GeoJSON.FeatureCollection<GeoJSON.Geometry, Record<string, unknown>>
const VACIO: FC = { type: 'FeatureCollection', features: [] }

/**
 * Tramos + waypoints de un evento. `route_weather` tiene, por contrato, la misma
 * longitud y el mismo orden que `route.waypoints`; si algún día dejara de cumplirse,
 * el tramo se queda sin `wave` y se pinta en el gris de "sin dato" en vez de mentir.
 */
export function rutaAGeoJSON(ev: OracleRecommendationV1): FC {
  const wp = ev.route.waypoints
  const meteo = ev.route_weather
  const features: FC['features'] = []

  for (let i = 0; i < wp.length - 1; i++) {
    const a = wp[i]!
    const b = wp[i + 1]!
    const m = meteo[i]
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[a[0]!, a[1]!], [b[0]!, b[1]!]] },
      properties: {
        clase: 'tramo',
        // -1 marca "sin dato del modelo": queda por debajo del primer corte Douglas
        // y la expresion `step` lo lleva al gris apagado.
        wave: m?.wave_height ?? -1,
        indice: i,
      },
    })
  }

  meteo.forEach((m, i) => {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [m.lon, m.lat] },
      properties: {
        clase: 'waypoint',
        indice: i,
        wave: m.wave_height ?? -1,
        wave_height: m.wave_height ?? null,
        wave_period: m.wave_period ?? null,
        wave_direction: m.wave_direction ?? null,
        wind_speed_kn: m.wind_speed_kn ?? null,
        wind_direction: m.wind_direction ?? null,
        wind_gusts_kn: m.wind_gusts_kn ?? null,
        eta: m.eta,
      },
    })
  })

  return { type: 'FeatureCollection', features }
}

export function montarCapasRuta(mapa: MapLibreMap): void {
  if (mapa.getSource(FUENTE_RUTA)) return
  mapa.addSource(FUENTE_RUTA, { type: 'geojson', data: VACIO })

  // Halo oscuro debajo: separa la linea del mar sin robarle saturacion al dato.
  mapa.addLayer({
    id: CAPA_RUTA_HALO,
    type: 'line',
    source: FUENTE_RUTA,
    filter: ['==', ['get', 'clase'], 'tramo'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#0d0d0d', 'line-width': 6, 'line-opacity': 0.65 },
  })

  mapa.addLayer({
    id: CAPA_RUTA,
    type: 'line',
    source: FUENTE_RUTA,
    filter: ['==', ['get', 'clase'], 'tramo'],
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: {
      'line-color': expresionColorOleaje() as never,
      'line-width': 2.6,
      'line-dasharray': [2.4, 1.6],
    },
  })

  mapa.addLayer({
    id: CAPA_WAYPOINTS,
    type: 'circle',
    source: FUENTE_RUTA,
    filter: ['==', ['get', 'clase'], 'waypoint'],
    paint: {
      'circle-radius': 4.5,
      'circle-color': expresionColorOleaje() as never,
      // Anillo de 2px del color de la superficie: separa marcas que se solapan.
      'circle-stroke-width': 2,
      'circle-stroke-color': '#0d0d0d',
    },
  })
}

export function pintarRuta(mapa: MapLibreMap, ev: OracleRecommendationV1 | null): void {
  const fuente = mapa.getSource(FUENTE_RUTA)
  if (!fuente || !('setData' in fuente)) return
  ;(fuente as maplibregl.GeoJSONSource).setData(ev ? rutaAGeoJSON(ev) : VACIO)
}
