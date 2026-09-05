/* GENERADO por 'npm run gen:types' desde contracts/oracle_recommendation_v1.schema.json. NO editar a mano. */

/**
 * Una decision del Oraculo Matematico (Adaptive Slow Steaming). Es la frontera de contrato entre api/ (escribe) y frontend/ (solo lee): viaja en la columna `payload` (jsonb) de la tabla `oracle_recommendations`.
 *
 * EXTRAIDO, no inventado: derivado de construir_evento_contrato() en api/app/agents/math_oracle.py (feature/math_oracle @ dbe92d0) y verificado contra 11 eventos reales del grafo, grabados en frontend/src/mock/events.json.
 *
 * Se emite una vez cada 30 min por buque mientras esta a <12 h de su puerto destino, asi que una misma aproximacion genera varios eventos con el mismo session_id.
 */
export interface OracleRecommendationV1 {
  /**
   * ULID. Es el correlation_id del webhook de Flink, asi que sirve de clave de idempotencia: un reintento no duplica fila (ON CONFLICT DO NOTHING en db_conn.guardar_recomendacion).
   */
  event_id: string;
  /**
   * ULID que agrupa una misma aproximacion buque-puerto. Se hereda de la ultima recomendacion del mismo mmsi+puerto dentro de 24 h; si no hay ninguna, empieza uno nuevo. Es la clave para leer una aproximacion completa y ver como evoluciono la recomendacion.
   */
  session_id: string;
  /**
   * Instante en que el oraculo construyo el evento.
   */
  emitted_at: string;
  schema_version: 1;
  vessel: {
    /**
     * OJO: numero aqui, pero la columna `mmsi` de la tabla es text. El frontal normaliza a string al entrar.
     */
    mmsi: number;
    /**
     * null si el AIS reporta 0 o el webhook no lo trae. Sin IMO no hay fila de thetis_mrv, y el CII cae a fallback_admiralty.
     */
    imo: number | null;
    /**
     * HOY SIEMPRE null. thetis_mrv.name existe y estimar_cii ya trae la fila completa por IMO, asi que es rellenable sin consultas nuevas (TODO 2). El frontal etiqueta por MMSI mientras siga null.
     */
    name: string | null;
    lat: number;
    lon: number;
    /**
     * SOG del AIS. El oraculo rechaza <= 0: no se puede calcular ruta ni ETA con el buque parado.
     */
    speed_kn: number;
    /**
     * Rumbo verdadero. null es frecuente (centinela 511 en ~27% del AIS real). Sin el, el frontal dibuja circulo y no triangulo: no se inventa rumbo.
     */
    heading: number | null;
    /**
     * Codigo AIS numerico (0 = en navegacion a motor, 1 = fondeado, 5 = amarrado).
     */
    nav_status: number | null;
    /**
     * ATENCION: el nombre miente. Hoy trae `paquete_1['puerto']`, que es el MISMO string que `port.name` (verificado: identicos en las 17 filas del fixture y de la tabla) y que el propio oraculo documenta como "solo un nombre para mostrar". NO es el destino crudo que teclea la tripulacion, que no llega al evento. Por eso el frontal no lo muestra: seria repetir el nombre del puerto bajo una etiqueta falsa. Pendiente en el oraculo: o emitir aqui el destino AIS de verdad —- que es el dato sucio e interesante— o retirar el campo por duplicado.
     */
    destination_raw: string | null;
    /**
     * ETA_static del webhook, cruda. El oraculo no la usa en ningun calculo.
     */
    eta_ais_raw: string | null;
    /**
     * Frescura real del fix. Se muestra siempre junto al buque: nunca se interpolan posiciones.
     */
    position_at: string;
    /**
     * Derivado del tipo normalizado del CII. null si no se pudo determinar.
     */
    is_container: boolean | null;
  };
  port: {
    /**
     * HOY SIEMPRE null: el webhook manda lat/lon del puerto y no se resuelve nombre->LOCODE contra la tabla ports. Sin el no se puede unir con `ports` ni unificar dos grafias del mismo puerto.
     */
    locode: string | null;
    /**
     * Nombre del puerto tal como llega del webhook (p.ej. "ALGECIRAS"). Es la etiqueta del mapa y la columna `puerto` de la tabla. Texto libre: dos grafias son dos puertos.
     */
    name: string;
    lat: number;
    lon: number;
    /**
     * HOY SIEMPRE null: lo define quien arma paquete_2 y el oraculo no lo conoce. Por eso el frontal NO dibuja el circulo de contexto: hacerlo exigiria inventarse el radio.
     */
    context_radius_nm: number | null;
    /**
     * Amarrados (nav_status 5). Ocupacion real de atraque.
     */
    berthed_count: number;
    /**
     * Fondeados (nav_status 1). Es la cola.
     */
    anchored_count: number;
    /**
     * En camino. OJO: INCLUYE al propio buque del evento, que aparece tambien en context_vessels.inbound. El frontal deduplica por mmsi y lo rotula.
     */
    inbound_count: number;
    /**
     * HOY SIEMPRE null: paquete_2 no trae timestamp propio. El frontal usa emitted_at y lo rotula como hora de emision, no como hora del contexto.
     */
    snapshot_at: string | null;
  };
  /**
   * El resto de la flota alrededor del puerto. Las esperas son MODELADAS por jit_calculus, no observadas por un tracker con estado: de ahi `estimated_wait_hours` y no `wait_hours`/`anchored_since`.
   */
  context_vessels: {
    berthed: ContextVessel[];
    anchored: WaitingVessel[];
    inbound: WaitingVessel[];
  };
  /**
   * Ruta navegable calculada por searoute: esquiva tierra. NO es la derrota observada — el frontal la dibuja punteada y la rotula como ruta prevista.
   */
  route: {
    distance_nm: number;
    /**
     * Horas de travesia A LA VELOCIDAD ACTUAL, informativo de searoute. No es el transito a la velocidad recomendada. Puesto junto a `queue.estimated_wait_hours` deja ver la decision JIT de un vistazo: tarda N horas en llegar y no hay atraque hasta la hora M.
     */
    duration_hours: number;
    /**
     * Orden de navegacion, [lon, lat] — misma convencion que el resto del pipeline. Su longitud coincide SIEMPRE con la de route_weather: el frontal tine cada tramo con el oleaje de su waypoint.
     *
     * @minItems 2
     */
    waypoints: [[number, number], [number, number], ...[number, number][]];
  };
  /**
   * Estado del mar en cada waypoint, a la hora estimada en que el buque pasara por el. Un elemento por waypoint, en el mismo orden. Es el elemento visual principal del frontal.
   */
  route_weather: {
    lat: number;
    lon: number;
    /**
     * ETA estimado en ESTE waypoint, acumulando distancia/velocidad.
     */
    eta: string;
    /**
     * Altura de ola en m. Open-Meteo devuelve null en celdas sin cobertura (tipicamente costeras); hoy eso hace fallar el evento completo (TODO 6).
     */
    wave_height: number | null;
    wave_direction: number | null;
    wave_period: number | null;
    wind_speed_kn: number | null;
    wind_direction: number | null;
    wind_gusts_kn: number | null;
  }[];
  /**
   * Posicion y espera de ESTE buque en la cola del puerto: la justificacion de frenar. Va a nivel raiz, hermano de `route` y `recommendation`, no dentro de la decision: describe el estado del mundo que la motiva, no la decision misma. Verificado contra las filas reales de oracle_recommendations.
   */
  queue: {
    estimated_wait_hours: number | null;
    queue_position: number | null;
    /**
     * Segmento de atraque al que opta el buque por su eslora (p.ej. "large"). Los atraques se agrupan por tamano, asi que la cola es por segmento, no por puerto.
     */
    berth_segment: string | null;
  };
  /**
   * La decision. NO trae `status` ni `confidence`: el oraculo expone las senales nativas del calculo y el frontal deriva severidad y fiabilidad en src/status.ts, en un solo sitio.
   */
  recommendation: {
    /**
     * Velocidad de motor constante para llegar cuando haya atraque libre (Kwon-Euler, corregida por meteo).
     */
    recommended_speed_kn: number;
    /**
     * Velocidad de diseno estimada del casco (cii_calculus). Es el numero que hace concreto a `excede_v_diseno`: sin el, el frontal solo puede decir «no llega a tiempo»; con el, «necesitaria 25,5 kn y su casco da 21,3».
     *
     * Opcional: las filas anteriores a que el oraculo lo emitiera no lo llevan.
     */
    design_speed_kn?: number | null;
    /**
     * recommended_speed_kn - speed_kn. Negativo = frenar (el caso JIT habitual); positivo = acelerar.
     */
    speed_delta_kn: number;
    /**
     * Horas de travesia a la velocidad RECOMENDADA (Kwon-Euler, corregidas por meteo). No confundir con `route.duration_hours`, que es a la velocidad actual.
     *
     * Es la pieza que permite cuantificar el fondeo de verdad: restandola a `queue.estimated_wait_hours` sale lo que el buque seguira fondeado SI sigue la recomendacion, y por diferencia con `idle_hours_avoided` -- que es el fondeo si no cambia nada -- las horas que la recomendacion evita realmente. Sin este campo el frontal solo podia decir «fondeara igual», sin numero.
     *
     * Opcional: las filas anteriores a que el oraculo lo emitiera no lo llevan.
     */
    estimated_transit_hours?: number | null;
    /**
     * ETA a la velocidad actual, sin contar colas. null si el webhook no manda ETA_dynamic.
     */
    eta_current: string | null;
    /**
     * ETA a la velocidad recomendada.
     */
    eta_optimized: string;
    /**
     * Horas que el buque pasaria fondeado SI NO CAMBIA NADA (`espera - ETA_dynamic`). OJO: el nombre engana, no son horas ahorradas — solo coinciden cuando el buque alcanza la ventana de atraque. Con `estimated_transit_hours` ya se puede calcular el ahorro real. null sin ETA_dynamic.
     */
    idle_hours_avoided: number | null;
    /**
     * Toneladas de combustible ahorradas. SOLO se rellena si thetis_mrv da un DWT REAL para ese IMO — nunca desde el DWT geometrico estimado. En la practica es null casi siempre: de los portacontenedores de la flota, ninguno tiene DWT real. Puede ser NEGATIVO (combustible extra) cuando la recomendacion es acelerar.
     */
    fuel_saved_t: number | null;
    /**
     * Justificacion en lenguaje natural. La genera un LLM (Gemini via inyeccion, o un resumen determinista si no hay clave) y es coherente entre avisos de la misma sesion, porque el prompt lleva las 3 recomendaciones anteriores. Se pinta como prosa.
     */
    rationale: string;
    /**
     * El texto de `rationale` NO viene del LLM: viene del resumen determinista de respaldo porque la llamada al modelo fallo (429 por rate limit, 5xx, model_id invalido). El calculo del oraculo -- ruta, meteo, CII, Kwon-Euler -- es el mismo y sigue siendo valido: lo unico degradado es el texto de acompanamiento, que es lo ultimo del pipeline.
     *
     * OJO con el sentido: `false` significa "no ha fallado nada", NO "esto lo escribio un LLM". Un despliegue sin GEMINI_API_KEY usa el resumen determinista desde el principio y emite `false`, porque no hay fallo que reportar.
     *
     * Opcional: las filas escritas antes de que el oraculo lo emitiera no lo llevan. Ausente se trata como `false`.
     */
    rationale_degradado?: boolean;
    /**
     * La biseccion de Kwon-Euler encontro una velocidad exacta dentro del rango realizable del casco ([0.4, 1.2] x velocidad de diseno).
     *
     * NO ES UN INDICADOR DE ERROR. false significa SATURACION, y hay dos casos opuestos que `nota` distingue: (a) sobra tiempo incluso a v_min -> se recomienda el minimo, que es el caso bueno del JIT y el mas frecuente; (b) la ventana no llega ni a v_max -> el buque llega tarde aunque vaya a tope. Usar convergio como senal de alerta marcaria casi todos los eventos.
     */
    convergio: boolean;
    /**
     * La velocidad recomendada supera la de diseno del casco: no es ejecutable. Solo puede ocurrir en el caso de ventana insuficiente.
     */
    excede_v_diseno: boolean;
    /**
     * El CII empeora con la velocidad JIT (cii.ahorro_pct < 0). Es la rama condicional que el propio grafo tomo hacia fetch_resumen_alerta, y esta promovido a columna en la tabla para poder filtrar sin abrir el jsonb.
     */
    alerta_cii: boolean;
    /**
     * Aviso de Kwon-Euler sobre su propia solucion, en texto libre. Se muestra SIEMPRE que no sea null: es la letra pequena del numero grande.
     */
    nota: string | null;
    cii: {
      /**
       * CII a la velocidad actual, en gCO2/(t.nm).
       */
      inicial: number | null;
      /**
       * CII a la velocidad recomendada, misma ruta.
       */
      jit: number | null;
      /**
       * Procedencia del CII. `eexi` sale del indicador declarado en thetis_mrv; `fallback_admiralty` de un DWT geometrico estimado desde las dimensiones del casco. NO son comparables entre buques, asi que el frontal lo muestra y degrada la fiabilidad cuando es fallback.
       */
      metodo: "eexi" | "fallback_admiralty";
      /**
       * Mejora porcentual del CII. Negativo = empeora, y entonces alerta_cii es true.
       */
      ahorro_pct: number | null;
    };
    /**
     * Perdida media de velocidad por meteo en esta ruta, en por ciento (correccion Kwon: `perdida_media_pct`). Cuanto castiga el mar al buque, y por tanto cuanta de la velocidad recomendada se la come la meteo en vez del motor.
     */
    weather_speed_loss_pct: number | null;
  };
}
export interface ContextVessel {
  /**
   * Llega tal cual venga en paquete_2, asi que puede ser numero o texto. El frontal normaliza a string.
   */
  mmsi: number | string;
  /**
   * HOY SIEMPRE null: paquete_2 no trae nombres.
   */
  name: string | null;
  lat: number | null;
  lon: number | null;
  /**
   * PENDIENTE (TODO 5). jit_calculus ya lo calcula pero no se propaga. Mientras no llegue, el frontal deduplica comparando con vessel.mmsi.
   */
  es_objetivo?: boolean | null;
}
/**
 * Buque del contexto que ademas espera: fondeados y en camino. Se declara completo en vez de heredar de ContextVessel con `allOf` — con `additionalProperties: false` cada rama del allOf valida por separado y la del padre rechazaba `estimated_wait_hours`.
 */
export interface WaitingVessel {
  /**
   * Llega tal cual venga en paquete_2, asi que puede ser numero o texto. El frontal normaliza a string.
   */
  mmsi: number | string;
  /**
   * HOY SIEMPRE null: paquete_2 no trae nombres.
   */
  name: string | null;
  lat: number | null;
  lon: number | null;
  /**
   * PENDIENTE (TODO 5). jit_calculus ya lo calcula pero no se propaga. Mientras no llegue, el frontal deduplica comparando con vessel.mmsi.
   */
  es_objetivo?: boolean | null;
  /**
   * Espera MODELADA por jit_calculus, no observada. El frontal la rotula como estimada.
   */
  estimated_wait_hours?: number | null;
}
