# Catálogos AIS: tipo de buque y estado de navegación

Referencia de los dos campos codificados que Nautiq transporta en crudo desde AIS.
Ambos son códigos numéricos del estándar **ITU-R M.1371**; el productor no los
interpreta, solo los valida y publica, así que traducirlos es responsabilidad de Flink.

| Campo | Mensaje AIS | Contrato Avro | Topic |
|-------|-------------|---------------|-------|
| `ship_type` | `ShipStaticData` (tipo 5) | `contracts/ais_static_v1.avsc` | `vessel.static.raw` |
| `nav_status` | `PositionReport` (tipos 1/2/3) | `contracts/ais_position_v1.avsc` | `vessel.positions.raw` |

Las distribuciones que aparecen más abajo están **medidas sobre el flujo real** de
Nautiq (`AIS_COVERAGE_BBOX`, ventana de 120 s), no son teóricas.

---

## 1. Tipo de buque (`ship_type`)

Entero de 0 a 99 que se lee como **dos dígitos**: el primero indica la categoría y el
segundo, en los rangos agrupados, el tipo de mercancía peligrosa que transporta.

### 1.1. Rangos agrupados

| Rango | Categoría |
|-------|-----------|
| 20-29 | Wing in ground (WIG), embarcación de efecto suelo |
| 40-49 | High speed craft (HSC), nave de alta velocidad |
| 60-69 | **Pasaje** |
| 70-79 | **Carga** |
| 80-89 | **Tanque** (petroleros, quimiqueros, gaseros) |
| 90-99 | Otros tipos |

En esos seis rangos, el **segundo dígito** significa siempre lo mismo:

| 2º dígito | Significado |
|-----------|-------------|
| 0 | Todos los buques de esta categoría (sin detalle) |
| 1 | Transporta mercancía peligrosa (DG/HS/MP), categoría IMO **A** (o **X** en MARPOL Anexo II) |
| 2 | Ídem, categoría **B** (o **Y**) |
| 3 | Ídem, categoría **C** (o **Z**) |
| 4 | Ídem, categoría **D** (o **OS**) |
| 5-8 | Reservado |
| 9 | Sin información adicional |

Así, `71` es *carga con mercancía peligrosa categoría A* y `79` es *carga sin
información adicional*. Ambos son carga: **el primer dígito es lo que define el tipo**.

### 1.2. Códigos individuales

| Código | Significado |
|--------|-------------|
| 0 | No disponible (valor por defecto) |
| 1-19 | Reservado |
| 30 | Pesca |
| 31 | Remolque |
| 32 | Remolque: eslora > 200 m o manga > 25 m |
| 33 | Dragado u operaciones submarinas |
| 34 | Operaciones de buceo |
| 35 | Operaciones militares |
| 36 | Vela |
| 37 | Embarcación de recreo |
| 38-39 | Reservado |
| 50 | Buque de práctico |
| 51 | Buque de salvamento y rescate |
| 52 | Remolcador |
| 53 | Buque de servicio portuario (*port tender*) |
| 54 | Buque anticontaminación |
| 55 | Fuerzas del orden |
| 56-57 | Reservado para uso local |
| 58 | Transporte médico |
| 59 | Buque no combatiente (Resolución nº 18 del RR) |

### 1.3. Lo que aparece de verdad en el Mediterráneo

Medido sobre 141 buques distintos en 120 s:

| Código | Tipo | % |
|--------|------|---|
| 37 | Recreo | 25,5% |
| 70 | Carga, sin detalle | 16,3% |
| 80 | Tanque, sin detalle | 8,5% |
| 30 | Pesca | 5,7% |
| 52 | Remolcador | 5,7% |
| 60 | Pasaje | 5,7% |
| 71 | Carga, mercancía peligrosa A | 4,3% |
| 36 | Vela | 3,5% |
| 79 | Carga, sin info adicional | 3,5% |
| 89 | Tanque, sin info adicional | 3,5% |
| resto | 0, 4, 33, 40, 49, 51, 56, 69, 73, 74, 81, 86, 90, 99 | ~18% |

Agregado por categoría: **carga (70-79) = 27,7%**, tanque (80-89) = 13,5%,
pasaje (60-69) = 7,1%.

> **Dato de calidad**: apareció un buque emitiendo el código **4**, que está en el rango
> reservado 1-19. Los códigos inválidos o reservados existen en el flujo real; conviene
> que Flink los trate como "desconocido" y no asuma que todo valor cae en el catálogo.

### 1.4. Aviso crítico: 70-79 NO identifica portacontenedores

El estándar AIS **no distingue portacontenedores** de graneleros, carga general,
frigoríficos o ro-ro: todos declaran 70-79. El segundo dígito indica peligrosidad de la
mercancía, no el tipo de buque.

La única forma de identificar portacontenedores es el **JOIN por IMO con la tabla
`thetis_mrv`**, cuyo campo `ship_type` sí trae la taxonomía real de EMSA
(`Container ship`, `Bulk carrier`, `Oil tanker`, `Ro-ro ship`…). En el fichero de 2024
hay 2.159 portacontenedores identificados así.

Filtrar por 70-79 daría "toda la carga"

---

## 2. Estado de navegación (`nav_status`)

Entero de 0 a 15 que describe la situación operativa declarada por el buque.

| Código | Significado |
|--------|-------------|
| 0 | Navegando a motor |
| 1 | **Fondeado** (al ancla) |
| 2 | Sin gobierno (*not under command*) |
| 3 | Maniobrabilidad restringida |
| 4 | Restringido por su calado |
| 5 | **Amarrado** (atracado) |
| 6 | Varado (*aground*) |
| 7 | Dedicado a la pesca |
| 8 | Navegando a vela |
| 9 | Reservado (naves de alta velocidad / mercancía peligrosa cat. C) |
| 10 | Reservado (WIG / mercancía peligrosa cat. A) |
| 11 | Buque a motor remolcando por popa |
| 12 | Buque a motor empujando o remolcando por el costado |
| 13 | Reservado |
| 14 | AIS-SART activo / MOB-AIS / EPIRB-AIS (baliza de emergencia) |
| 15 | **Indefinido** (valor por defecto) |

### 2.1. Lo que aparece de verdad en el Mediterráneo

Medido sobre 731 buques distintos en 120 s:

| Código | Estado | % |
|--------|--------|---|
| 0 | Navegando a motor | 59,1% |
| 5 | **Amarrado** | 20,7% |
| 15 | Indefinido | 6,3% |
| 1 | **Fondeado** | 5,5% |
| 8 | Navegando a vela | 2,7% |
| 7 | Pesca | 2,5% |
| 3 | Maniobrabilidad restringida | 1,5% |
| 11, 12 | Remolcando | 0,8% |
| 9, 10, 13 | Reservados | 0,8% |
| 6 | Varado | 0,1% |

> **Dato de calidad**: el 6,3% declara **15 (indefinido)** y aparecen códigos
> *reservados* (9, 10, 13) que no deberían usarse. Además, un 0,1% se declara "varado",
> lo que casi siempre es un error del operador y no un buque realmente encallado. Este
> campo lo teclea la tripulación: es declarativo, no medido, y se olvida actualizar con
> frecuencia. No conviene usarlo como única fuente de verdad.

### 2.2. Los dos códigos que importan para Nautiq

| Código | Uso en el sistema |
|--------|-------------------|
| **5 (amarrado)** | Ocupación de atraque. Un buque en 5 dentro del polígono del puerto está ocupando muelle: es la base para calcular el cupo. |
| **1 (fondeado)** | Espera. Un buque en 1 frente al puerto es exactamente lo que el JIT trata de evitar: está quemando combustible en ralentí esperando turno. |

La diferencia entre 0 (navegando) y 1 (fondeado) es la señal de que un buque llegó
antes de tiempo. Cuantificarla contra `co2_at_berth_t` de `thetis_mrv` da la línea base
del ahorro.

Como el campo es declarativo, conviene **corroborarlo con la velocidad**: un buque con
`speed` ≈ 0 sostenida dentro del área portuaria está parado, declare lo que declare.

---

## 3. Valores centinela en otros campos

Los códigos de "sin dato" no se limitan a estos dos catálogos. Nautiq publica el crudo,
así que estos valores llegan tal cual a Flink:

| Campo | Centinela | Significado | Frecuencia observada |
|-------|-----------|-------------|----------------------|
| `heading` | 511 | Rumbo verdadero no disponible | **27,3%** de las posiciones |
| `cog` | 360 | Rumbo sobre el fondo no disponible | **10,6%** |
| `nav_status` | 15 | Estado indefinido | **9,7%** |
| `ship_type` | 0 | Tipo no disponible | 2,1% de los buques |
| `speed` | 102,3 | Velocidad no disponible | no observado en 719 posiciones (existe en el estándar, es raro) |
| `imo` | 0 | Sin IMO | el productor ya lo convierte a `null` |
| `eta` | `{"Day": 0, "Hour": 24, "Minute": 60, "Month": 0}` | ETA no declarada | ~21% de las estáticas |

Los tres primeros no son casos raros: **más de una de cada cuatro posiciones no trae
rumbo verdadero**. Cualquier cálculo geométrico en Flink debe descartarlos
explícitamente, porque tratar 511 como grados o 360 como rumbo válido mete un error
enorme y silencioso.
