# Conceptos Clave y Glosario de AISStream

Esta documentación explica los términos y conceptos fundamentales para entender y trabajar correctamente con la API de AISStream.

## 1. Conceptos Generales Marítimos

*   **AIS (Automatic Identification System):** Es el protocolo principal. Consiste en un sistema de seguimiento automatizado utilizado en buques y por los servicios de tráfico marítimo para identificar y localizar embarcaciones mediante frecuencias de radio VHF. AISStream digitaliza esta señal de radio y la expone en internet.
*   **MMSI (Maritime Mobile Service Identity):** Es un número único de 9 dígitos que identifica de forma exclusiva a una estación de radio marítima (es decir, identifica a un barco específico). En AISStream, usas el campo `FiltersShipMMSI` para suscribirte únicamente a la información de los barcos que te interesen.
*   **IMO Number:** Otro identificador de buque (Organización Marítima Internacional). A diferencia del MMSI, que puede cambiar si el barco cambia de bandera o registro, el número IMO es permanente durante toda la vida útil del barco.
*   **SOG (Speed Over Ground):** *Velocidad sobre el fondo*. Indica la velocidad real a la que se desplaza el barco respecto al lecho marino, independientemente de las corrientes o el viento. Suele medirse en nudos.
*   **COG (Course Over Ground):** *Rumbo sobre el fondo*. Es la trayectoria o dirección real en la que se mueve el barco respecto a la Tierra, expresada en grados (0° a 360°).
*   **True Heading:** *Rumbo verdadero*. Es la dirección hacia la que apunta la proa del barco en relación con el Norte geográfico. Es común que difiera del COG si hay corrientes laterales que hacen que el barco se desplace de lado ("deriva").
*   **Navigational Status:** *Estado de navegación*. Un código numérico (ej. 0 = navegando a motor, 1 = fondeado, 5 = amarrado) que indica la situación actual de operación del buque.

## 2. Conceptos de Arquitectura y Conexión API

*   **WebSocket (wss://):** Es el protocolo bidireccional y en tiempo real que usa AISStream. A diferencia de una petición HTTP (REST) donde pides datos y la conexión se cierra, el WebSocket se mantiene siempre abierto recibiendo un flujo ininterrumpido (*stream*) de eventos.
*   **Subscription Message (Mensaje de Suscripción):** Es un mensaje JSON que actúa como el "saludo" inicial. Debes enviarlo **obligatoriamente en los primeros 3 segundos** tras abrir el WebSocket. Contiene tu `APIKey` y las reglas (filtros) que quieres aplicar a tu flujo de datos.
*   **Bounding Box (Caja Delimitadora):** Un área geográfica rectangular definida por dos pares de coordenadas (Latitud y Longitud) que representan dos esquinas opuestas de la caja. Le indica a la API: *"Solo envíame información de los barcos que estén físicamente dentro de este rectángulo"*.
    *   *Dato clave:* Puedes incluir múltiples *Bounding Boxes* en tu suscripción y pueden solaparse sin generar mensajes duplicados.
*   **Swap and Replace:** Es el concepto de cómo se actualizan los filtros. Si quieres dejar de seguir un barco o cambiar de *Bounding Box*, no necesitas cerrar la conexión. Simplemente envía un nuevo *Subscription Message* por el mismo WebSocket y la API reemplazará inmediatamente tus filtros anteriores.
*   **TCP Backlog / Cola de Lectura:** Es vital comprender esto. AISStream puede enviar **más de 300 mensajes por segundo** (si te suscribes a todo el mundo). Si el código de tu programa es lento y no procesa los mensajes rápidamente, los mensajes se acumularán en la memoria de la red. AISStream monitoriza este atasco y **te desconectará automáticamente** (cerrará tu conexión) si detecta que no estás consumiendo los datos a tiempo.

## 3. Catálogo Completo de Tipos de Mensajes (`MessageType`)

La API de AISStream digitaliza todos los mensajes del estándar AIS. Para facilitar su comprensión, los hemos agrupado en categorías lógicas. Conocerlos te permitirá estructurar mejor tu base de datos y saber qué información esperar de cada uno.

### A. Reportes de Posición (Dinámicos)
*   **PositionReport:** El mensaje más vital y frecuente. Proporciona la ubicación en tiempo real (Lat/Lon), velocidad (SOG), rumbo (COG), rumbo verdadero y estado de navegación. Emitido por transceptores de Clase A (buques comerciales grandes).
*   **StandardClassBPositionReport:** Similar al anterior pero para transceptores Clase B (embarcaciones menores, yates de recreo, pesqueros pequeños). 
*   **ExtendedClassBPositionReport:** Una versión extendida del reporte Clase B que incluye más detalles técnicos (como la velocidad de giro y el rumbo verdadero) acercándose al nivel de detalle de la Clase A.
*   **LongRangeAisBroadcastMessage:** Diseñado para comunicación de largo alcance (a veces captado por satélites o receptores especiales), permitiendo seguir barcos a grandes distancias (más de 20 millas náuticas).

### B. Datos Estáticos y de Viaje
*   **ShipStaticData:** Contiene información que no cambia con frecuencia: nombre del barco, indicativo de llamada (Call Sign), dimensiones (eslora y manga), tipo de barco (ej. petrolero, carga, remolcador), destino y tiempo estimado de llegada (ETA).
*   **StaticDataReport:** Parecido al anterior, divide la información estática en dos partes (A y B) para adaptarse a los límites de tamaño del paquete de radio. Se emite periódicamente.

### C. Seguridad y Búsqueda y Rescate (SAR)
*   **SafetyBroadcastMessage:** Mensaje de difusión general para alertar a todos los barcos cercanos sobre peligros inminentes (obstáculos en el agua, contenedores perdidos, condiciones climáticas extremas).
*   **AddressedSafetyMessage:** Igual que el anterior, pero dirigido a un barco en específico (usando su MMSI) en lugar de una difusión general.
*   **StandardSearchAndRescueAircraftReport:** Emitido por aeronaves (aviones o helicópteros) que realizan operaciones de búsqueda y rescate. Indica su posición, altitud (muy importante) y rumbo.

### D. Infraestructura Costera y Ayudas a la Navegación
*   **BaseStationReport:** Reporte emitido por una estación base fija en tierra (como un centro de control de tráfico marítimo o faro), indicando su posición estática.
*   **AidsToNavigationReport:** Reporta la posición y el estado de una ayuda a la navegación (AtoN), como boyas o balizas. También se usa para balizas "virtuales" que no existen físicamente pero aparecen en los radares para marcar peligros submarinos.
*   **GnssBroadcastBinaryMessage:** Transmitido por infraestructuras GNSS (GPS/EGNOS) para enviar correcciones de posicionamiento a los barcos, mejorando la precisión de sus equipos.

### E. Mensajería Binaria (Datos Flexibles)
*   **SingleSlotBinaryMessage / MultiSlotBinaryMessage:** Mensajes que encapsulan datos binarios puros en uno o varios *slots* de tiempo. Se usan para transmitir información no estandarizada por defecto en AIS, como lecturas meteorológicas locales de sensores o niveles de marea.
*   **AddressedBinaryMessage:** Datos binarios dirigidos exclusivamente a un barco en particular.
*   **BinaryAcknowledge:** Mensaje que confirma que se ha recibido correctamente un mensaje binario dirigido.

### F. Gestión de Red y Control (Mensajes Técnicos)
*   **Interrogation:** Un barco o estación base envía este mensaje para "interrogar" o forzar a otro barco a que transmita sus datos inmediatamente.
*   **ChannelManagement:** Las autoridades costeras lo usan para ordenar a los barcos que cambien temporalmente sus frecuencias de radio VHF en áreas específicas.
*   **AssignedModeCommand:** Comando de una estación base que obliga a ciertos barcos a cambiar la frecuencia (intervalo) con la que emiten sus reportes de posición.
*   **DataLinkManagementMessage / CoordinatedUTCInquiry:** Mensajes técnicos del protocolo utilizados para gestionar las ranuras de tiempo en la red de radio VHF y mantener los relojes sincronizados.


## 4. Diccionario de Estados de Navegación (`NavigationalStatus`)

Los números de los estados se refieren al **NavigationalStatus** (Estado de Navegación) del estándar internacional AIS. Los barcos transmiten este código numérico para indicar qué están haciendo operativamente en ese momento.

Aquí tienes la lista completa de lo que significa cada número:

* **`0`**: Under way using engine (Navegando a motor). Es el estado más común cuando el barco está en tránsito por el mar.
* **`1`**: At anchor (Fondeado). El barco ha tirado el ancla y está esperando (normalmente en la zona exterior de un puerto esperando turno).
* **`2`**: Not under command (Sin gobierno). El barco tiene una avería grave y no puede maniobrar.
* **`3`**: Restricted manoeuvrability (Maniobrabilidad restringida). El barco está haciendo trabajos (como dragado o remolque) y no puede apartarse fácilmente.
* **`4`**: Constrained by her draught (Restringido por su calado). El barco es tan profundo que solo puede navegar por un canal muy específico y no puede desviarse.
* **`5`**: Moored (Amarrado). El barco está físicamente atado al muelle dentro del puerto, realizando tareas de carga/descarga.
* **`6`**: Aground (Varado / Encallado). El barco ha tocado fondo y está atascado.
* **`7`**: Engaged in Fishing (Pescando). El barco tiene redes en el agua.
* **`8`**: Under way sailing (Navegando a vela).
* *Del `9` al `14`*: Son códigos reservados para usos futuros o embarcaciones especiales (como transportes de materiales peligrosos rápidos).
* **`15`**: Not defined (No definido). Es el valor por defecto si el sistema AIS del barco no ha sido configurado por la tripulación.