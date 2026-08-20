/**
 * Formato de valores para pantalla. Un único sitio decide cómo se ve un `null`, porque
 * el contrato tiene campos que hoy son `null` SIEMPRE (`vessel.name`, `port.locode`,
 * `context_radius_nm`, `snapshot_at`) y otros que lo son a menudo (`fuel_saved_t`,
 * `heading`, `eta_current`). "Sin dato" es un estado de primera clase, no un hueco.
 */
export const SIN_DATO = '—'

export function num(v: number | null | undefined, decimales = 1, unidad = ''): string {
  if (v === null || v === undefined || Number.isNaN(v)) return SIN_DATO
  return `${v.toFixed(decimales)}${unidad ? ' ' + unidad : ''}`
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return SIN_DATO
  return `${v > 0 ? '+' : ''}${v.toFixed(1)} %`
}

export function horaUtc(iso: string | null | undefined): string {
  if (!iso) return SIN_DATO
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return SIN_DATO
  return d.toISOString().slice(11, 16) + ' UTC'
}

export function fechaHoraUtc(iso: string | null | undefined): string {
  if (!iso) return SIN_DATO
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return SIN_DATO
  return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
}

/** Antigüedad en minutos, para las reglas de caducidad de marcadores. */
export function minutosDesde(iso: string, ahora = Date.now()): number {
  return (ahora - new Date(iso).getTime()) / 60000
}

export function antiguedad(iso: string, ahora = Date.now()): string {
  const m = minutosDesde(iso, ahora)
  if (m < 1) return 'ahora mismo'
  if (m < 60) return `hace ${Math.round(m)} min`
  const h = m / 60
  if (h < 48) return `hace ${h.toFixed(1)} h`
  return `hace ${Math.round(h / 24)} d`
}

/**
 * Etiqueta de un buque. `vessel.name` llega `null` siempre hoy (TODO 2 del equipo del
 * oráculo), así que el MMSI es la identidad de facto. Cuando el nombre aterrice, esta
 * función es el único sitio que cambia.
 */
export function etiquetaBuque(mmsi: number | string, nombre?: string | null): string {
  return nombre?.trim() ? nombre : `MMSI ${mmsi}`
}

/** Grados a rosa de los vientos, para direcciones de ola y viento. */
export function rumbo(grados: number | null | undefined): string {
  if (grados === null || grados === undefined) return SIN_DATO
  const puntos = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO']
  return `${puntos[Math.round(((grados % 360) / 22.5)) % 16]} ${Math.round(grados)}°`
}

/**
 * Espera estimada de un buque del contexto. `berthed` no la lleva y `anchored`/`inbound`
 * la declaran opcional, así que el acceso va por aquí en vez de repartir comprobaciones
 * de `in` por los componentes —- que además no estrechan bien la unión.
 *
 * Es un valor MODELADO por jit_calculus, no observado: quien lo pinte tiene que rotularlo.
 */
export function esperaEstimada(b: unknown): number | null {
  const v = (b as { estimated_wait_hours?: unknown } | null)?.estimated_wait_hours
  return typeof v === 'number' ? v : null
}
