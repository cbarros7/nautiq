/**
 * El feed: lee `oracle_recommendations` y nada más.
 *
 * El frontal no conoce al oráculo, ni su URL, ni su ciclo de despliegue. Lee una tabla.
 * Quien escribe la fila es intercambiable —- hoy el oráculo tras el webhook de Flink,
 * antes un fixture— y el frontal no cambia.
 *
 * No se usa Supabase Realtime: el oráculo emite una vez cada 30 min por buque en
 * aproximación, así que 30 s de repesca son ruido frente a la cadencia de la fuente, y
 * evitan tener que habilitar replicación en la tabla. El salto a `.on('INSERT')` sería
 * sustituir `arrancarRepesca` y nada más.
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { OracleRecommendationV1 } from './types'
import { TABLA } from './entorno'

/** Una fila de la tabla. Las cuatro columnas promovidas + el evento en `payload`. */
export interface FilaRecomendacion {
  event_id: string
  session_id: string
  emitted_at: string
  mmsi: string
  puerto: string
  alerta_cii: boolean
  payload: OracleRecommendationV1
}

export const LIMITE_ARRANQUE = 50
export const INTERVALO_REPESCA_MS = 30_000

/**
 * El fixture es el defecto cuando no hay credenciales: un clon recién hecho arranca con
 * `npm run dev` y ve la demo, sin configurar nada. En producción el workflow inyecta las
 * `VITE_*` y entonces se lee la tabla. `VITE_USE_MOCK` fuerza el fixture aunque haya
 * credenciales, para desarrollar sin red.
 */
const HAY_CREDENCIALES = Boolean(
  import.meta.env.VITE_SUPABASE_URL && import.meta.env.VITE_SUPABASE_ANON_KEY,
)
export const USANDO_MOCK =
  import.meta.env.VITE_USE_MOCK === 'true' || !HAY_CREDENCIALES

let cliente: SupabaseClient | null = null
function sb(): SupabaseClient {
  if (!cliente) {
    const url = import.meta.env.VITE_SUPABASE_URL
    const key = import.meta.env.VITE_SUPABASE_ANON_KEY
    if (!url || !key) {
      throw new Error(
        'Faltan VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY. ' +
        'Con VITE_USE_MOCK=true el frontal arranca sin ellas, leyendo src/mock/events.json.',
      )
    }
    cliente = createClient(url, key, { auth: { persistSession: false } })
  }
  return cliente
}

/**
 * El fixture trae horas fijas del momento en que se grabó, así que en modo mock se
 * desplazan en bloque para que el evento más reciente quede "ahora". Sin esto las reglas
 * de caducidad (§ `vigencia`) retirarían los 11 eventos al instante y el mapa saldría
 * vacío. Solo ocurre en modo mock, y la interfaz lo anuncia con un banner: los
 * desplazamientos RELATIVOS entre eventos se conservan intactos.
 */
function rebasarFixture(filas: FilaRecomendacion[]): FilaRecomendacion[] {
  if (filas.length === 0) return filas
  const masReciente = Math.max(...filas.map((f) => new Date(f.emitted_at).getTime()))
  const desplazamiento = Date.now() - masReciente
  return filas.map((f) => {
    const emitted = new Date(new Date(f.emitted_at).getTime() + desplazamiento).toISOString()
    const posOrig = new Date(f.payload.vessel.position_at).getTime()
    return {
      ...f,
      emitted_at: emitted,
      payload: {
        ...f.payload,
        emitted_at: emitted,
        vessel: {
          ...f.payload.vessel,
          position_at: new Date(posOrig + desplazamiento).toISOString(),
        },
      },
    }
  })
}

async function cargarMock(): Promise<FilaRecomendacion[]> {
  const mod = await import('./mock/events.json')
  return rebasarFixture(mod.default as unknown as FilaRecomendacion[])
}

/** Cuántos eventos trae el fixture, para el banner. Contado, no escrito a mano. */
export async function totalMock(): Promise<number> {
  return (await import('./mock/events.json')).default.length
}

/** Arranque en frío: las últimas N decisiones. Resuelve el mapa vacío al abrir. */
export async function cargarInicial(): Promise<FilaRecomendacion[]> {
  if (USANDO_MOCK) return cargarMock()
  const { data, error } = await sb()
    .from(TABLA).select('*')
    .order('emitted_at', { ascending: false })
    .limit(LIMITE_ARRANQUE)
  if (error) throw new Error(`No se pudo leer ${TABLA}: ${error.message}`)
  return (data ?? []) as FilaRecomendacion[]
}

/** Repesca incremental: solo lo posterior a lo ya visto. */
export async function cargarDesde(ultimoVisto: string): Promise<FilaRecomendacion[]> {
  if (USANDO_MOCK) return []
  const { data, error } = await sb()
    .from(TABLA).select('*')
    .gt('emitted_at', ultimoVisto)
    .order('emitted_at', { ascending: true })
  if (error) throw new Error(`No se pudo repescar ${TABLA}: ${error.message}`)
  return (data ?? []) as FilaRecomendacion[]
}

/**
 * Una aproximación completa. Con un aviso cada 30 min durante hasta 12 h, una sesión
 * puede tener ~24 eventos: es lo que permite ver cómo evolucionó la recomendación en
 * vez de una foto suelta.
 */
export async function cargarSesion(sessionId: string): Promise<FilaRecomendacion[]> {
  if (USANDO_MOCK) {
    const todas = await cargarMock()
    return todas
      .filter((f) => f.session_id === sessionId)
      .sort((a, b) => a.emitted_at.localeCompare(b.emitted_at))
  }
  const { data, error } = await sb()
    .from(TABLA).select('*')
    .eq('session_id', sessionId)
    .order('emitted_at', { ascending: true })
  if (error) throw new Error(`No se pudo leer la sesión ${sessionId}: ${error.message}`)
  return (data ?? []) as FilaRecomendacion[]
}

export function arrancarRepesca(
  obtenerUltimoVisto: () => string | null,
  alLlegar: (filas: FilaRecomendacion[]) => void,
  alFallar: (e: Error) => void,
  /** Se llama tras CADA ciclo con éxito, traiga filas o no: es lo que permite a la
   *  interfaz demostrar que sigue leyendo, en vez de anunciar una cadencia teórica. */
  alRefrescar?: () => void,
): () => void {
  if (USANDO_MOCK) return () => {}
  const id = setInterval(async () => {
    const desde = obtenerUltimoVisto()
    if (!desde) return
    try {
      const filas = await cargarDesde(desde)
      alRefrescar?.()
      if (filas.length) alLlegar(filas)
    } catch (e) {
      alFallar(e as Error)
    }
  }, INTERVALO_REPESCA_MS)
  return () => clearInterval(id)
}

// --------------------------------------------------------------------------- vigencia

export type Vigencia = 'fresco' | 'atenuado' | 'retirado'

/**
 * Cuanto tiempo sigue un aviso en pantalla. Es una constante y no un numero suelto porque
 * el texto de "ningun aviso en las ultimas N h" tiene que decir lo mismo que la regla: si
 * se tocan por separado, la interfaz miente sobre su propio comportamiento.
 */
export const VENTANA_AVISOS_H = 5

/**
 * Caducidad de marcadores, calibrada a la cadencia real de 30 min del oráculo:
 *
 *   < 40 min      fresco     un ciclo más margen de jitter
 *  40 min-5 h     atenuado   se han perdido ciclos: hueco, o fin de la aproximación
 *   > 5 h         retirado   la aproximación terminó (el buque salió de la ventana de <12 h)
 *
 * Un marcador retirado desaparece del mapa pero su sesión sigue consultable.
 */
export function vigencia(emittedAt: string, ahora = Date.now()): Vigencia {
  const minutos = (ahora - new Date(emittedAt).getTime()) / 60000
  if (minutos < 40) return 'fresco'
  if (minutos < VENTANA_AVISOS_H * 60) return 'atenuado'
  return 'retirado'
}

export const OPACIDAD_VIGENCIA: Record<Vigencia, number> = {
  fresco: 1,
  atenuado: 0.45,
  retirado: 0,
}


/**
 * El último evento de cada buque. La clave es el MMSI **normalizado a string**: en el
 * payload `vessel.mmsi` es un número, en la columna es `text`, y en `context_vessels`
 * llega tal cual venga de Flink. Sin normalizar, los cruces fallan en silencio.
 */
export function porBuque(filas: FilaRecomendacion[]): Map<string, FilaRecomendacion> {
  const m = new Map<string, FilaRecomendacion>()
  for (const f of filas) {
    const clave = String(f.payload.vessel.mmsi)
    const previo = m.get(clave)
    if (!previo || f.emitted_at > previo.emitted_at) m.set(clave, f)
  }
  return m
}
