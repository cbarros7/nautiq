# Catálogos AIS: tipo de buque y estado de navegación

Referencia de los dos campos codificados que Nautiq transporta en crudo desde AIS.
Ambos son códigos numéricos del estándar **ITU-R M.1371**; 

| Campo | Mensaje AIS | Contrato Avro | Topic |
|-------|-------------|---------------|-------|
| `ship_type` | `ShipStaticData` (tipo 5) | `contracts/ais_static_v1.avsc` | `vessel.static.raw` |
| `nav_status` | `PositionReport` (tipos 1/2/3) | `contracts/ais_position_v1.avsc` | `vessel.positions.raw` |

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
