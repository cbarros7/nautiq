/**
 * Entorno del despliegue y tabla de la que se lee.
 *
 * Espejo de `api/app/config.py`: MISMA convención, mismos nombres de tabla, mismo override.
 * No es una convención propia del frontal —- si divergen, un despliegue lee la tabla del otro.
 *
 *   NAUTIQ_ENV = DEV  ->  oracle_recommendations_dev
 *   NAUTIQ_ENV = PRO  ->  oracle_recommendations_prod
 *
 * Dos detalles que se copian del oráculo y conviene no "arreglar" por cuenta propia:
 *
 * - El entorno va como **sufijo**, no como prefijo, y `PRO` es `prod` (no `pro`), igual que
 *   los topics de Kafka en Aiven.
 * - **Solo DEV y PRO.** `ingestion` admite además PRE, pero el oráculo no tiene entorno de
 *   preproducción propio y por tanto no existe la tabla. Aceptar PRE aquí daría un frontal
 *   apuntando a una tabla inexistente, que es peor que rechazarlo.
 *
 * Las dos tablas viven en el MISMO proyecto de Supabase, así que las dos Static Web Apps
 * comparten `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY`: lo único que las diferencia es
 * `VITE_NAUTIQ_ENV`.
 */
export type Entorno = 'DEV' | 'PRO'

const TABLA_POR_ENTORNO: Record<Entorno, string> = {
  DEV: 'oracle_recommendations_dev',
  PRO: 'oracle_recommendations_prod',
}

/** Mismo patrón que valida el oráculo antes de interpolar el nombre en su SQL. */
const NOMBRE_VALIDO = /^[a-z_][a-z0-9_]*$/

function leerEntorno(): Entorno {
  const v = (import.meta.env.VITE_NAUTIQ_ENV ?? 'DEV').trim().toUpperCase()
  if (v === 'PRO') return 'PRO'
  if (v !== 'DEV' && v !== '') {
    // No se lanza: un frontal que no arranca es peor que uno que arranca en DEV avisando.
    console.warn(
      `VITE_NAUTIQ_ENV=${v} no es válido (solo DEV o PRO, como en api/app/config.py). ` +
      'Se usa DEV.',
    )
  }
  return 'DEV'
}

export const ENTORNO: Entorno = leerEntorno()

/**
 * Tabla que lee el frontal. El override existe por el mismo motivo que en el oráculo
 * (`ORACLE_RECOMMENDATIONS_TABLE`): poder corregir el nombre sin volver a desplegar.
 * Se valida con el mismo patrón; un nombre raro se descarta en vez de acabar en la consulta.
 */
function resolverTabla(): string {
  const override = import.meta.env.VITE_ORACLE_RECOMMENDATIONS_TABLE?.trim()
  if (override) {
    if (NOMBRE_VALIDO.test(override)) return override
    console.warn(
      `VITE_ORACLE_RECOMMENDATIONS_TABLE=${override} inválido (solo minúsculas, dígitos y ` +
      'guion bajo). Se usa el nombre del entorno.',
    )
  }
  return TABLA_POR_ENTORNO[ENTORNO]
}

export const TABLA: string = resolverTabla()
export const TABLA_FIJADA = TABLA !== TABLA_POR_ENTORNO[ENTORNO]

export const ETIQUETA_ENTORNO: Record<Entorno, string> = {
  DEV: 'Desarrollo',
  PRO: 'Producción',
}

/** Producción se señala distinto: hay que saber sin pensarlo que los datos son reales. */
export const ES_PRODUCCION = ENTORNO === 'PRO'
