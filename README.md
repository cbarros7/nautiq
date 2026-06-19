# Nautiq

Nautiq es una plataforma de **Agent-as-a-Service (AaaS)** orientada a la logística marítima. Su objetivo principal es optimizar dinámicamente la velocidad (RPM) de los buques comerciales para garantizar llegadas *Just-In-Time* (JIT). Al evitar esperas innecesarias en los puertos, Nautiq elimina la quema de combustible en ralentí (Idle Fuel Burn) sin requerir modificaciones en el hardware de los barcos.

## Estructura del proyecto

El repositorio está organizado como un **Monorepo** basado en componentes. Esta separación garantiza que cada pieza del sistema sea independiente, escalable y fácil de mantener:

- **`api/` (Capa cognitiva):** Aplicación principal en FastAPI que hospeda al agente inteligente (construido con LangGraph). Aquí se toman las decisiones logísticas y se conecta con la base de datos transaccional (Supabase).
- **`streaming/` (Motor de procesamiento):** Tareas de procesamiento continuo en Apache Flink. Filtra el ruido de los datos, realiza cálculos geométricos en tiempo real y alerta a la API cuando detecta anomalías de navegación.
- **`ingestion/` (Adquisición de datos):** Scripts en Python responsables de conectarse a proveedores satelitales (como AISStream), validar la calidad de la telemetría y publicarla en Kafka.
- **`contracts/` (Reglas de datos):** Archivos JSON que definen de forma estricta cómo debe ser la información que fluye por el sistema, garantizando la calidad desde el primer paso (*Shift-Left Validation*).
- **`databricks/` (Analítica avanzada):** Entorno destinado al procesamiento de datos históricos, abarcando las capas de transformación y reporte para inteligencia de negocios.
- **`infrastructure/` (Infraestructura como código):** Archivos de Terraform para el despliegue automatizado en la nube (Azure/Oracle) y configuraciones de Docker para levantar el ecosistema en desarrollo local.
- **`docs/` (Documentación):** Repositorio de los manuales del sistema y los Registros de Decisiones de Arquitectura (ADRs).
- **`main.py`:** Archivo orquestador diseñado exclusivamente para arrancar el Producto Mínimo Viable (MVP) durante la fase de desarrollo local.

## Patrones de Diseño

Para asegurar un código profesional, limpio y sostenible, la arquitectura se apoya fuertemente en los siguientes patrones de diseño de software:

| Componente    | Patrón Aplicado          | Propósito Principal                                                                                           |
| :--------------| :-------------------------| :--------------------------------------------------------------------------------------------------------------|
| **Ingesta**   | **Facade**               | Ocultar la complejidad técnica bajo un orquestador semántico y fácil de leer.                                 |
|               | **Adapter**              | Aislar integraciones externas (ej. Kafka, WebSockets) para facilitar futuros reemplazos tecnológicos.         |
|               | **Observer**             | Permitir el flujo continuo de datos satelitales mediante colas asíncronas, evitando bloqueos del sistema.     |
| **Streaming** | **State**                | Mantener memoria del comportamiento previo de cada barco para detectar anomalías (ej. *GPS spoofing*).        |
|               | **Reactive Sink**        | Empujar alertas hacia la API estrictamente cuando sea necesario, evitando consultas repetitivas (Polling).    |
| **Cognitiva** | **ReAct Pattern**        | Otorgar autonomía al agente de IA para que intercale razonamiento lógico con ejecución de acciones.           |
|               | **Strategy / Tool**      | Encapsular las fórmulas matemáticas complejas como herramientas intercambiables para el modelo de lenguaje.   |
|               | **Dependency Injection** | Inyectar conexiones (bases de datos, modelos LLM) de forma limpia para asegurar pruebas unitarias confiables. |

## Ejecución y gestión de entornos

Este proyecto utiliza [uv](https://github.com/astral-sh/uv) como gestor central de dependencias bajo un esquema de **Workspaces**. Esto elimina la necesidad de configurar entornos virtuales (`venv`) o gestionar instalaciones cruzadas (`pip`) de manera manual.

### 1. Instalación de dependencias
Abra una terminal en la raíz del proyecto (`/nautiq`) y ejecute:
```bash
uv sync
```
*Este comando lee la configuración global, crea automáticamente un entorno virtual optimizado y enlaza todos los sub-paquetes internos del repositorio.*

### 2. Arrancar la aplicación (Local/MVP)
Para inicializar el orquestador principal de pruebas, simplemente ejecute:
```bash
uv run python main.py
```
*Al emplear `uv run`, la plataforma se encarga de aislar la ejecución y resolver de forma transparente las rutas internas de los paquetes sin requerir configuraciones adicionales.*
