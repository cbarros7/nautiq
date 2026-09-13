import { describe, expect, it } from 'vitest'
import { fiabilidad, fondeo, fondearaIgual, saturacion, severidad, titular } from './status'
import type { OracleRecommendationV1 } from './types'

type Recomendacion = OracleRecommendationV1['recommendation']

function crearRecomendacion(overrides: Partial<Recomendacion> = {}): Recomendacion {
  return {
    recommended_speed_kn: 12,
    design_speed_kn: 21,
    speed_delta_kn: -2,
    estimated_transit_hours: 10,
    eta_current: '2026-07-28T20:00:00Z',
    eta_optimized: '2026-07-28T22:00:00Z',
    idle_hours_avoided: 4,
    fuel_saved_t: 3.5,
    rationale: 'texto de ejemplo',
    convergio: true,
    excede_v_diseno: false,
    alerta_cii: false,
    nota: null,
    cii: { inicial: 3.1, jit: 2.9, metodo: 'eexi', ahorro_pct: 6.4 },
    weather_speed_loss_pct: 1.2,
    ...overrides,
  }
}

describe('severidad', () => {
  it('critical cuando excede la velocidad de diseno, por encima de todo lo demas', () => {
    const r = crearRecomendacion({ excede_v_diseno: true, alerta_cii: true })
    expect(severidad(r)).toBe('critical')
  })

  it('alert cuando el CII empeora sin exceder diseno', () => {
    const r = crearRecomendacion({ alerta_cii: true })
    expect(severidad(r)).toBe('alert')
  })

  it('ok en el caso bueno del JIT', () => {
    const r = crearRecomendacion()
    expect(severidad(r)).toBe('ok')
  })
})

describe('fiabilidad', () => {
  it('baja cuando el CII viene de fallback_admiralty', () => {
    const r = crearRecomendacion({ cii: { inicial: 3, jit: 2.8, metodo: 'fallback_admiralty', ahorro_pct: 5 } })
    expect(fiabilidad(r)).toBe('baja')
  })

  it('alta cuando hay fuel_saved_t real', () => {
    const r = crearRecomendacion({ fuel_saved_t: 1.2 })
    expect(fiabilidad(r)).toBe('alta')
  })

  it('media cuando no hay fuel_saved_t ni es fallback', () => {
    const r = crearRecomendacion({ fuel_saved_t: null })
    expect(fiabilidad(r)).toBe('media')
  })
})

describe('saturacion', () => {
  it('ninguna cuando convergio', () => {
    expect(saturacion(crearRecomendacion({ convergio: true }))).toBe('ninguna')
  })

  it('frenando-al-minimo cuando no convergio y el delta es negativo', () => {
    const r = crearRecomendacion({ convergio: false, speed_delta_kn: -5 })
    expect(saturacion(r)).toBe('frenando-al-minimo')
  })

  it('a-maxima-velocidad cuando no convergio y el delta es positivo', () => {
    const r = crearRecomendacion({ convergio: false, speed_delta_kn: 3 })
    expect(saturacion(r)).toBe('a-maxima-velocidad')
  })
})

describe('titular', () => {
  it('prioriza excede_v_diseno sobre el resto', () => {
    const r = crearRecomendacion({ excede_v_diseno: true, convergio: false, speed_delta_kn: -1, alerta_cii: true })
    expect(titular(r)).toBe('Necesita más velocidad de la de diseño')
  })

  it('fondeara igual cuando esta frenando al minimo', () => {
    const r = crearRecomendacion({ convergio: false, speed_delta_kn: -1 })
    expect(titular(r)).toBe('Fondeará igual: solo recorta el consumo')
    expect(fondearaIgual(r)).toBe(true)
  })

  it('avisa de mas emisiones cuando alerta_cii y no esta saturado', () => {
    const r = crearRecomendacion({ alerta_cii: true })
    expect(titular(r)).toBe('Llega a tiempo, emitiendo más')
  })

  it('caso bueno: llega a tiempo emitiendo menos', () => {
    const r = crearRecomendacion()
    expect(titular(r)).toBe('Llega a tiempo emitiendo menos')
    expect(fondearaIgual(r)).toBe(false)
  })
})

describe('fondeo', () => {
  function crearEvento(overrides: {
    estimated_wait_hours?: number | null
    idle_hours_avoided?: number | null
    estimated_transit_hours?: number | null
  }): OracleRecommendationV1 {
    const espera = 'estimated_wait_hours' in overrides ? overrides.estimated_wait_hours! : 20
    const idle = 'idle_hours_avoided' in overrides ? overrides.idle_hours_avoided! : 8
    const transito = 'estimated_transit_hours' in overrides ? overrides.estimated_transit_hours : 12
    return {
      queue: { estimated_wait_hours: espera, queue_position: 1, berth_segment: 'large' },
      recommendation: crearRecomendacion({
        idle_hours_avoided: idle,
        estimated_transit_hours: transito,
      }),
    } as unknown as OracleRecommendationV1
  }

  it('calcula fondeo con recomendacion y lo evitado', () => {
    const ev = crearEvento({ estimated_wait_hours: 20, idle_hours_avoided: 8, estimated_transit_hours: 12 })
    expect(fondeo(ev)).toEqual({ sinCambios: 8, conRecomendacion: 8, evitado: 0 })
  })

  it('nunca da conRecomendacion negativo (se recorta a 0)', () => {
    const ev = crearEvento({ estimated_wait_hours: 5, idle_hours_avoided: 3, estimated_transit_hours: 12 })
    expect(fondeo(ev).conRecomendacion).toBe(0)
  })

  it('todo null si falta alguna pieza', () => {
    const ev = crearEvento({ estimated_transit_hours: null })
    expect(fondeo(ev)).toEqual({ sinCambios: 8, conRecomendacion: null, evitado: null })
  })
})
