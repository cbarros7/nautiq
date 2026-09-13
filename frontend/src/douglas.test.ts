import { describe, expect, it } from 'vitest'
import { BANDAS_DOUGLAS, COLOR_SIN_OLEAJE, colorOleaje, expresionColorOleaje, nombreOleaje } from './douglas'

describe('colorOleaje / nombreOleaje', () => {
  it('clasifica cada altura en la banda Douglas correcta', () => {
    expect(nombreOleaje(0.05)).toBe('Mar en calma')
    expect(nombreOleaje(0.3)).toBe('Rizada')
    expect(nombreOleaje(1.0)).toBe('Marejada')
    expect(nombreOleaje(2.0)).toBe('Fuerte marejada')
    expect(nombreOleaje(5.0)).toBe('Gruesa o más')
  })

  it('devuelve el color de la banda correspondiente', () => {
    expect(colorOleaje(0.05)).toBe(BANDAS_DOUGLAS[0]!.color)
    expect(colorOleaje(5.0)).toBe(BANDAS_DOUGLAS[4]!.color)
  })

  it('sin cobertura del modelo cae al gris apagado', () => {
    expect(colorOleaje(null)).toBe(COLOR_SIN_OLEAJE)
    expect(colorOleaje(undefined)).toBe(COLOR_SIN_OLEAJE)
    expect(nombreOleaje(null)).toBe('Sin dato del modelo')
  })

  it('los limites de banda son exclusivos por arriba (< no <=)', () => {
    expect(nombreOleaje(0.1)).toBe('Rizada')
    expect(nombreOleaje(0.5)).toBe('Marejada')
  })
})

describe('expresionColorOleaje', () => {
  it('genera una expresion step de MapLibre con un color por banda', () => {
    const expr = expresionColorOleaje()
    expect(expr[0]).toBe('step')
    expect(expr[1]).toEqual(['get', 'wave'])
    // color base + (limite, color) por cada banda salvo la ultima (Infinity)
    expect(expr.length).toBe(2 + 1 + (BANDAS_DOUGLAS.length - 1) * 2)
  })
})
