import { describe, expect, it } from 'vitest'
import { antiguedad, etiquetaBuque, fechaHoraUtc, horaUtc, minutosDesde, num, pct, rumbo, SIN_DATO } from './format'

describe('num', () => {
  it('formatea con los decimales y unidad indicados', () => {
    expect(num(12.345, 1, 'kn')).toBe('12.3 kn')
    expect(num(12.345, 2)).toBe('12.35')
  })

  it('null, undefined y NaN dan SIN_DATO', () => {
    expect(num(null)).toBe(SIN_DATO)
    expect(num(undefined)).toBe(SIN_DATO)
    expect(num(NaN)).toBe(SIN_DATO)
  })
})

describe('pct', () => {
  it('antepone el signo + a los valores positivos', () => {
    expect(pct(4.2)).toBe('+4.2 %')
  })

  it('no antepone signo a los negativos', () => {
    expect(pct(-3.1)).toBe('-3.1 %')
  })

  it('null y undefined dan SIN_DATO', () => {
    expect(pct(null)).toBe(SIN_DATO)
    expect(pct(undefined)).toBe(SIN_DATO)
  })
})

describe('horaUtc / fechaHoraUtc', () => {
  it('extraen hora y fecha en UTC de un ISO', () => {
    expect(horaUtc('2026-07-28T17:13:08Z')).toBe('17:13 UTC')
    expect(fechaHoraUtc('2026-07-28T17:13:08Z')).toBe('2026-07-28 17:13 UTC')
  })

  it('ausente o invalido da SIN_DATO', () => {
    expect(horaUtc(null)).toBe(SIN_DATO)
    expect(horaUtc('no es una fecha')).toBe(SIN_DATO)
    expect(fechaHoraUtc(undefined)).toBe(SIN_DATO)
  })
})

describe('minutosDesde / antiguedad', () => {
  const ahora = Date.parse('2026-07-28T18:00:00Z')

  it('calcula minutos transcurridos', () => {
    expect(minutosDesde('2026-07-28T17:30:00Z', ahora)).toBe(30)
  })

  it('etiqueta segun la franja de antiguedad', () => {
    expect(antiguedad('2026-07-28T17:59:30Z', ahora)).toBe('ahora mismo')
    expect(antiguedad('2026-07-28T17:30:00Z', ahora)).toBe('hace 30 min')
    expect(antiguedad('2026-07-27T18:00:00Z', ahora)).toBe('hace 24.0 h')
    expect(antiguedad('2026-07-20T18:00:00Z', ahora)).toBe('hace 8 d')
  })
})

describe('etiquetaBuque', () => {
  it('usa el nombre si esta presente', () => {
    expect(etiquetaBuque(224123456, 'EVER GIVEN')).toBe('EVER GIVEN')
  })

  it('cae al MMSI si el nombre es null, vacio o solo espacios', () => {
    expect(etiquetaBuque(224123456, null)).toBe('MMSI 224123456')
    expect(etiquetaBuque(224123456, '')).toBe('MMSI 224123456')
    expect(etiquetaBuque(224123456, '   ')).toBe('MMSI 224123456')
  })
})

describe('rumbo', () => {
  it('traduce grados a punto cardinal y los redondea', () => {
    expect(rumbo(0)).toBe('N 0°')
    expect(rumbo(90)).toBe('E 90°')
    expect(rumbo(359.6)).toBe('N 360°')
  })

  it('null o undefined dan SIN_DATO', () => {
    expect(rumbo(null)).toBe(SIN_DATO)
    expect(rumbo(undefined)).toBe(SIN_DATO)
  })
})
