/**
 * La evolución de una aproximación.
 *
 * Es la mejor consecuencia de `session_id`: el oráculo emite cada 30 min mientras el
 * buque está a menos de 12 h del puerto, así que una aproximación deja hasta ~24
 * eventos en la tabla. Enseñarlos demuestra que el sistema REACCIONA —- la cola cambia,
 * la recomendación cambia—- en vez de opinar una vez.
 *
 * Dos múltiplos pequeños y no un gráfico con dos ejes: nudos y por ciento son escalas
 * distintas.
 */
import { LineChart, type Punto } from './chart'
import type { FilaRecomendacion } from './feed'
import { horaUtc, num } from './format'
import { saturacion, ETIQUETA_SATURACION } from './status'

export function PanelSesion({ eventos }: { eventos: FilaRecomendacion[] }) {
  if (eventos.length < 2) {
    return (
      <section className="bloque">
        <h3 className="bloque-titulo">Evolución de la aproximación</h3>
        <p className="nota-vacia">Primer aviso de esta aproximación.</p>
      </section>
    )
  }

  const t0 = new Date(eventos[0]!.emitted_at).getTime()
  const minutos = (f: FilaRecomendacion) => (new Date(f.emitted_at).getTime() - t0) / 60000

  const velocidad: Punto[] = eventos.map((f) => ({
    x: minutos(f),
    y: f.payload.recommendation.recommended_speed_kn,
    etiqueta: horaUtc(f.emitted_at),
  }))
  const cii: Punto[] = eventos.map((f) => ({
    x: minutos(f),
    y: f.payload.recommendation.cii.ahorro_pct,
    etiqueta: horaUtc(f.emitted_at),
  }))

  const primera = eventos[0]!.payload.recommendation
  const ultima = eventos[eventos.length - 1]!.payload.recommendation
  const cambioRegimen = saturacion(primera) !== saturacion(ultima)

  return (
    <section className="bloque">
      <h3 className="bloque-titulo">
        Evolución de la aproximación
        <span className="bloque-sub">{eventos.length} avisos · un mismo `session_id`</span>
      </h3>

      <LineChart
        titulo="Velocidad recomendada"
        unidad="kn"
        puntos={velocidad}
        color="var(--serie)"
        pie={<span className="gr-lectura gr-lectura-inerte">
          De {num(primera.recommended_speed_kn, 1, 'kn')} a {num(ultima.recommended_speed_kn, 1, 'kn')}
        </span>}
      />

      <LineChart
        titulo="Ahorro de CII frente a la velocidad actual"
        unidad="%"
        puntos={cii}
        color="var(--serie)"
        base={0}
        pie={<span className="gr-lectura gr-lectura-inerte">
          Bajo la línea de base, la maniobra emite más
        </span>}
      />

      {cambioRegimen && (
        <p className="aviso-regimen">
          <b>Cambio de régimen durante la aproximación.</b> Empezó en
          «{ETIQUETA_SATURACION[saturacion(primera)].toLowerCase()}» y terminó en
          «{ETIQUETA_SATURACION[saturacion(ultima)].toLowerCase()}»: la cola del puerto
          se movió lo suficiente para cambiar qué puede hacer el buque.
        </p>
      )}
    </section>
  )
}
