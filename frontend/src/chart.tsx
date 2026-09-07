/**
 * Gráfico de línea de UNA serie, en SVG. Se usa como múltiplo pequeño.
 *
 * Por qué una sola serie y varios gráficos en vez de uno con dos ejes: ola en metros
 * y viento en nudos son medidas de escalas distintas, y superponerlas en un plano con
 * dos ejes y inventa una correlación que no está en los datos. Dos gráficos, un eje
 * cada uno. Lo mismo en la sesión: velocidad en nudos y ahorro de CII en por ciento
 * van separados.
 *
 * Especificaciones de marca que se respetan: línea de 2 px, cuadrícula y ejes
 * recesivos, relleno de área tenue, extremo final enfatizado, marcador del punto
 * actual >= 8 px, y capa de hover con retícula y tooltip — que en un gráfico HTML no
 * es un extra, es lo que se espera.
 */
import { useRef, useState, type ReactNode } from 'react'

export interface Punto {
  x: number
  y: number | null
  etiqueta: string
}

interface Props {
  titulo: string
  unidad: string
  puntos: Punto[]
  color: string
  /** Índice a destacar con un marcador (p.ej. la posición actual del buque). */
  destacado?: number | null
  /** Fuerza el 0 en el eje. Para porcentajes con signo se usa una línea de base. */
  incluirCero?: boolean
  /** Se dibuja una línea de base en este valor (p.ej. 0 en un delta). */
  base?: number | null
  alto?: number
  pie?: ReactNode
}

const W = 384
const M = { arriba: 10, derecha: 10, abajo: 20, izquierda: 34 }

export function LineChart({
  titulo, unidad, puntos, color, destacado = null,
  incluirCero = false, base = null, alto = 116, pie,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)

  const validos = puntos.filter((p) => p.y !== null) as (Punto & { y: number })[]
  if (validos.length < 2) {
    return (
      <figure className="gr">
        <figcaption className="gr-titulo">{titulo}</figcaption>
        <p className="gr-vacio">Sin datos suficientes para trazar la serie.</p>
      </figure>
    )
  }

  const H = alto
  const xs = validos.map((p) => p.x)
  const ys = validos.map((p) => p.y)
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  let yMin = Math.min(...ys), yMax = Math.max(...ys)
  if (incluirCero) { yMin = Math.min(0, yMin); yMax = Math.max(0, yMax) }
  if (base !== null) { yMin = Math.min(base, yMin); yMax = Math.max(base, yMax) }
  if (yMax === yMin) { yMax += 1; yMin -= 1 }
  const pad = (yMax - yMin) * 0.12
  yMin -= pad; yMax += pad

  const px = (x: number) => M.izquierda + ((x - xMin) / (xMax - xMin || 1)) * (W - M.izquierda - M.derecha)
  const py = (y: number) => M.arriba + (1 - (y - yMin) / (yMax - yMin)) * (H - M.arriba - M.abajo)

  const linea = validos.map((p, i) => `${i === 0 ? 'M' : 'L'}${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join('')
  const area = `${linea}L${px(validos[validos.length - 1]!.x).toFixed(1)},${py(yMin).toFixed(1)}` +
               `L${px(validos[0]!.x).toFixed(1)},${py(yMin).toFixed(1)}Z`

  const ticksY = [yMin + pad, (yMin + yMax) / 2, yMax - pad]
  const ultimo = validos[validos.length - 1]!
  const puntoHover = hover !== null ? validos[hover] : null

  function alMover(e: React.PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current
    if (!svg) return
    const r = svg.getBoundingClientRect()
    const xVista = ((e.clientX - r.left) / r.width) * W
    let mejor = 0, dMejor = Infinity
    validos.forEach((p, i) => {
      const d = Math.abs(px(p.x) - xVista)
      if (d < dMejor) { dMejor = d; mejor = i }
    })
    setHover(mejor)
  }

  return (
    <figure className="gr">
      <figcaption className="gr-titulo">
        {titulo} <span className="gr-unidad">{unidad}</span>
      </figcaption>
      <svg
        ref={svgRef}
        className="gr-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${titulo} (${unidad}). ${validos.length} puntos, de ${ys[0]!.toFixed(1)} a ${ultimo.y.toFixed(1)}.`}
        onPointerMove={alMover}
        onPointerLeave={() => setHover(null)}
      >
        {ticksY.map((t, i) => (
          <g key={i}>
            <line className="gr-rejilla" x1={M.izquierda} x2={W - M.derecha} y1={py(t)} y2={py(t)} />
            <text className="gr-tick" x={M.izquierda - 6} y={py(t)} textAnchor="end" dominantBaseline="middle">
              {Math.abs(t) >= 100 ? t.toFixed(0) : t.toFixed(1)}
            </text>
          </g>
        ))}
        {base !== null && (
          <line className="gr-base" x1={M.izquierda} x2={W - M.derecha} y1={py(base)} y2={py(base)} />
        )}

        <path d={area} fill={color} opacity={0.14} />
        <path d={linea} fill="none" stroke={color} strokeWidth={2}
              strokeLinecap="round" strokeLinejoin="round" />

        {/* Extremo final enfatizado. */}
        <circle cx={px(ultimo.x)} cy={py(ultimo.y)} r={3.5} fill={color}
                stroke="var(--superficie)" strokeWidth={2} />

        {destacado !== null && validos[destacado] && (
          <circle className="gr-destacado"
                  cx={px(validos[destacado]!.x)} cy={py(validos[destacado]!.y)}
                  r={5} fill="none" stroke="var(--tinta)" strokeWidth={2} />
        )}

        <line className="gr-eje" x1={M.izquierda} x2={W - M.derecha}
              y1={H - M.abajo} y2={H - M.abajo} />
        <text className="gr-tick" x={M.izquierda} y={H - 6}>{validos[0]!.etiqueta}</text>
        <text className="gr-tick" x={W - M.derecha} y={H - 6} textAnchor="end">{ultimo.etiqueta}</text>

        {puntoHover && (
          <g className="gr-hover">
            <line className="gr-reticula" x1={px(puntoHover.x)} x2={px(puntoHover.x)}
                  y1={M.arriba} y2={H - M.abajo} />
            <circle cx={px(puntoHover.x)} cy={py(puntoHover.y)} r={4.5} fill={color}
                    stroke="var(--superficie)" strokeWidth={2} />
          </g>
        )}
      </svg>
      <div className="gr-pie">
        {puntoHover
          ? <span className="gr-lectura">
              <b>{puntoHover.y.toFixed(2)}</b> {unidad} · {puntoHover.etiqueta}
            </span>
          : pie ?? <span className="gr-lectura gr-lectura-inerte">Pasa el cursor para leer valores</span>}
      </div>
    </figure>
  )
}
