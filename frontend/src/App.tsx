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
  USANDO_MOCK, INTERVALO_REPESCA_MS, totalMock, VENTANA_AVISOS_H, type FilaRecomendacion,
} from './feed'
import { Panel } from './panel'
import { severidad, titular, fondearaIgual, COLOR_SEVERIDAD, ETIQUETA_SEVERIDAD } from './status'
import { prepararAudio, reproducirAviso, sonidoActivo, guardarSonido } from './alerta'
import { ENTORNO, ETIQUETA_ENTORNO, ES_PRODUCCION, TABLA, TABLA_FIJADA } from './entorno'
import { etiquetaBuque, num, antiguedad } from './format'
import { BANDAS_DOUGLAS } from './douglas'

const ANCHO_PANEL = 430
/** Debe coincidir con el `@media (max-width: 760px)` de app.css. */
const MOVIL = '(max-width: 760px)'
/** Fraccion de alto que ocupa la hoja del panel en movil. Coincide con `--alto-hoja`. */
const ALTO_HOJA = 0.58

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
  const [nMock, setNMock] = useState(0)
  const [sonido, setSonido] = useState(sonidoActivo)
  // event_ids llegados en la última repesca: se resaltan un rato y se apagan solos.
  const [nuevos, setNuevos] = useState<Set<string>>(new Set())
  // En movil la lista es una hoja inferior que se pliega: sin esto ocupa media pantalla
  // y no deja ver el mapa. En escritorio el boton esta oculto y siempre esta abierta.
  const [listaAbierta, setListaAbierta] = useState(true)
  // En movil el panel es una hoja inferior que deja ver el mapa; se puede expandir a
  // pantalla completa para leer el "por que" sin ir haciendo scroll en un hueco pequeno.
  const [panelExpandido, setPanelExpandido] = useState(false)
  const [esMovil, setEsMovil] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOVIL).matches,
  )

  // Reactivo al giro del telefono y al cambio de tamano: si no, una rotacion deja el
  // encuadre de la ruta calculado para la otra disposicion.
  useEffect(() => {
    const mq = window.matchMedia(MOVIL)
    const alCambiar = (e: MediaQueryListEvent) => setEsMovil(e.matches)
    mq.addEventListener('change', alCambiar)
    return () => mq.removeEventListener('change', alCambiar)
  }, [])
  const [ultimaLectura, setUltimaLectura] = useState<number | null>(null)

  useEffect(() => { if (USANDO_MOCK) totalMock().then(setNMock) }, [])
  useEffect(prepararAudio, [])

  /**
   * Señala la llegada de avisos: suena una vez por tanda (no una por fila, que con una
   * ráfaga de Flink sería una ametralladora) y con el timbre del caso más grave.
   */
  const senalarLlegada = useCallback((filas: FilaRecomendacion[]) => {
    if (!filas.length) return
    reproducirAviso(filas.some((f) => severidad(f.payload.recommendation) === 'critical'))
    const ids = filas.map((f) => f.event_id)
    setNuevos((prev) => new Set([...prev, ...ids]))
    window.setTimeout(() => setNuevos((prev) => {
      const s = new Set(prev)
      ids.forEach((i) => s.delete(i))
      return s
    }), 12_000)
  }, [])

  // Un reloj propio: la vigencia de los marcadores depende del paso del tiempo, no
  // solo de que lleguen filas nuevas. Sin esto un marcador se quedaría "fresco" para
  // siempre en una pestaña abierta.
  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), USANDO_MOCK ? 60_000 : 5_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!refMapa.current || mapaRef.current) return
    const contenedor = refMapa.current
    let vivo = true
    let limpiar: (() => void) | null = null

    // El estilo se pide a OpenFreeMap antes de construir el mapa, asi que esto es
    // asincrono: si el componente se desmonta mientras llega, se descarta el mapa.
    crearMapa(contenedor).then((mapa) => {
      if (!vivo) { mapa.remove(); return }
      mapaRef.current = mapa
      const dejarDeObservar = observarTamano(mapa, contenedor)
      mapa.on('load', () => {
        montarCapasRuta(mapa)
        capaRef.current = crearCapaMarcadores(mapa)
        mapa.resize()
        setAhora(Date.now())
      })
      mapa.on('click', () => setSeleccion(null))
      limpiar = () => { dejarDeObservar(); mapa.remove(); mapaRef.current = null }
    })

    return () => { vivo = false; limpiar?.() }
  }, [])

  useEffect(() => {
    let vivo = true
    cargarInicial()
      .then((f) => { if (vivo) { setFilas(f); setCargando(false); setUltimaLectura(Date.now()) } })
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
    (nuevas) => {
      setFilas((prev) => {
        const porId = new Map(prev.map((f) => [f.event_id, f]))
        nuevas.forEach((f) => porId.set(f.event_id, f))
        return [...porId.values()]
      })
      senalarLlegada(nuevas)
    },
    (e) => setError(e.message),
    () => { setUltimaLectura(Date.now()); setError(null) },
  ), [senalarLlegada])

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
    setPanelExpandido(false)
    // La lista y el panel son la misma hoja inferior en movil: dejarla abierta detras del
    // panel no aporta nada y se come el mapa.
    if (esMovil) setListaAbierta(false)
    cargarSesion(fila.session_id).then(setSesion).catch(() => setSesion([fila]))
    const mapa = mapaRef.current
    if (!mapa) return
    // En movil el panel tapa la parte de ABAJO; en escritorio, la derecha.
    encuadrarRuta(
      mapa,
      fila.payload.route.waypoints,
      esMovil
        ? { bottom: Math.round(mapa.getContainer().clientHeight * ALTO_HOJA) }
        : { right: ANCHO_PANEL },
    )
  }, [esMovil])

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
          <span className="marca-s">Llegada Just-In-Time · Adaptive Slow Steaming</span>
          <span className="marca-s-corta">JIT</span>
        </div>
        {/*
          Este hueco central lo ocupaba un aviso de «datos de ejemplo». Con dos despliegues
          —- uno por entorno, leyendo tablas distintas— lo que de verdad hace falta saber de un
          vistazo es CUÁL de los dos se está mirando, y de qué tabla sale lo que se ve. Que
          los datos sean de ejemplo pasa a ser un matiz dentro de esa misma chapa.
        */}
        <div
          className={'entorno' + (ES_PRODUCCION ? ' entorno-pro' : '')}
          title={USANDO_MOCK
            ? `${ETIQUETA_ENTORNO[ENTORNO]} · sin credenciales, así que se leen los ${nMock || ''} ` +
              'eventos de src/mock/events.json en vez de la base de datos.'
            : `${ETIQUETA_ENTORNO[ENTORNO]} · tabla leída: ${TABLA}` +
              (TABLA_FIJADA ? ' (fijada por VITE_TABLA_RECOMENDACIONES)' : ' (derivada del entorno)')}
        >
          <span className="entorno-clave">{ENTORNO}</span>
          <span className="entorno-detalle">
            {USANDO_MOCK ? 'datos de ejemplo' : TABLA}
          </span>
        </div>
        <div className="cabecera-ctrl">
          <label
            className="interruptor"
            title={'Boyas, luces y marcas de navegación de OpenSeaMap. Solo se ven al acercarse ' +
                   'a un puerto: en la vista general no dibuja nada.'}
          >
            <input type="checkbox" checked={seamark} onChange={(e) => setSeamark(e.target.checked)} />
            <span className="ctrl-largo">Balizamiento</span>
            <span className="ctrl-corto">Balizas</span>
          </label>
          <label className="interruptor" title="Sonido al llegar avisos nuevos">
            <input
              type="checkbox"
              checked={sonido}
              onChange={(e) => { setSonido(e.target.checked); guardarSonido(e.target.checked) }}
            />
            <span>Sonido</span>
          </label>
          {USANDO_MOCK && visibles.length > 0 && (
            /* En modo fixture no hay repesca, así que el aviso no se dispararía nunca.
               Este botón lo lanza sobre el último evento para poder probarlo. */
            <button className="probar" onClick={() => senalarLlegada([visibles[0]!])}>
              Probar aviso
            </button>
          )}
          {/*
            En modo fixture no se muestra nada: la insignia de «Datos de ejemplo» ya dice que
            no hay feed en vivo, y un «sin repesca» al lado era jerga repetida.
            Conectado se muestra CUÁNDO se leyó por última vez, no cada cuánto se pretende
            leer: una cadencia teórica no demuestra que siga funcionando; un reloj que avanza,
            sí — y si se congela, se ve.
          */}
          {!USANDO_MOCK && ultimaLectura !== null && (
            <span className="cadencia" title={`Se relee la tabla cada ${INTERVALO_REPESCA_MS / 1000} s`}>
              <span className={'latido' + (ahora - ultimaLectura > INTERVALO_REPESCA_MS * 2.5 ? ' latido-frio' : '')} />
              {ahora - ultimaLectura < 60_000
                ? `leído hace ${Math.max(0, Math.round((ahora - ultimaLectura) / 1000))} s`
                : `leído ${antiguedad(new Date(ultimaLectura).toISOString(), ahora)}`}
            </span>
          )}
        </div>
      </header>

      <nav
        className={'avisos' + (listaAbierta ? '' : ' avisos-plegada')}
        aria-label="Avisos del oráculo"
      >
        <h2 className="avisos-titulo">
          <button
            className="avisos-plegar"
            onClick={() => setListaAbierta((v) => !v)}
            aria-expanded={listaAbierta}
            aria-label={listaAbierta ? 'Plegar la lista de avisos' : 'Desplegar la lista de avisos'}
          >
            <span aria-hidden="true">{listaAbierta ? '▾' : '▴'}</span>
          </button>
          Avisos
          <span className="avisos-cuenta">
            {nuevos.size > 0 && <span className="avisos-nuevos">{nuevos.size} nuevo{nuevos.size > 1 ? 's' : ''}</span>}
            <span className="avisos-n">{visibles.length}</span>
          </span>
        </h2>
        {cargando && <p className="avisos-estado">Cargando…</p>}
        {error && (
          <p className="avisos-error">
            <b>No se pudo leer la tabla.</b> {error}
          </p>
        )}
        {!cargando && !error && visibles.length === 0 && (
          <p className="avisos-estado">Ningún aviso en las últimas {VENTANA_AVISOS_H} h.</p>
        )}
        <ul className="avisos-lista">
          {visibles.map((f) => {
            const sev = severidad(f.payload.recommendation)
            const vig = vigencia(f.emitted_at, ahora)
            return (
              <li key={f.event_id}>
                <button
                  className={'aviso' + (f.event_id === seleccion ? ' aviso-sel' : '') +
                             (vig === 'atenuado' ? ' aviso-viejo' : '') +
                             (nuevos.has(f.event_id) ? ' aviso-nuevo' : '')}
                  onClick={() => seleccionar(f)}
                  aria-pressed={f.event_id === seleccion}
                >
                  <span className="aviso-punto" style={{ background: COLOR_SEVERIDAD[sev] }}
                        title={titular(f.payload.recommendation)} />
                  <span className="aviso-cuerpo">
                    <span className="aviso-id">
                      {etiquetaBuque(f.payload.vessel.mmsi, f.payload.vessel.name)}
                    </span>
                    <span className="aviso-meta">
                      {f.payload.port.name} · {num(f.payload.vessel.speed_kn, 1)} →{' '}
                      {num(f.payload.recommendation.recommended_speed_kn, 1)} kn
                      {fondearaIgual(f.payload.recommendation) && (
                        <span className="aviso-ancla" title="Fondeará esperando atraque aunque frene al mínimo">
                          {' ⚓'}
                        </span>
                      )}
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
        <Panel
          fila={filaSel}
          sesion={sesion.length ? sesion : [filaSel]}
          alCerrar={() => setSeleccion(null)}
          expandido={panelExpandido}
          alAlternarExpansion={() => setPanelExpandido((v) => !v)}
        />
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
        <div className="leyenda-bloque">
          <span className="leyenda-t">Al abrir una recomendación</span>
          <div className="leyenda-escala">
            <span className="leyenda-paso">
              <i className="mk-ctx-icono mk-ctx-berthed" />amarrados
            </span>
            <span className="leyenda-paso">
              <i className="mk-ctx-icono mk-ctx-anchored" />fondeados
            </span>
            <span className="leyenda-paso">
              <i className="mk-ctx-icono mk-ctx-inbound" />en camino
            </span>
          </div>
        </div>
        <p className="leyenda-nota">
          <b>⚓</b> fondeará esperando atraque aunque frene al mínimo. Ruta prevista,
          discontinua. Sin rumbo conocido, círculo en vez de triángulo.
        </p>
      </div>
    </div>
  )
}
