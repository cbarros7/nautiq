/**
 * El mapa: MapLibre GL sobre teselas VECTORIALES libres, sin clave de API.
 *
 * Por qué se abandonó CARTO: sus basemaps ráster siguen respondiendo 200 sin clave, pero
 * desde hace poco devuelven la tesela con una marca de agua «API KEY REQUIRED ·
 * carto.com/basemaps/apikey» incrustada. Se ve en pantalla y contradice la premisa del
 * plan («sin token, sin licencia propietaria»).
 *
 * OpenFreeMap sirve teselas vectoriales OpenMapTiles sin clave y con glifos propios. Al ser
 * vectorial se elige el color exacto de cada capa —- que es lo que pedía el feedback: la
 * escala de negros no contrastaba— y además hay etiquetas de verdad, que con un estilo
 * ráster eran imposibles sin un servidor de fuentes.
 */
import maplibregl, { type Map as MapLibreMap, type StyleSpecification } from 'maplibre-gl'

export const CENTRO_MEDITERRANEO: [number, number] = [1.5, 38.5]

/** Por debajo de este zoom, las etiquetas de buque no caben sin pisarse. */
export const ZOOM_ETIQUETAS = 6

/**
 * Paleta del mapa. Tierra claramente más clara que el mar: es lo que separa la costa de un
 * vistazo y lo que hace que la ruta naranja y los colores de estado salten. Los tonos son
 * fríos para que el único color cálido de la pantalla sea dato (oleaje y estado).
 */
export const MAPA = {
  tierra: '#242c32',
  mar: '#041b2d',
  linea: '#38454d',
  texto: '#8698a3',
}

const ESTILO_BASE = 'https://tiles.openfreemap.org/styles/positron'
const ATRIB =
  '<a href="https://openfreemap.org">OpenFreeMap</a> · ' +
  '<a href="https://www.openmaptiles.org/">OpenMapTiles</a> · ' +
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const ATRIB_OSEAM = '&copy; <a href="https://www.openseamap.org/">OpenSeaMap</a>'

/** Capas de ciudad que a escala de Mediterráneo son ruido y tapan el mar. */
const CAPAS_MUDAS = new Set([
  'building', 'landuse_residential', 'landcover_wood', 'park',
  'aeroway-area', 'aeroway-runway', 'aeroway-taxiway', 'aeroway-runway-casing',
  'road_area_pier', 'road_pier', 'highway_path', 'highway_minor',
  'highway_major_casing', 'highway_major_inner', 'highway_major_subtle',
  'highway_motorway_casing', 'highway_motorway_inner', 'highway_motorway_subtle',
  'railway_transit', 'tunnel_motorway_casing', 'tunnel_motorway_inner',
])

function capaSeamark() {
  return {
    fuente: {
      type: 'raster' as const,
      tiles: ['https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 18,
      attribution: ATRIB_OSEAM,
    },
    capa: {
      id: 'seamark',
      type: 'raster' as const,
      source: 'seamark',
      // Apagada por defecto: a poco zoom es ruido, y ahí arranca la vista general.
      layout: { visibility: 'none' as const },
      paint: { 'raster-opacity': 0.85 },
    },
  }
}

/** Estilo mínimo por si OpenFreeMap no responde: mar liso, sin costa. */
function estiloDeRespaldo(): StyleSpecification {
  const sm = capaSeamark()
  return {
    version: 8,
    glyphs: undefined,
    sources: { seamark: sm.fuente },
    layers: [
      { id: 'fondo', type: 'background', paint: { 'background-color': MAPA.mar } },
      sm.capa,
    ],
  } as unknown as StyleSpecification
}

/**
 * Trae el estilo de OpenFreeMap y lo repinta con nuestra paleta. Se hace ANTES de crear el
 * mapa, no con `setPaintProperty` después, para no enseñar un fogonazo del estilo claro
 * original —- y porque `setStyle` a posteriori se llevaría por delante las capas de ruta.
 */
export async function estiloNautico(): Promise<StyleSpecification> {
  let base: StyleSpecification
  try {
    const r = await fetch(ESTILO_BASE)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    base = (await r.json()) as StyleSpecification
  } catch {
    // Sin costa el mapa sigue siendo utilizable: buques, ruta y puertos están en
    // GeoJSON propio. Peor mapa, no aplicación rota.
    return estiloDeRespaldo()
  }

  const s = JSON.parse(JSON.stringify(base)) as StyleSpecification
  s.layers = s.layers.filter(
    // `ne2_shaded` es el relieve de Natural Earth: a poco zoom pinta África más oscura
    // que Europa y rompe la lectura tierra/mar.
    (l) => !CAPAS_MUDAS.has(l.id) && (l as { source?: string }).source !== 'ne2_shaded',
  )
  for (const l of s.layers) {
    const p = (l as { paint?: Record<string, unknown> }).paint ?? {}
    if (l.type === 'background') (l as { paint: unknown }).paint = { 'background-color': MAPA.tierra }
    else if (l.id === 'water') (l as { paint: unknown }).paint = { ...p, 'fill-color': MAPA.mar }
    else if (l.id === 'waterway') (l as { paint: unknown }).paint = { ...p, 'line-color': MAPA.mar }
    else if (l.type === 'fill') (l as { paint: unknown }).paint = { ...p, 'fill-color': MAPA.tierra }
    else if (l.type === 'line') (l as { paint: unknown }).paint = { ...p, 'line-color': MAPA.linea }
    else if (l.type === 'symbol')
      (l as { paint: unknown }).paint = {
        ...p, 'text-color': MAPA.texto,
        'text-halo-color': MAPA.tierra, 'text-halo-width': 1.2,
      }
  }
  const sm = capaSeamark()
  ;(s.sources as Record<string, unknown>).seamark = sm.fuente
  s.layers.push(sm.capa as never)
  for (const f of Object.values(s.sources as Record<string, { attribution?: string }>)) {
    if (f && typeof f === 'object' && !f.attribution) f.attribution = ATRIB
  }
  return s
}

export async function crearMapa(contenedor: HTMLElement): Promise<MapLibreMap> {
  const mapa = new maplibregl.Map({
    container: contenedor,
    center: CENTRO_MEDITERRANEO,
    zoom: 5.4,
    minZoom: 3,
    maxZoom: 12,
    attributionControl: false,
    style: await estiloNautico(),
  })

  mapa.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
  mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
  // Abajo a la derecha y no a la izquierda: ahí vive la leyenda y la tapaba.
  mapa.addControl(new maplibregl.ScaleControl({ unit: 'nautical' }), 'bottom-right')

  /*
   * A poco zoom las etiquetas de buques cercanos se pisan (dos buques a 30 nm son píxeles
   * vecinos a zoom 5). Por debajo de ZOOM_ETIQUETAS se dejan solo las marcas y la identidad
   * la lleva la lista de avisos, que está al lado; el buque seleccionado conserva la suya.
   * Se conmuta una clase en el contenedor en vez de repintar marcadores en cada rueda.
   */
  const aplicarZoom = () =>
    contenedor.classList.toggle('zoom-bajo', mapa.getZoom() < ZOOM_ETIQUETAS)
  mapa.on('zoom', aplicarZoom)
  aplicarZoom()

  return mapa
}

/**
 * MapLibre mide el contenedor UNA vez, al construirse. Si en ese instante el CSS todavía no
 * le ha dado altura —- lo que pasa en desarrollo, donde los estilos se inyectan por JS— se
 * queda con su fallback de 300 px y no vuelve a mirar: el cambio viene del CSS, no de un
 * `resize` de ventana, así que nada le avisa.
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

/**
 * Encuadra una ruta dejando libre la parte de mapa que NO tapa la interfaz.
 *
 * El margen se pasa desde fuera porque cambia con la disposicion: en escritorio el panel
 * ocupa una franja a la derecha, y en movil es una hoja que ocupa la parte de ABAJO. Antes
 * se reservaban siempre 430 px a la derecha, asi que en un telefono la ruta se encuadraba
 * contra un panel que no estaba ahi y acababa debajo del que si estaba.
 */
export function encuadrarRuta(
  mapa: MapLibreMap,
  waypoints: number[][],
  margen: { top?: number; bottom?: number; left?: number; right?: number },
): void {
  if (waypoints.length < 2) return
  const lons = waypoints.map((w) => w[0]!)
  const lats = waypoints.map((w) => w[1]!)
  mapa.fitBounds(
    [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
    {
      padding: {
        top: 70 + (margen.top ?? 0),
        bottom: 70 + (margen.bottom ?? 0),
        left: 70 + (margen.left ?? 0),
        right: 70 + (margen.right ?? 0),
      },
      duration: 700,
      maxZoom: 9,
    },
  )
}
