# Capa Oráculo — lógica de cálculo

> Anexo técnico a la memoria del TFM. Documenta **qué hace cada pieza del
> oráculo y por qué está hecha así**. La arquitectura de despliegue
> (Azure Functions, Supabase, ADLS) se describe en la memoria principal;
> aquí el foco es el razonamiento del cálculo.

---

## 1. Qué problema resuelve

Un buque que llega antes de que su atraque esté libre no entra antes: se queda
**fondeado esperando**. Ha quemado combustible para adelantar una espera. La
práctica de *Just-In-Time arrival* consiste en reducir la velocidad para llegar
justo cuando hay atraque, convirtiendo esa espera en ahorro de combustible y
emisiones sin perder el turno.

El oráculo automatiza esa decisión. Recibe un aviso de que un buque está a
menos de 12 h de un puerto y responde con:

- cuánto va a esperar realmente (posición en cola y horas),
- a qué velocidad debería navegar para llegar justo a tiempo,
- cuánto mejora su CII (indicador de intensidad de carbono) al hacerlo,
- y una explicación en lenguaje natural para el oficial de operaciones.

**Entrada** (webhook de Flink, dos paquetes):

| | Contenido |
|---|---|
| `paquete_1` | El buque que dispara la alerta: MMSI, IMO, posición, velocidad, dimensiones, puerto destino y sus coordenadas |
| `paquete_2` | Foto del puerto: listas de buques atracados, fondeados y en camino |

**Salida**: un evento JSON (`oracle_recommendation_v1`) que se publica en
Supabase (fuente de verdad, lo consume el frontal) y en ADLS Gen2 (copia
analítica para Databricks).

---

## 2. El pipeline

Implementado como un **grafo de LangGraph** (`app/agents/math_oracle.py`).
Cada nodo es una función pura sobre un estado compartido:

```
paquete_1 + paquete_2
        │
        ├─ 1. fetch_datos_buque      normaliza la entrada
        ├─ 2. fetch_route            ruta navegable y distancia
        ├─ 3. fetch_weather          olas y viento sobre la ruta
        ├─ 4. fetch_cii_inicial      CII a la velocidad actual
        ├─ 5. fetch_tiempo_espera    posición en cola y horas de espera
        ├─ 6. fetch_velocidad_jit    velocidad para llegar justo a tiempo
        ├─ 7. fetch_cii_jit          CII a la velocidad recomendada
        ├─ 8. build_informe          compara ambos escenarios
        ├─ 9. fetch_historial        avisos previos del mismo buque
        │
        ├─ 10. decidir_resumen  ─────┐  (arista condicional)
        │        ¿el CII mejora?     │
        │      sí ↓            no ↓  │
        │   resumen_ahorro   resumen_alerta
        │                            │
        └─ 11. publicar_recomendacion ┘
```

**Por qué un grafo y no una función encadenada.** El orden de dependencias es
real y no arbitrario: la meteo necesita la ruta, la velocidad JIT necesita la
espera *y* la meteo, el CII final necesita la velocidad. Un grafo hace ese
orden explícito y verificable. Además, la decisión "¿el CII mejora o empeora?"
es una **arista condicional real**, no un `if` escondido dentro de una
función: el grafo expresa que hay dos caminos distintos, no un texto que
cambia.

**Por qué sin *tool-calling*.** El pipeline es determinista: dada la misma
entrada produce la misma salida. Dejar que un LLM decidiera qué calcular y en
qué orden introduciría variabilidad en un cálculo de ingeniería sin aportar
nada. El LLM interviene **solo al final**, para redactar; nunca para decidir.

---

## 3. Las piezas

### 3.1 `sea_route.py` — ruta navegable

Calcula la ruta marítima real entre el buque y el puerto sobre el grafo de
corredores navegables de la librería `searoute`, devolviendo distancia y
*waypoints* intermedios.

**Por qué no la distancia en línea recta.** Un buque no atraviesa penínsulas.
La diferencia entre la distancia ortodrómica y la navegable puede ser enorme
en el Mediterráneo, y como la velocidad JIT sale de dividir distancia entre
tiempo, ese error se propagaría directamente a la recomendación.

Los *waypoints* no son un subproducto: son los puntos donde se consulta la
meteo, y los tramos sobre los que se integra el tiempo de tránsito.

### 3.2 `open_meteo.py` — meteo a lo largo de la ruta

Consulta dos APIs de Open-Meteo (marina para el oleaje, estándar para el
viento) **en cada waypoint y en el instante estimado de paso por él**, no
sobre una posición y hora únicas.

**Por qué así.** Una travesía de 300 millas dura más de un día. La meteo que
encontrará el buque a mitad de camino, mañana, no es la que hay ahora en su
posición actual. Interesa el estado del mar *donde y cuando* va a estar.

Los campos se modelan como `list[float | None]`: Open-Meteo devuelve `null` en
celdas costeras que el modelo de oleaje no cubre. Tratarlos como obligatorios
hacía caer el evento entero por no tener el dato de un solo tramo.

### 3.3 `jit_calculus.py` — cuánto va a esperar

**La pieza central**, y la que más determina el resultado. Modela el puerto
como un **sistema de colas M/G/c segmentado**.

**Segmentación por eslora.** Los atraques no son intercambiables: un buque de
340 m no cabe en un muelle dimensionado para 120 m. Se definen cuatro
segmentos (`small` <150 m, `medium` 150-250, `large` 250-350, `vlarge` >350) y
cada buque compite solo dentro del suyo. Sin esto, un puerto con muchos
atraques pequeños libres parecería descongestionado para un portacontenedores
grande que en realidad no puede usar ninguno.

**Tiempo de servicio por tipo de buque.** Cuánto ocupa el atraque depende de
la operativa, no del tamaño: un portacontenedores descarga en ~28 h, un
granelero en ~42 h, un tanque en ~49 h. Los valores proceden de literatura
sobre AIS (ver §6) y se corrigen por eslora (`FACTOR_ESLORA`), porque un buque
más grande mueve más carga.

**Tiempo hasta que se libera un atraque.** Aquí hay un punto sutil. Sabiendo
que un servicio dura de media μ horas, ¿cuánto le queda al buque que está
ahora atracado? La respuesta intuitiva, μ/2, **es incorrecta**: es la *paradoja
de la inspección*. Al observar en un instante cualquiera es más probable caer
dentro de un servicio largo que de uno corto, así que el tiempo restante está
sesgado hacia arriba. La fórmula correcta del residual es:

$$E[R] = \frac{\mu}{2}\left(1 + CV^2\right)$$

donde CV es el coeficiente de variación del servicio. Con la variabilidad real
de un tanque (CV ≈ 0,49), esto da un residual **24 % mayor** que la
aproximación ingenua. Con *c* atraques ocupados, el primero en liberarse llega
antes: E[R] / c.

**Tiempo total de espera.** Para el buque en posición *pos* de la cola:

```
t_espera = t_liberación + (pos − 1) · (μ / c) + t_maniobra
```

El término central es una aproximación **fluida**: los atraques se van
liberando de forma continua a ritmo μ/c. La alternativa —suponer que los *c*
atraques se vacían a la vez, por tandas— infraestimaba mucho la espera de las
posiciones intermedias. `t_maniobra` (1 h) es el tiempo medido de la maniobra
fondeo↔atraque.

**Resolución del tipo de buque**, en cascada de más a menos fiable:
1. Texto explícito, si viene.
2. **IMO → consulta a `thetis_mrv`** (registro oficial de emisiones de la UE),
   resuelta en lote para todo el puerto en una sola query.
3. Código numérico AIS (ITU-R M.1371) como último recurso.

La tercera vía es notablemente más pobre: AIS agrupa todo el carguero en
"Cargo" (70-79), sin distinguir granelero de portacontenedores o Ro-Ro, que
tienen tiempos de servicio muy distintos. Por eso el IMO va antes.

> **Limitación conocida.** El número real de atraques por segmento no está
> disponible en ninguna fuente conectada, y se infiere como
> `ceil(atracados_visibles × 1,2)` (ocupación ~83 %, coherente con el umbral
> de congestión del 85 % que cita UNCTAD). Como AIS solo ve una fracción de
> los buques realmente atracados, **la capacidad sale infraestimada y las
> esperas resultan artificialmente largas**. Es la limitación más relevante
> del modelo y afecta a todo lo que viene después. Ver §5.

### 3.4 `kwon_euler.py` — a qué velocidad navegar

Resuelve el **problema inverso**: conocido el tiempo disponible, ¿qué
velocidad de motor constante hace que el buque llegue exactamente entonces?

**Por qué no basta con dividir distancia entre tiempo.** El mar frena al
buque. Con oleaje y viento de proa, la velocidad efectiva sobre el fondo es
menor que la de motor, y la diferencia depende del estado del mar, del ángulo
relativo y de la forma del casco. Ordenar "navega a 8 nudos" cuando el mar le
va a quitar un 15 % significa llegar tarde y perder el atraque.

Tres mecanismos combinados:

1. **Método de Kwon (2008)** — estima el porcentaje de pérdida de velocidad
   por resistencia añadida en función del número de **Beaufort**, el **ángulo
   relativo** entre el rumbo y la meteo, y el **coeficiente de bloque** del
   casco. Es empírico y está pensado precisamente para estimaciones a nivel de
   viaje.
2. **Integración de Euler** — la ruta se recorre tramo a tramo entre
   waypoints; cada tramo aplica *su* pérdida (la meteo de ese punto y ese
   momento) y se acumula el tiempo. Un promedio único de la meteo perdería
   justo lo que importa: que el mal tiempo se concentra en un tramo concreto.
3. **Bisección** — se busca la velocidad de motor cuyo tiempo integrado iguala
   el objetivo.

**Por qué velocidad constante.** Variar de régimen consume más que mantenerlo
estable, y una recomendación operativa tiene que ser ejecutable por un
tripulante.

**Por qué el rango de búsqueda se acota** a [0,4 – 1,2] × velocidad de diseño
*de ese buque*: con un rango genérico, la bisección puede converger sin avisar
a velocidades imposibles para ese casco. Cuando no hay solución dentro del
rango, el resultado se marca `convergio: false` con una nota explicando si
sobra tiempo (ni al mínimo llega tan tarde) o falta (ni al máximo llega a
tiempo). **No se inventa un número plausible.**

### 3.5 `cii_calculus.py` — cuánto CO₂ ahorra

Calcula el CII (gramos de CO₂ por tonelada y milla) en dos escenarios: a la
velocidad actual y a la recomendada. La comparación es la métrica que
justifica la recomendación.

Dos vías, según los datos disponibles:

**Vía EEXI** (preferente). Si `thetis_mrv` tiene el índice de eficiencia real
del buque:

$$CII \approx EEXI \cdot \left(\frac{V_{actual}}{V_{diseño}}\right)^2$$

Se apoya en un dato medido y declarado del buque concreto.

**Vía coeficiente de Almirantazgo** (respaldo). Si no hay EEXI, se estima el
desplazamiento desde las dimensiones del casco y su coeficiente de bloque, y
la potencia con:

$$P \approx \frac{\Delta^{2/3} \cdot V^3}{C_{adm}}$$

De la potencia se pasa a consumo (190 g/kWh) y a CO₂ (3,114 g CO₂/g fuel).

La **dependencia cúbica con la velocidad** es la razón física de que todo esto
funcione: reducir un 20 % la velocidad baja la potencia cerca de un 50 %.

> **Detalle de unidades.** Los coeficientes de Almirantazgo tabulados están
> calibrados para **V en nudos**. Usar m/s en la potencia cúbica introduce un
> factor de error de ~7,3× (subestimando el consumo). Es un fallo silencioso,
> porque el resultado sigue pareciendo razonable.

`fuel_saved_t` solo se rellena cuando `thetis_mrv` aporta un **DWT real**;
nunca con el DWT estimado geométricamente, que arrastra la misma
incertidumbre que el método de respaldo. Si no hay dato real, va a `null`
antes que dar una cifra de toneladas ahorradas que no se sostiene.

### 3.6 `informe_llm.py` + `llm_provider.py` — la explicación

Traduce el resultado numérico a un texto breve para un oficial de
operaciones, con el historial de avisos previos del mismo buque como contexto
(la alerta se repite mientras el buque se aproxima, y los mensajes sucesivos
deben ser coherentes entre sí).

**Dos funciones simétricas, no una con un `if`.** `resumen_ahorro` y
`resumen_alerta` son casos distintos: el segundo ocurre cuando la ventana es
tan ajustada que el buque debe **acelerar**, y el CII empeora. No es un error
de cálculo, y el texto debe decirlo sin disfrazarlo de éxito.

**Degradación en cascada** (`llm_provider.py`):

```
Gemini (gratuito)  →  Azure AI Foundry (de pago)  →  resumen determinista
```

Cada escalón se prueba solo si el anterior falla. Y "falla" incluye devolver
texto vacío, no solo lanzar una excepción: Gemini devuelve `None` sin error
cuando el filtro de seguridad bloquea la respuesta.

**Por qué esta cascada.** El resumen es lo último del pipeline: cuando se
llama, ya se han pagado la ruta, la meteo, el CII y la velocidad JIT. Dejar
que un límite de cuota tire todo ese trabajo por el texto de acompañamiento
sería absurdo. El último escalón no usa LLM y siempre funciona; el evento se
marca con `rationale_degradado: true` para que el consumidor sepa que la
redacción es de plantilla —aunque el cálculo sea igual de válido.

`informe_llm` **no importa ningún SDK**: recibe una función
`prompt → texto`. Cambiar de proveedor no toca la lógica de negocio.

### 3.7 `db_conn.py` y `adls_conn.py` — persistencia

Dos destinos con papeles distintos:

- **Supabase** (`oracle_recommendations_*`) — **fuente de verdad**. Sirve al
  frontal y es el historial que da contexto al LLM en el siguiente aviso.
- **ADLS Gen2** — copia analítica para Databricks, en JSON particionado por
  día (`{entorno}/dt=YYYY-MM-DD/{event_id}.json`).

**El orden importa**: primero Supabase, y ADLS **solo si aquella confirma**.
Si la fuente de verdad no tiene el evento, la capa analítica tampoco debe
tenerlo.

**Idempotencia.** `event_id` es el `correlation_id` del webhook: en Supabase
va como `ON CONFLICT DO NOTHING`, y en ADLS el nombre del blob es ese mismo
id, de modo que reescribir sobrescribe. Un reintento no duplica nada.

**Ningún fallo de persistencia tumba el grafo**: se registra y se devuelve el
resultado igual. Perder el cálculo entero por un problema de red sería peor
que no publicarlo.

### 3.8 `config.py` — separación de entornos

Una sola variable, `NAUTIQ_ENV`, decide **los dos destinos a la vez**:

| | `DEV` | `PRO` |
|---|---|---|
| Tabla | `oracle_recommendations_dev` | `oracle_recommendations_prod` |
| Carpeta ADLS | `dev/` | `prod/` |

**Tablas separadas y no una columna `entorno`**: así el aislamiento no depende
de que ninguna consulta se acuerde de filtrar. Una credencial mal apuntada
escribe en la tabla equivocada, pero no ensucia los datos buenos.

### 3.9 `function_app.py` — el webhook

Expone `POST /api/alerta` y `GET /api/health`.

**Procesamiento síncrono**, no en segundo plano. El anfitrión puede reciclar
la instancia en cuanto sale la respuesta HTTP, así que un hilo de fondo se
perdería en silencio, sin traza ni reintento. El cálculo tarda segundos y el
tiempo límite es de minutos.

Los códigos de respuesta distinguen casos:

| | |
|---|---|
| **200** | Recomendación calculada y publicada |
| **400** | Cuerpo mal formado |
| **422** | Alerta no aplicable (buque atracado o parado) |
| **500** | Fallo real del pipeline |

El **422** es deliberado: un buque parado no es un error del sistema, es una
alerta que no procede. Quien llama no debe reintentarla.

---

## 4. Principios transversales

**Fallar pronto y con contexto, o degradar explícitamente.** Cada punto de
fallo se clasifica: lo que invalida el resultado corta con un error tipado
(`BuqueNoNavegandoError`); lo que solo lo empobrece degrada y lo marca en el
evento (`rationale_degradado`, `convergio`, `fuel_saved_t: null`). Lo que no
se hace nunca es rellenar un hueco con un valor plausible.

**Cada dato calculado una sola vez.** La ficha de `thetis_mrv` se consulta una
vez y se reutiliza; las estimaciones de cola de todo el puerto salen de una
única pasada. No es solo eficiencia: recalcular abre la puerta a que dos
partes del mismo evento discrepen.

**El evento publicado incluye su propia justificación** — posición en cola,
espera, buques del contexto, meteo de la ruta, si convergió — para que la
recomendación sea auditable y el frontal pueda explicar *por qué* frenar.

---

## 5. Limitaciones conocidas

Documentadas por honestidad metodológica: afectan a cómo deben leerse los
resultados.

1. **Capacidad de atraque inferida** (§3.3). Es la más importante. AIS solo ve
   parte de los buques atracados, así que la capacidad sale corta y las
   esperas largas. En casos extremos el solver no converge y recomienda
   acelerar al máximo (velocidades por encima de lo físicamente razonable).
   Se resolvería con datos reales de infraestructura portuaria, no
   disponibles en el TFM.
2. **Kwon aproximado.** El artículo original publica una tabla; aquí se usa un
   ajuste polinómico que reproduce el orden de magnitud, no los valores
   exactos.
3. **Tipos de buque desde AIS.** Cuando falta el IMO, la granularidad de AIS
   no distingue operativas con tiempos de servicio muy distintos.
4. **Sin `locode` de puerto.** No hay tabla nombre→locode conectada; el evento
   lo publica como `null`.

---

## 6. Referencias

- Ma, Zhou & Zhu (2023). *Identification and analysis of ship waiting behavior
  outside the port based on AIS data*. Scientific Reports 13:11267.
- Wijaya & Nakamura (2024). *Port performance indicators construction based on
  AIS-generated trajectory segmentation and classification*.
- Wu & Aarsnes (2017). *An Introduction to Assessing Bunkering Operations
  Through AIS Data*. NTNU.
- Kwon, Y.J. (2008). *Speed loss due to added resistance in wind and waves*.
  The Naval Architect.
- Watson, D.G.M. *Practical Ship Design*. Elsevier.
- Molland, Turnock & Hudson. *Ship Resistance and Propulsion*. Cambridge UP.
- Schneekluth & Bertram. *Ship Design for Efficiency and Economy*.
  Butterworth-Heinemann.
- ITU-R M.1371-5, tabla 53 — *Type of ship and cargo type* (códigos AIS).
- IMO — marco de EEXI y CII.

---

## 7. Estructura del código

```
api/
├── function_app.py              webhook (Azure Functions)
├── app/
│   ├── config.py                entorno → tabla y carpeta
│   └── agents/
│       ├── math_oracle.py       el grafo LangGraph
│       └── tools/
│           ├── sea_route.py     ruta navegable
│           ├── open_meteo.py    meteo por waypoint
│           ├── jit_calculus.py  colas de puerto
│           ├── kwon_euler.py    velocidad JIT
│           ├── cii_calculus.py  emisiones
│           ├── informe_llm.py   prompts y resúmenes
│           ├── llm_provider.py  cascada de proveedores
│           ├── gemini_client.py / foundry_client.py
│           ├── db_conn.py       Supabase
│           └── adls_conn.py     ADLS Gen2
└── scripts/
    ├── replay_alertas.py        reproduce alertas reales end-to-end
    ├── empaquetar.py            construye el paquete de despliegue
    ├── desplegar.py             despliegue a Azure
    └── verificar_despliegue.py  comprobación post-despliegue
```
