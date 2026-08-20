/**
 * El mapa: MapLibre GL sobre teselas libres, sin token ni licencia propietaria.
 *
 * Dos decisiones que conviene tener escritas:
 *
 * 1. Estilo ráster definido en línea, no un `style.json` remoto. Así no hay servicio
 *    de estilos del que depender y las atribuciones quedan en el código.
 * 2. Ni una capa `text-field`. Un estilo ráster no trae glifos, así que cualquier
 *    etiqueta exigiría un servidor de fuentes externo. Las etiquetas y los buques son
 *    marcadores HTML: sin dependencia extra, y con eventos de DOM de serie.
 */
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'

export const CENTRO_MEDITERRANEO: [number, number] = [1.5, 38.5]

/** Por debajo de este zoom, las etiquetas de buque no caben sin pisarse. */
export const ZOOM_ETIQUETAS = 6

const ATRIB_CARTO =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>'
const ATRIB_OSEAM =
  '&copy; <a href="https://www.openseamap.org/">OpenSeaMap</a>'

export function crearMapa(contenedor: HTMLElement): MapLibreMap {
  const mapa = new maplibregl.Map({
    container: contenedor,
    center: CENTRO_MEDITERRANEO,
    zoom: 5.4,
    minZoom: 3,
    maxZoom: 12,
    attributionControl: false,
    style: {
      version: 8,
      sources: {
        carto: {
          type: 'raster',
          tiles: ['https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
                  'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
                  'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
          tileSize: 256,
          attribution: ATRIB_CARTO,
        },
        seamark: {
          type: 'raster',
          tiles: ['https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'],
          tileSize: 256,
          maxzoom: 18,
          attribution: ATRIB_OSEAM,
        },
      },
      layers: [
        { id: 'fondo', type: 'background', paint: { 'background-color': '#0d0d0d' } },
        { id: 'carto', type: 'raster', source: 'carto' },
        // Superposición náutica: balizamiento, boyas, luces. Apagada por defecto —
        // a poco zoom aporta ruido, y es donde arranca la vista general.
        { id: 'seamark', type: 'raster', source: 'seamark',
          layout: { visibility: 'none' }, paint: { 'raster-opacity': 0.85 } },
      ],
    },
  })

  mapa.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
  mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
  // Abajo a la derecha y no a la izquierda: ahi vive la leyenda y la tapaba.
  mapa.addControl(new maplibregl.ScaleControl({ unit: 'nautical' }), 'bottom-right')

  /*
   * A poco zoom las etiquetas de buques cercanos se pisan (dos buques a 30 nm son
   * pixeles vecinos a zoom 5). Por debajo de ZOOM_ETIQUETAS se dejan solo las marcas y
   * la identidad la lleva la lista de avisos, que esta al lado; el buque seleccionado
   * conserva su etiqueta siempre. Se conmuta una clase en el contenedor en vez de
   * repintar marcadores en cada rueda de raton.
   */
  const aplicarZoom = () => {
    contenedor.classList.toggle('zoom-bajo', mapa.getZoom() < ZOOM_ETIQUETAS)
  }
  mapa.on('zoom', aplicarZoom)
  aplicarZoom()

  return mapa
}

/**
 * MapLibre mide el contenedor UNA vez, al construirse. Si en ese instante el CSS
 * todavía no le ha dado altura —- que es lo que pasa en desarrollo, donde los estilos se
 * inyectan por JS—- se queda con su fallback de 300 px y no vuelve a mirar: el cambio de
 * tamaño viene del CSS, no de un `resize` de ventana, así que nada le avisa.
 *
 * Un `ResizeObserver` sobre el contenedor lo cubre, y de paso resuelve el panel lateral
 * abriéndose y el móvil girando.
 */
export function observarTamano(mapa: MapLibreMap, contenedor: HTMLElement): () => void {
  mapa.resize()
  const obs = new ResizeObserver(() => mapa.resize())
  obs.observe(contenedor)
  return () => obs.disconnect()
}

export function alternarSeamark(mapa: MapLibreMap, visible: boolean): void {
  if (mapa.getLayer('seamark')) {
    mapa.setLayoutProperty('seamark', 'visibility', visible ? 'visible' : 'none')
  }
}

/** Encuadra una ruta dejando sitio al panel lateral. */
export function encuadrarRuta(mapa: MapLibreMap, waypoints: number[][], anchoPanel: number): void {
  if (waypoints.length < 2) return
  const lons = waypoints.map((w) => w[0]!)
  const lats = waypoints.map((w) => w[1]!)
  mapa.fitBounds(
    [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
    { padding: { top: 70, bottom: 70, left: 70, right: anchoPanel + 70 }, duration: 700, maxZoom: 9 },
  )
}
