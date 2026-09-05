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
  titular, fondearaIgual, fondeo, ETIQUETA_FIABILIDAD, DETALLE_FIABILIDAD,
  ETIQUETA_SATURACION, COLOR_SEVERIDAD, type Severidad,
} from './status'
import { num, pct, horaUtc, fechaHoraUtc, antiguedad, etiquetaBuque, rumbo, esperaEstimada } from './format'
import { nombreOleaje, colorOleaje } from './douglas'

const ICONO_SEVERIDAD = { ok: '✓', alert: '!', critical: '×' } as const

/**
 * El glifo del chip sigue al TITULAR, no a la severidad cruda: un «✓» junto a «fondeará
 * igual» se contradice, aunque la severidad sea `ok` porque la recomendación es buena.
 */
function iconoTitular(r: OracleRecommendationV1['recommendation'], sev: Severidad): string {
  return fondearaIgual(r) ? '⚓' : ICONO_SEVERIDAD[sev]
}

/**
 * El `rationale` lo escribe un LLM y viene con énfasis ligero de Markdown —- en las filas
 * reales de la tabla aparece como `*large*` al citar el segmento de atraque. Sin tratarlo
 * se leen los asteriscos en pantalla.
 *
 * Se resuelve SOLO `*cursiva*`, partiendo el texto y devolviendo nodos de React: ni
 * `dangerouslySetInnerHTML` ni un parser de Markdown completo para tres asteriscos. Si el
 * modelo empieza a emitir más sintaxis, aquí es donde se añade.
 */
function conEnfasis(texto: string) {
  return texto.split(/(\*[^*\n]+\*)/g).map((trozo, i) =>
    trozo.startsWith('*') && trozo.endsWith('*') && trozo.length > 2
      ? <em key={i}>{trozo.slice(1, -1)}</em>
      : trozo,
  )
}

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

/**
 * Cuenta buques del contexto excluyendo al del evento. `port.inbound_count` incluye al
 * propio buque, y enseñar ese numero obligaba a explicar por que la lista de abajo tenia
 * uno menos. Se cuenta de la lista ya filtrada: el numero sale correcto y no hay nada
 * que aclarar.
 */
function conteo(lista: { es_objetivo?: boolean | null }[]): number {
  return lista.filter((b) => b.es_objetivo !== true).length
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
  fila, sesion, alCerrar, expandido = false, alAlternarExpansion,
}: {
  fila: FilaRecomendacion
  sesion: FilaRecomendacion[]
  alCerrar: () => void
  /** Solo en movil: la hoja ocupa toda la pantalla en vez de la parte de abajo. */
  expandido?: boolean
  alAlternarExpansion?: () => void
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
  const f = fondeo(ev)


  return (
    <aside
      className={'panel' + (expandido ? ' panel-expandido' : '')}
      aria-label="Recomendación del oráculo"
    >
      {/* Asa de la hoja: solo se ve en movil (en escritorio el panel es una columna fija).
          Dos estados en vez de arrastre libre: cubre el caso real —- ver el mapa o leer el
          texto— sin la complejidad de un gesto. */}
      <button
        className="panel-asa"
        onClick={alAlternarExpansion}
        aria-expanded={expandido}
        aria-label={expandido ? 'Encoger el panel para ver el mapa' : 'Expandir el panel'}
      >
        <span aria-hidden="true" />
      </button>
      <header className="panel-cab">
        <div className="panel-cab-fila">
          <span className="chip" style={{ ['--c' as string]: COLOR_SEVERIDAD[sev] }}>
            <span className="chip-icono" aria-hidden="true">{iconoTitular(r, sev)}</span>
            {titular(r)}
          </span>
          <button className="cerrar" onClick={alCerrar} aria-label="Cerrar panel">×</button>
        </div>
        <h2 className="panel-titulo">{etiquetaBuque(ev.vessel.mmsi, ev.vessel.name)}</h2>
        {/*
          Lo que no se sabe, no se rotula: sin IMO o sin tipo simplemente no hay segmento,
          en vez de un «Sin IMO» o un «Tipo indeterminado» que solo dicen lo que falta.
        */}
        <p className="panel-sub">
          {[
            ev.vessel.imo ? `IMO ${ev.vessel.imo}` : null,
            ev.vessel.is_container === true ? 'Portacontenedores'
              : ev.vessel.is_container === false ? 'Otra carga' : null,
          ].filter(Boolean).join(' · ')}
          {ev.vessel.imo || ev.vessel.is_container !== null ? ' → ' : ''}{ev.port.name}
        </p>
      </header>

      <section className="bloque">
        <h3 className="bloque-titulo">Llegada Just-In-Time</h3>
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
        {sat === 'ninguna' && (
          <p className="etiqueta-saturacion" title={r.nota ?? undefined}>
            {ETIQUETA_SATURACION[sat]}
          </p>
        )}
        {/* Con `design_speed_kn` el «no ejecutable» deja de ser un adjetivo y es una cuenta. */}
        {r.excede_v_diseno && r.design_speed_kn !== null && r.design_speed_kn !== undefined && (
          <p className="etiqueta-saturacion etiqueta-excede">
            Su casco da {num(r.design_speed_kn, 1, 'kn')}: pediría {num(r.recommended_speed_kn, 1, 'kn')}
          </p>
        )}

        {/*
          El nucleo del proyecto: no es ahorrar combustible navegando, es no quemarlo
          fondeado esperando atraque.
          .
          OJO CON EL SIGNIFICADO DE `idle_hours_avoided`. El oraculo lo calcula como
          `espera_hasta_atraque - ETA_dynamic`, o sea las horas que el buque pasaria
          fondeado SI NO CAMBIA NADA. Eso coincide con las horas EVITADAS solo cuando
          Kwon-Euler consigue estirar la travesia hasta la ventana de atraque, es decir
          cuando `convergio` es true.
          .
          En el caso saturado al minimo -- el mas frecuente con datos reales: los 3 de la
          tabla y 7 de los 14 del fixture -- el buque llega antes aunque vaya al minimo, asi
          que fondea casi lo mismo: MSC PRATITI pasa de fondear 61,0 h a 59,8 h. Anunciar
          "61 h menos fondeado" ahi es falso. Se enuncia como exposicion, no como ahorro.
          .
          Para dar la cifra REAL de horas evitadas en ese caso haria falta
          `tiempo_transito_estimado_h` del oraculo, que hoy no se emite (ver §15.1).
        */}
        {f.sinCambios !== null && f.sinCambios > 0 && (
          sat === 'frenando-al-minimo' ? (
            /*
              Caso saturado: el buque va a fondear de todas formas. El numero grande es lo
              que fondeara SIGUIENDO la recomendacion —- que es el plan—, no lo que fondearia
              sin hacer nada. Y al lado, cuanto evita de verdad: con
              `estimated_transit_hours` ya es una cifra, no un «no lo evita» (§7.9).
            */
            <div className="jit-hero jit-hero-espera">
              <span className="jit-cifra">
                {(f.conRecomendacion ?? f.sinCambios).toFixed(0)}<i>h</i>
              </span>
              <span className="jit-texto">
                fondeado esperando atraque, incluso frenando al mínimo.
                {f.evitado !== null && f.evitado > 0.05
                  ? ` Frenar recorta ${f.evitado.toFixed(1)} h de espera y el consumo de la travesía.`
                  : ' Reducir la velocidad no lo evita: recorta el consumo de la travesía.'}
              </span>
            </div>
          ) : (
            <div className="jit-hero" style={{ borderLeftColor: COLOR_SEVERIDAD[sev] }}>
              <span className="jit-cifra">
                {(f.evitado ?? f.sinCambios).toFixed(0)}<i>h</i>
              </span>
              <span className="jit-texto">
                menos fondeado quemando combustible, llegando cuando se libera el atraque
              </span>
            </div>
          )
        )}

        <dl className="datos">
          <Dato etiqueta="Travesía" valor={num(ev.route.duration_hours, 0, 'h')}
                apunte={r.estimated_transit_hours !== null && r.estimated_transit_hours !== undefined
                  ? `${num(ev.route.distance_nm, 0, 'nm')} · ${num(r.estimated_transit_hours, 0, 'h')} frenando`
                  : `${num(ev.route.distance_nm, 0, 'nm')} a velocidad actual`} />
          <Dato etiqueta="Atraque libre en" valor={num(ev.queue.estimated_wait_hours, 0, 'h')}
                apunte={ev.queue.queue_position !== null && ev.queue.queue_position !== undefined
                  ? `${ev.queue.queue_position}.º en cola${
                      ev.queue.berth_segment ? ` · segmento ${ev.queue.berth_segment}` : ''}`
                  : undefined} />
          <Dato etiqueta="Llegada prevista" valor={fechaHoraUtc(r.eta_optimized)}
                apunte={r.eta_current ? `sin ajustar: ${fechaHoraUtc(r.eta_current)}` : undefined} />
        </dl>

      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          Emisiones por milla (CII)
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
        {ETIQUETA_FIABILIDAD[fia] && (
          <p className="procedencia" title={DETALLE_FIABILIDAD[fia]}>
            <span className={`marca-fiabilidad marca-${fia}`} />
            {ETIQUETA_FIABILIDAD[fia]}
          </p>
        )}
        {combustibleExtra
          ? <p className="fuel-linea">
              {Math.abs(r.fuel_saved_t!).toFixed(1)} t más de combustible al acelerar
            </p>
          : r.fuel_saved_t !== null && r.fuel_saved_t !== undefined && r.fuel_saved_t > 0
          ? <p className="fuel-linea">{r.fuel_saved_t.toFixed(1)} t menos de combustible en la travesía</p>
          : null}
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          Por qué
          {/*
            El calculo NO esta degradado: ruta, meteo, CII y Kwon-Euler son los mismos.
            Lo unico que fallo es el texto de acompanamiento, que es lo ultimo del
            pipeline. Por eso se marca junto al texto y no junto a los numeros.
          */}
          {r.rationale_degradado && (
            <span className="marca-degradado"
                  title={'La redacción automática falló y se usó el resumen de respaldo. ' +
                         'Los cálculos (ruta, meteo, CII, velocidad) no están afectados.'}>
              redacción de respaldo
            </span>
          )}
        </h3>
        <p className="racional">{conEnfasis(r.rationale)}</p>
      </section>

      <section className="bloque">
        <h3 className="bloque-titulo">
          Estado del mar en ruta
          <span className="bloque-sub">
            {ev.route_weather.length} puntos
            {r.weather_speed_loss_pct !== null && r.weather_speed_loss_pct !== undefined
              && ` · resta ${r.weather_speed_loss_pct.toFixed(1)} % de velocidad`}
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
          <div className="conteo"><b>{conteo(ev.context_vessels.berthed)}</b><span>amarrados</span></div>
          <div className="conteo"><b>{conteo(ev.context_vessels.anchored)}</b><span>fondeados</span></div>
          <div className="conteo"><b>{conteo(ev.context_vessels.inbound)}</b><span>en camino</span></div>
        </div>
        <ListaContexto ev={ev} />
      </section>

      <PanelSesion eventos={sesion} />

      <footer className="panel-pie">
        <div><span>Fix del buque</span><b>{horaUtc(ev.vessel.position_at)} · {antiguedad(ev.vessel.position_at)}</b></div>
        <div><span>Emitido</span><b>{horaUtc(ev.emitted_at)} · {antiguedad(ev.emitted_at)}</b></div>
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
        const otros = lista.filter((b) => b.es_objetivo !== true && String(b.mmsi) !== propio)
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
                          ? `${esperaEstimada(b)!.toFixed(0)} h`
                          : ''}
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
