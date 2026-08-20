/**
 * El panel: la recomendación, su justificación y de dónde sale cada número.
 *
 * Toda la política de honestidad del frontal se concentra aquí, porque es donde se
 * afirman cosas: `fuel_saved_t` rotulado como estimación y capaz de ser NEGATIVO
 * (combustible extra) cuando la recomendación es acelerar; `estimated_wait_hours`
 * rotulado como modelado y no observado; el `metodo` del CII a la vista porque un CII
 * por EEXI y uno por casco geométrico no son comparables; `nota` mostrada siempre que
 * exista, porque es la letra pequeña del número grande; y la hora del contexto
 * marcada como hora de EMISIÓN, ya que `snapshot_at` llega null.
 */
import { LineChart, type Punto } from './chart'
import { PanelSesion } from './session'
import type { FilaRecomendacion } from './feed'
import type { OracleRecommendationV1 } from './types'
import {
  severidad, fiabilidad, saturacion,
  ETIQUETA_SEVERIDAD, ETIQUETA_FIABILIDAD, ETIQUETA_SATURACION, COLOR_SEVERIDAD,
} from './status'
import { num, pct, horaUtc, fechaHoraUtc, antiguedad, etiquetaBuque, rumbo, esperaEstimada, SIN_DATO } from './format'
import { nombreOleaje, colorOleaje } from './douglas'

const ICONO_SEVERIDAD = { ok: '✓', alert: '!', critical: '×' } as const

function Dato({ etiqueta, valor, apunte }: { etiqueta: string; valor: string; apunte?: string }) {
  return (
    <div className="dato">
      <dt className="dato-et">{etiqueta}</dt>
      <dd className="dato-v">
        {valor}
        {apunte && <span className="dato-apunte">{apunte}</span>}
      </dd>
    </div>
  )
}

function distanciaAcumulada(ev: OracleRecommendationV1): number[] {
  const R = 3440.065
  const wp = ev.route.waypoints
  const acc = [0]
  for (let i = 1; i < wp.length; i++) {
    const [lo1, la1] = [wp[i - 1]![0]!, wp[i - 1]![1]!]
    const [lo2, la2] = [wp[i]![0]!, wp[i]![1]!]
    const dLa = ((la2 - la1) * Math.PI) / 180
    const dLo = ((lo2 - lo1) * Math.PI) / 180
    const a = Math.sin(dLa / 2) ** 2 +
      Math.cos((la1 * Math.PI) / 180) * Math.cos((la2 * Math.PI) / 180) * Math.sin(dLo / 2) ** 2
    acc.push(acc[i - 1]! + 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)))
  }
  return acc
}

export function Panel({
  fila, sesion, alCerrar,
}: {
  fila: FilaRecomendacion
  sesion: FilaRecomendacion[]
  alCerrar: () => void
}) {
  const ev = fila.payload
  const r = ev.recommendation
  const sev = severidad(r)
  const fia = fiabilidad(r)
  const sat = saturacion(r)

  const dist = distanciaAcumulada(ev)
  const etiquetaX = (i: number) => `${dist[i]!.toFixed(0)} nm`
  const ola: Punto[] = ev.route_weather.map((m, i) => ({
    x: dist[i] ?? i, y: m.wave_height ?? null, etiqueta: etiquetaX(i),
  }))
  const viento: Punto[] = ev.route_weather.map((m, i) => ({
    x: dist[i] ?? i, y: m.wind_speed_kn ?? null, etiqueta: etiquetaX(i),
  }))
  const primerTramo = ev.route_weather[0]

  const combustibleExtra = r.fuel_saved_t !== null && r.fuel_saved_t !== undefined && r.fuel_saved_t < 0

  return (
    <aside className="panel" aria-label="Recomendación del oráculo">
      <header className="panel-cab">
        <div className="panel-cab-fila">
          <span className="chip" style={{ ['--c' as string]: COLOR_SEVERIDAD[sev] }}>
            <span className="chip-icono" aria-hidden="true">{ICONO_SEVERIDAD[sev]}</span>
            {ETIQUETA_SEVERIDAD[sev]}
          </span>
          <button className="cerrar" onClick={alCerrar} aria-label="Cerrar panel">×</button>
        </div>
        <h2 className="panel-titulo">{etiquetaBuque(ev.vessel.mmsi, ev.vessel.name)}</h2>
        <p className="panel-sub">
          {ev.vessel.imo ? `IMO ${ev.vessel.imo}` : 'Sin IMO en el AIS'}
          {' · '}
          {ev.vessel.is_container === true ? 'Portacontenedores'
            : ev.vessel.is_container === false ? 'Otra carga' : 'Tipo indeterminado'}
          {' → '}{ev.port.name}
        </p>
        {!ev.vessel.name && (
          <p className="panel-carencia">
            El oráculo no envía todavía el nombre del buque, así que la identidad es el MMSI.
          </p>
        )}
      </header>

      <section className="bloque">
        <h3 className="bloque-titulo">La recomendación</h3>
        <div className="velocidad">
          <span className="velocidad-de">{num(ev.vessel.speed_kn, 1)}</span>
          <span className="velocidad-flecha" aria-hidden="true">→</span>
          <span className="velocidad-a" style={{ color: COLOR_SEVERIDAD[sev] }}>
            {num(r.recommended_speed_kn, 1)}
          </span>
          <span className="velocidad-u">kn</span>
          <span className="velocidad-delta">
            {r.speed_delta_kn > 0 ? 'acelerar' : 'frenar'} {num(Math.abs(r.speed_delta_kn), 1, 'kn')}
          </span>
        </div>
        <p className="etiqueta-saturacion">{ETIQUETA_SATURACION[sat]}</p>

        <dl className="datos">
          <Dato etiqueta="ETA actual" valor={fechaHoraUtc(r.eta_current)}
                apunte={r.eta_current ? undefined : 'el webhook no envió ETA_dynamic'} />
          <Dato etiqueta="ETA optimizada" valor={fechaHoraUtc(r.eta_optimized)} />
          <Dato etiqueta="Ralentí evitado" valor={num(r.idle_hours_avoided, 2, 'h')}
                apunte={r.idle_hours_avoided === null ? 'requiere ETA_dynamic' : undefined} />
          <Dato
            etiqueta={combustibleExtra ? 'Combustible extra' : 'Combustible ahorrado'}
            valor={num(r.fuel_saved_t === null || r.fuel_saved_t === undefined
              ? null : Math.abs(r.fuel_saved_t), 3, 't')}
            apunte={r.fuel_saved_t === null || r.fuel_saved_t === undefined
              ? 'sin DWT real en THETIS-MRV para este IMO'
              : combustibleExtra ? 'estimación · la recomendación CUESTA combustible'
              : 'estimación sobre el DWT real de THETIS-MRV'}
          />
        </dl>

        {r.nota && <p className="nota-kwon"><b>Nota del cálculo.</b> {r.nota}</p>}
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          Intensidad de carbono (CII)
          <span className="bloque-sub">gCO₂ por tonelada y milla náutica</span>
        </h3>
        <div className="cii">
          <div className="cii-lado">
            <span className="cii-et">a velocidad actual</span>
            <span className="cii-v">{num(r.cii.inicial, 2)}</span>
          </div>
          <span className="cii-flecha" aria-hidden="true">→</span>
          <div className="cii-lado">
            <span className="cii-et">a velocidad JIT</span>
            <span className="cii-v" style={{ color: COLOR_SEVERIDAD[sev] }}>{num(r.cii.jit, 2)}</span>
          </div>
          <div className="cii-ahorro">
            <span className="cii-ahorro-v" style={{ color: COLOR_SEVERIDAD[sev] }}>{pct(r.cii.ahorro_pct)}</span>
            <span className="cii-et">{r.alerta_cii ? 'empeora' : 'mejora'}</span>
          </div>
        </div>
        <p className="procedencia">
          <span className={`marca-fiabilidad marca-${fia}`} />
          {ETIQUETA_FIABILIDAD[fia]}
          {r.cii.metodo === 'fallback_admiralty' &&
            ' — estimado desde las dimensiones del casco, no comparable con otros buques'}
        </p>
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">Por qué</h3>
        <p className="racional">{r.rationale}</p>
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          Estado del mar en ruta
          <span className="bloque-sub">
            {num(ev.route.distance_nm, 1, 'nm')} · {ev.route_weather.length} waypoints
          </span>
        </h3>
        {primerTramo && (
          <p className="mar-ahora">
            En la posición del buque:{' '}
            <b style={{ color: colorOleaje(primerTramo.wave_height) }}>
              {nombreOleaje(primerTramo.wave_height)}
            </b>
            {' · '}{num(primerTramo.wave_height, 2, 'm')}
            {' · '}periodo {num(primerTramo.wave_period, 1, 's')}
            {' · '}viento {num(primerTramo.wind_speed_kn, 1, 'kn')} de {rumbo(primerTramo.wind_direction)}
            {primerTramo.wind_gusts_kn !== null && primerTramo.wind_gusts_kn !== undefined &&
              ` (rachas ${primerTramo.wind_gusts_kn.toFixed(1)} kn)`}
          </p>
        )}
        <LineChart titulo="Altura de ola" unidad="m" puntos={ola}
                   color="var(--serie)" destacado={0} />
        <LineChart titulo="Viento" unidad="kn" puntos={viento}
                   color="var(--serie)" destacado={0} />
        <details className="tabla-desplegable">
          <summary>Ver los valores como tabla</summary>
          <div className="tabla-scroll">
            <table>
              <thead>
                <tr><th>nm</th><th>ETA</th><th>Ola m</th><th>T s</th><th>Viento kn</th><th>Rachas kn</th></tr>
              </thead>
              <tbody>
                {ev.route_weather.map((m, i) => (
                  <tr key={i}>
                    <td>{dist[i]!.toFixed(0)}</td>
                    <td>{horaUtc(m.eta)}</td>
                    <td>{num(m.wave_height, 2)}</td>
                    <td>{num(m.wave_period, 1)}</td>
                    <td>{num(m.wind_speed_kn, 1)}</td>
                    <td>{num(m.wind_gusts_kn, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          {ev.port.name}
          <span className="bloque-sub">
            {ev.port.snapshot_at
              ? `contexto a las ${horaUtc(ev.port.snapshot_at)}`
              : `sin hora de contexto · se usa la de emisión, ${horaUtc(ev.emitted_at)}`}
          </span>
        </h3>
        <div className="conteos">
          <div className="conteo"><b>{ev.port.berthed_count}</b><span>amarrados</span></div>
          <div className="conteo"><b>{ev.port.anchored_count}</b><span>fondeados</span></div>
          <div className="conteo"><b>{ev.port.inbound_count}</b><span>en camino</span></div>
        </div>
        <p className="apunte-conteo">
          «En camino» incluye a este buque, que viene también en el contexto del puerto.
          {ev.port.context_radius_nm === null &&
            ' El evento no trae el radio con que se armó el contexto, así que no se dibuja en el mapa.'}
        </p>
        {r.queue ? (
          <dl className="datos">
            <Dato etiqueta="Posición en cola" valor={r.queue.queue_position?.toString() ?? SIN_DATO} />
            <Dato etiqueta="Espera estimada" valor={num(r.queue.estimated_wait_hours, 1, 'h')}
                  apunte="modelada, no observada" />
            <Dato etiqueta="Segmento de atraque" valor={r.queue.berth_segment ?? SIN_DATO} />
          </dl>
        ) : (
          <p className="nota-vacia">
            El oráculo calcula la posición en cola y la espera estimada de este buque, pero
            todavía no las envía en el evento —- son justo la justificación de frenar.
          </p>
        )}
        <ListaContexto ev={ev} />
      </section>

      <PanelSesion eventos={sesion} />

      <footer className="panel-pie">
        <div><span>Fix del buque</span><b>{horaUtc(ev.vessel.position_at)} · {antiguedad(ev.vessel.position_at)}</b></div>
        <div><span>Emitido</span><b>{horaUtc(ev.emitted_at)} · {antiguedad(ev.emitted_at)}</b></div>
        <div><span>Destino AIS (crudo)</span><b>{ev.vessel.destination_raw ?? SIN_DATO}</b></div>
        <div><span>Rumbo</span><b>{ev.vessel.heading === null || ev.vessel.heading === undefined
          ? 'sin dato en el AIS' : rumbo(ev.vessel.heading)}</b></div>
        <div className="panel-pie-id"><span>event_id</span><b>{ev.event_id}</b></div>
      </footer>
    </aside>
  )
}

function ListaContexto({ ev }: { ev: OracleRecommendationV1 }) {
  const propio = String(ev.vessel.mmsi)
  const grupos = [
    { clase: 'anchored' as const, titulo: 'Fondeados', lista: ev.context_vessels.anchored },
    { clase: 'berthed' as const, titulo: 'Amarrados', lista: ev.context_vessels.berthed },
    { clase: 'inbound' as const, titulo: 'En camino', lista: ev.context_vessels.inbound },
  ]
  return (
    <div className="contexto">
      {grupos.map(({ clase, titulo, lista }) => {
        const otros = lista.filter((b) => String(b.mmsi) !== propio)
        return (
          <div key={clase} className="contexto-grupo">
            <h4 className="contexto-titulo">
              <span className={`mk-ctx-icono mk-ctx-${clase}`} aria-hidden="true" />
              {titulo} <span className="contexto-n">{otros.length}</span>
            </h4>
            {otros.length === 0
              ? <p className="contexto-vacio">Ninguno</p>
              : <ul className="contexto-lista">
                  {otros.map((b) => (
                    <li key={String(b.mmsi)}>
                      <span className="contexto-mmsi">{b.mmsi}</span>
                      <span className="contexto-espera">
                        {esperaEstimada(b) !== null
                          ? `${esperaEstimada(b)!.toFixed(1)} h est.`
                          : clase === 'berthed' ? '' : 'espera sin dato'}
                      </span>
                    </li>
                  ))}
                </ul>}
          </div>
        )
      })}
    </div>
  )
}
