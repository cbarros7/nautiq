/**
 * Aviso de llegada: sonido sintetizado + señal visual.
 *
 * El sonido se genera con Web Audio, sin fichero de audio: no hay que servir un binario, no
 * hay peticion que pueda fallar y el timbre se ajusta en el codigo. Son dos notas cortas —-
 * suficiente para levantar la vista, corto para no molestar en una sala.
 *
 * Sobre el bloqueo de autoplay: el navegador no deja sonar nada hasta que el usuario
 * interactua con la pagina, asi que el AudioContext nace suspendido y se reanuda en el
 * primer clic. Mientras tanto la senal visual funciona igual: el aviso nunca depende solo
 * del audio, que ademas puede estar en silencio o el usuario no llevar altavoces.
 */
const CLAVE = 'nautiq.sonido'

let ctx: AudioContext | null = null
let desbloqueado = false

function contexto(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (!ctx) {
    const AC = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AC) return null           // navegador sin Web Audio: solo senal visual
    try { ctx = new AC() } catch { return null }
  }
  return ctx
}

/**
 * Se engancha al primer gesto del usuario, que es lo unico que permite reanudar el audio.
 * Idempotente: se puede llamar en cada render sin coste.
 */
export function prepararAudio(): void {
  if (desbloqueado || typeof window === 'undefined') return
  const abrir = () => {
    desbloqueado = true
    contexto()?.resume().catch(() => {})
    window.removeEventListener('pointerdown', abrir)
    window.removeEventListener('keydown', abrir)
  }
  window.addEventListener('pointerdown', abrir, { once: true })
  window.addEventListener('keydown', abrir, { once: true })
}

export function sonidoActivo(): boolean {
  try { return localStorage.getItem(CLAVE) !== 'off' } catch { return true }
}

export function guardarSonido(activo: boolean): void {
  try { localStorage.setItem(CLAVE, activo ? 'on' : 'off') } catch { /* modo privado */ }
}

function nota(c: AudioContext, hz: number, inicio: number, dur: number, vol: number): void {
  const osc = c.createOscillator()
  const gan = c.createGain()
  osc.type = 'sine'
  osc.frequency.value = hz
  // Envolvente suave: un oscilador cortado en seco chasquea.
  gan.gain.setValueAtTime(0, inicio)
  gan.gain.linearRampToValueAtTime(vol, inicio + 0.012)
  gan.gain.exponentialRampToValueAtTime(0.0001, inicio + dur)
  osc.connect(gan).connect(c.destination)
  osc.start(inicio)
  osc.stop(inicio + dur + 0.02)
}

function emitir(c: AudioContext, critico: boolean): void {
  const t = c.currentTime + 0.02
  if (critico) {
    nota(c, 440, t, 0.16, 0.16)
    nota(c, 370, t + 0.17, 0.16, 0.16)
    nota(c, 294, t + 0.34, 0.28, 0.16)
  } else {
    nota(c, 784, t, 0.13, 0.12)
    nota(c, 1046, t + 0.11, 0.26, 0.11)
  }
}

/**
 * Dos timbres, no uno: lo que no es ejecutable suena distinto, para que se distinga sin
 * mirar. El resto comparte tono —- no hace falta un timbre por estado.
 *
 * Si el contexto sigue suspendido se reanuda y se emite al resolverse, en vez de descartar
 * el aviso: `prepararAudio` llama a `resume()` en el primer gesto, pero es asincrono, asi
 * que un aviso disparado por ese mismo gesto llegaria antes de que el contexto este listo
 * y se perderia justo el primero.
 */
export function reproducirAviso(critico: boolean): void {
  if (!sonidoActivo()) return
  const c = contexto()
  if (!c) return
  if (c.state === 'suspended') {
    c.resume().then(() => emitir(c, critico)).catch(() => {})
    return
  }
  emitir(c, critico)
}
