/**
 * La pantalla. Un mapa, una lista de avisos y un panel.
 *
 * El estado es dos `Map` en `useState` y nada más: hay decenas de marcadores, no
 * cientos, así que un gestor de estado o una capa de virtualización serían maquinaria
 * sin trabajo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { crearMapa, alternarSeamark, encuadrarRuta, observarTamano } from './map'
import { montarCapasRuta, pintarRuta } from './route-layer'
import { crearCapaMarcadores, type CapaMarcadores } from './markers'
import {
  cargarInicial, cargarSesion, arrancarRepesca, porBuque, vigencia,
  USANDO_MOCK, INTERVALO_REPESCA_MS, type FilaRecomendacion,
} from './feed'
import { Panel } from './panel'
import { severidad, COLOR_SEVERIDAD, ETIQUETA_SEVERIDAD } from './status'
import { etiquetaBuque, num, antiguedad } from './format'
import { BANDAS_DOUGLAS } from './douglas'

const ANCHO_PANEL = 430

export default function App() {
  const refMapa = useRef<HTMLDivElement>(null)
  const mapaRef = useRef<MapLibreMap | null>(null)
  const capaRef = useRef<CapaMarcadores | null>(null)

  const [filas, setFilas] = useState<FilaRecomendacion[]>([])
  const [seleccion, setSeleccion] = useState<string | null>(null)
  const [sesion, setSesion] = useState<FilaRecomendacion[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [seamark, setSeamark] = useState(false)
  const [ahora, setAhora] = useState(Date.now())

  // Un reloj propio: la vigencia de los marcadores depende del paso del tiempo, no
  // solo de que lleguen filas nuevas. Sin esto un marcador se quedaría "fresco" para
  // siempre en una pestaña abierta.
  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), 60_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!refMapa.current || mapaRef.current) return
    const contenedor = refMapa.current
    const mapa = crearMapa(contenedor)
    mapaRef.current = mapa
    const dejarDeObservar = observarTamano(mapa, contenedor)
    mapa.on('load', () => {
      montarCapasRuta(mapa)
      capaRef.current = crearCapaMarcadores(mapa)
      mapa.resize()
      setAhora(Date.now())
    })
    mapa.on('click', () => setSeleccion(null))
    return () => { dejarDeObservar(); mapa.remove(); mapaRef.current = null }
  }, [])

  useEffect(() => {
    let vivo = true
    cargarInicial()
      .then((f) => { if (vivo) { setFilas(f); setCargando(false) } })
      .catch((e: Error) => { if (vivo) { setError(e.message); setCargando(false) } })
    return () => { vivo = false }
  }, [])

  const ultimoVisto = useMemo(
    () => (filas.length ? filas.reduce((m, f) => (f.emitted_at > m ? f.emitted_at : m), filas[0]!.emitted_at) : null),
    [filas],
  )
  const refUltimo = useRef<string | null>(null)
  refUltimo.current = ultimoVisto

  useEffect(() => arrancarRepesca(
    () => refUltimo.current,
    (nuevas) => setFilas((prev) => {
      const porId = new Map(prev.map((f) => [f.event_id, f]))
      nuevas.forEach((f) => porId.set(f.event_id, f))
      return [...porId.values()]
    }),
    (e) => setError(e.message),
  ), [])

  const ultimoPorBuque = useMemo(() => [...porBuque(filas).values()], [filas])
  const visibles = useMemo(
    () => ultimoPorBuque
      .filter((f) => vigencia(f.emitted_at, ahora) !== 'retirado')
      .sort((a, b) => b.emitted_at.localeCompare(a.emitted_at)),
    [ultimoPorBuque, ahora],
  )
  const filaSel = useMemo(
    () => filas.find((f) => f.event_id === seleccion) ?? null,
    [filas, seleccion],
  )

  const seleccionar = useCallback((fila: FilaRecomendacion) => {
    setSeleccion(fila.event_id)
    cargarSesion(fila.session_id).then(setSesion).catch(() => setSesion([fila]))
    const mapa = mapaRef.current
    if (mapa) encuadrarRuta(mapa, fila.payload.route.waypoints, ANCHO_PANEL)
  }, [])

  useEffect(() => {
    const mapa = mapaRef.current
    if (!mapa || !capaRef.current) return
    capaRef.current.pintar(visibles, seleccion, seleccionar)
    pintarRuta(mapa, filaSel?.payload ?? null)
  }, [visibles, seleccion, filaSel, seleccionar])

  useEffect(() => {
    const mapa = mapaRef.current
    if (mapa) alternarSeamark(mapa, seamark)
  }, [seamark])

  return (
    <div className="app">
      <div ref={refMapa} className="mapa" />

      <header className="cabecera">
        <div className="marca">
          <span className="marca-n">Nautiq</span>
          <span className="marca-s">Oráculo de Adaptive Slow Steaming</span>
        </div>
        {USANDO_MOCK && (
          <div
            className="banner-mock"
            role="status"
            title={'Eventos grabados ejecutando el grafo real del oráculo. Las horas se han ' +
                   'desplazado en bloque para que el más reciente sea «ahora»; los intervalos ' +
                   'relativos entre eventos son los originales.'}
          >
            <b>Datos de ejemplo</b> · 11 eventos grabados del oráculo
          </div>
        )}
        <div className="cabecera-ctrl">
          <label className="interruptor">
            <input type="checkbox" checked={seamark} onChange={(e) => setSeamark(e.target.checked)} />
            <span>Balizamiento</span>
          </label>
          <span className="cadencia">
            {USANDO_MOCK ? 'sin repesca' : `repesca cada ${INTERVALO_REPESCA_MS / 1000} s`}
          </span>
        </div>
      </header>

      <nav className="avisos" aria-label="Avisos del oráculo">
        <h2 className="avisos-titulo">
          Avisos <span className="avisos-n">{visibles.length}</span>
        </h2>
        {cargando && <p className="avisos-estado">Cargando…</p>}
        {error && (
          <p className="avisos-error">
            <b>No se pudo leer la tabla.</b> {error}
          </p>
        )}
        {!cargando && !error && visibles.length === 0 && (
          <p className="avisos-estado">
            Ningún aviso en las últimas 3 h. El oráculo solo emite cuando hay un buque a
            menos de 12 h de su puerto.
          </p>
        )}
        <ul className="avisos-lista">
          {visibles.map((f) => {
            const sev = severidad(f.payload.recommendation)
            const vig = vigencia(f.emitted_at, ahora)
            return (
              <li key={f.event_id}>
                <button
                  className={'aviso' + (f.event_id === seleccion ? ' aviso-sel' : '') +
                             (vig === 'atenuado' ? ' aviso-viejo' : '')}
                  onClick={() => seleccionar(f)}
                  aria-pressed={f.event_id === seleccion}
                >
                  <span className="aviso-punto" style={{ background: COLOR_SEVERIDAD[sev] }}
                        title={ETIQUETA_SEVERIDAD[sev]} />
                  <span className="aviso-cuerpo">
                    <span className="aviso-id">
                      {etiquetaBuque(f.payload.vessel.mmsi, f.payload.vessel.name)}
                    </span>
                    <span className="aviso-meta">
                      {f.payload.port.name} · {num(f.payload.vessel.speed_kn, 1)} →{' '}
                      {num(f.payload.recommendation.recommended_speed_kn, 1)} kn
                    </span>
                    <span className="aviso-hora">{antiguedad(f.emitted_at, ahora)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      {filaSel && (
        <Panel fila={filaSel} sesion={sesion.length ? sesion : [filaSel]}
               alCerrar={() => setSeleccion(null)} />
      )}

      <div className="leyenda">
        <div className="leyenda-bloque">
          <span className="leyenda-t">Estado del mar en ruta (Douglas)</span>
          <div className="leyenda-escala">
            {BANDAS_DOUGLAS.map((b) => (
              <span key={b.nombre} className="leyenda-paso" title={
                b.hasta === Infinity ? 'más de 2,5 m' : `hasta ${b.hasta} m`
              }>
                <i style={{ background: b.color }} />
                {b.nombre}
              </span>
            ))}
          </div>
        </div>
        <div className="leyenda-bloque">
          <span className="leyenda-t">Recomendación</span>
          <div className="leyenda-escala">
            {(['ok', 'alert', 'critical'] as const).map((s) => (
              <span key={s} className="leyenda-paso">
                <i style={{ background: COLOR_SEVERIDAD[s] }} />
                {ETIQUETA_SEVERIDAD[s]}
              </span>
            ))}
          </div>
        </div>
        <p className="leyenda-nota">
          Ruta discontinua: prevista por searoute, no la derrota observada. Sin rumbo en
          el AIS se dibuja círculo en vez de triángulo. Las posiciones no se interpolan.
        </p>
      </div>
    </div>
  )
}
