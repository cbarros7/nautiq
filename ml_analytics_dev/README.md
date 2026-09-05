## Arquitectura Medallion, analítica y Machine Learning

En esta sección se desarrolla la parte analítica de los datos AIS ingeridos y almacenados en el ADLS del proyecto.

Este bloque de arquitectura estuvo en funcionamiento en el entorno de **DEV desde el 01/08/2026 hasta el 31/08/2026**, fecha establecida como cierre para la documentación de la tarea realizada.

Debido al reducido tiempo disponible hasta la fecha de entrega, no fue posible recopilar un histórico suficientemente amplio de buques que hubieran completado todo su ciclo de escala portuaria. Este histórico resulta necesario para obtener los tiempos de espera reales y disponer de una muestra representativa para el entrenamiento del modelo.

Por este motivo, se decidió mantener este bloque exclusivamente en **DEV** y no promoverlo a Producción, considerándolo un *nice-to-have* de cara a futuras mejoras del proyecto. Con una ventana temporal de datos más amplia, este componente podría integrarse en el flujo productivo como apoyo a la parte cognitiva, permitiendo incorporar información basada en el comportamiento histórico y en modelos de Machine Learning para mejorar las sugerencias y predicciones generadas.

Toda esta sección se ha desarrollado mediante notebooks de Python en un workspace de **Azure Databricks Premium**, independiente de la cuenta de almacenamiento ADLS utilizada para la ingesta de los datos AIS.

Para acceder de forma segura al ADLS se utiliza un **SAS Token**, almacenado como secreto en **Databricks Secret Scope** y recuperado dinámicamente desde los notebooks, evitando incluir credenciales directamente en el código.


## Estructura de notebooks

```text
notebooks/
├── setup_nautiq_dev.ipynb
├── medallion/
│   ├── silver_ais_positions_dev.ipynb
│   ├── silver_ais_static_dev.ipynb
│   └── gold_vessel_port_calls_jit.ipynb
├── data_analytics/
│   └── gold_waiting_avg_per_length.ipynb
└── ml_analytics/
    ├── ml_vessel_jit_classification.ipynb
    └── gold_vessel_jit_current_predictions.ipynb
```

Al ejecutarse este bloque únicamente en DEV, las salidas se han almacenado como tablas administradas en **Unity Catalog** dentro del entorno de Databricks.

Para centralizar la configuración se ha creado el notebook `setup_nautiq_dev.ipynb`, que contiene las rutas de lectura, tablas de destino, schemas, checkpoints de Auto Loader, configuración del acceso al ADLS, nombres de los notebooks y configuración del modelo registrado en MLflow.

El setup también deja preparada la configuración necesaria para utilizar almacenamiento externo en ADLS. De esta forma, una futura adaptación del flujo a Producción puede realizarse de manera más sencilla y centralizada, reduciendo la necesidad de modificar individualmente cada componente.

La estructura del trabajo se puede separar en **3 bloques principales**:

- **Medallion**
- **Data Analytics**
- **Machine Learning**


### Medallion

En este apartado se consolidan las capas de la arquitectura Medallion.

Los notebooks `silver_ais_positions_dev.ipynb` y `silver_ais_static_dev.ipynb` procesan respectivamente los datos AIS de posiciones y los datos estáticos de los buques procedentes de la capa Bronze del ADLS.

La lectura se realiza de forma incremental mediante **Databricks Auto Loader**, utilizando schemas y checkpoints independientes para cada fuente. Durante este proceso se realizan tareas de normalización, tipado, estandarización de nomenclatura y validación, manteniendo los datos lo más próximos posible a la información original recibida.

Como resultado se generan las tablas Silver:

- `silver.ais_positions_dev`
- `silver.ais_static_dev`

Una vez procesadas ambas fuentes, entra en ejecución `gold_vessel_port_calls_jit.ipynb`, que combina la información temporal de posiciones AIS con la información estática de cada buque.

El objetivo es transformar los registros AIS individuales en una unidad de negocio de mayor nivel:


```text
1 fila = 1 escala portuaria (`port_call`) de un buque
```
A partir de las posiciones AIS se reconstruye el comportamiento del buque alrededor del puerto, identificando principalmente las fases de:

- aproximación;
- fondeo;
- entrada en servicio.

El análisis se realiza para los tres puertos seleccionados en el proyecto:

- Valencia (`ESVLC`)
- Barcelona (`ESBCN`)
- Algeciras (`ESALG`)

Para las escalas completadas se calcula el tiempo de espera real transcurrido antes del inicio del servicio:

```text
actual_wait_hours = service_start_timestamp - anchor_start_timestamp
```

En los casos en los que el buque entra directamente en servicio sin una fase previa de fondeo, el tiempo de espera se considera igual a `0`.

El resultado se almacena en:

```text
gold.vessel_port_calls_analytics
```

Esta tabla constituye la base analítica para los siguientes bloques del proyecto.

### Data Analytics

El notebook `gold_waiting_avg_per_length.ipynb` se construye a partir de las escalas portuarias ya identificadas en la Gold anterior.

Su objetivo es generar una **referencia histórica del comportamiento real de los tiempos de espera** en los tres puertos seleccionados.

Para ello, utiliza únicamente escalas que disponen de un `actual_wait_hours` válido y genera dos tablas analíticas.

La primera agrupa los resultados por "puerto + rango de eslora", generando:

```text
gold.waiting_avg_per_length
```

La segunda incorpora además el tipo de buque "puerto + rango de eslora + tipo de buque", generando:

```text
gold.waiting_avg_per_type
```


Para el posterior entrenamiento de Machine Learning se utiliza principalmente la **mediana (`median_wait_hours`) de puerto + rango de eslora**, ya que permite disponer de una referencia histórica menos sensible a valores extremos que la media.

### Machine Learning

En el notebook `ml_vessel_jit_classification.ipynb` se define el proceso de entrenamiento del modelo de clasificación.

Para construir la muestra se utilizan únicamente las escalas portuarias que disponen de un tiempo de espera real observado y que pueden asociarse a una mediana histórica válida.

El tiempo de espera real:

```text
actual_wait_hours
```

se compara con la mediana histórica obtenida de:

```text
gold.waiting_avg_per_length
```

para la combinación:

```text
destination_port_code + vessel_length_band
```

De esta comparación se obtiene la etiqueta utilizada como variable objetivo del modelo:

```text
JIT = 1
actual_wait_hours <= median_wait_hours
```

```text
NO_JIT = 0
actual_wait_hours > median_wait_hours
```

La mediana se utiliza exclusivamente para construir la etiqueta y **no se introduce como variable de entrada al modelo**, evitando introducir información del target dentro de las variables predictoras.

Para este proyecto se han evaluado tres modelos de clasificación:

- **Logistic Regression:** modelo lineal utilizado como baseline e interpretable.
- **Random Forest:** conjunto de árboles entrenados en paralelo, capaz de aprender relaciones no lineales.
- **XGBoost:** modelo basado en boosting secuencial de árboles, orientado a aprender relaciones más complejas.

Para el entrenamiento y evaluación se ha utilizado **StratifiedGroupKFold con 10 folds**.

Cada fold actúa una vez como conjunto de prueba. La estratificación intenta mantener una proporción similar de las clases JIT y NO_JIT en cada partición, mientras que la agrupación por `mmsi` evita que escalas correspondientes al mismo buque aparezcan simultáneamente en entrenamiento y test.

De esta forma se reduce el riesgo de **data leakage** y se evalúa mejor la capacidad del modelo para generalizar sobre buques diferentes a los observados durante su entrenamiento.

Debido al reducido periodo disponible para recopilar históricos, el conjunto final utilizado por el notebook de entrenamiento quedó formado por una muestra de 262 escalas de los cuales 130 estan clasificadas como JIT y 132 como NO_JIT.


El reducido tamaño de la muestra constituye una de las principales limitaciones de esta prueba y es uno de los motivos por los que este componente se mantiene actualmente en DEV.

Dado que el objetivo del proyecto es identificar situaciones en las que una escala puede superar el tiempo de espera habitual, para seleccionar el modelo ganador se ha dado prioridad a la métrica **`recall_no_jit`**.

Esta métrica indica qué proporción de los casos que realmente son **NO_JIT** consigue identificar correctamente el modelo. De esta forma, se busca reducir especialmente los casos en los que una escala que realmente va a superar el umbral histórico es clasificada incorrectamente como JIT.

Para evitar seleccionar un modelo que consiga un recall elevado simplemente prediciendo demasiados casos como NO_JIT, también se tienen en cuenta métricas complementarias como:

- `precision_no_jit`;
- `balanced_accuracy`;
- `f1_macro`;
- `roc_auc`.

Como resultado de la evaluación, el modelo seleccionado fue **Logistic Regression**. Con la muestra disponible, los modelos más complejos no consiguieron mejorar de forma consistente sus resultados.

Una vez seleccionado el modelo ganador, se realizó una segunda fase de reducción de variables mediante **Permutation Importance**.

La importancia de cada variable se calcula dentro del conjunto de entrenamiento de cada fold, evaluando cómo afecta su permutación al `recall_no_jit`. Posteriormente se analiza la estabilidad de las variables entre los diferentes folds.

El modelo completo utilizaba **8 variables**, mientras que la versión reducida consiguió mantener un comportamiento muy similar utilizando únicamente **3 variables**:

```text
speed_over_ground_knots
navigation_status_code
destination_port_code
```

En la validación cruzada, los resultados medios fueron:

| Versión | recall_NO_JIT | balanced_accuracy |
| --- |--------------:|------------------:|
| FULL |        0.8181 |            0.8119 |
| REDUCED |        0.8033 |            0.7964 |

La reducción supone una pérdida de aproximadamente `0.01` en `recall_no_jit` y `balanced_accuracy`, por lo que se decidió utilizar la versión reducida debido a su menor complejidad y al mantenimiento de un rendimiento muy similar.

Las tres variables seleccionadas también fueron las únicas que aparecieron de forma estable en los **10 folds** utilizados durante el proceso de selección.

Una vez entrenado el modelo final, se registra en **MLflow Model Registry / Unity Catalog** bajo el nombre:

```text
gold.vessel_jit_classifier
```

La versión activa recibe el alias:

```text
Champion
```

Esto permite que el proceso de inferencia consulte siempre la versión activa del modelo sin necesidad de indicar manualmente un `run_id` o una versión concreta.



El modelo puede volver a entrenarse periódicamente a medida que se incorporan nuevas escalas portuarias completas al histórico. En el flujo planteado se configura una actualización semanal del entrenamiento para incorporar progresivamente nuevas observaciones y actualizar el modelo registrado cuando corresponda.

Como resultado final se utiliza `gold_vessel_jit_current_predictions.ipynb`.

Este notebook trabaja sobre escalas portuarias **todavía en curso**, seleccionando buques que:

- tienen como destino uno de los tres puertos analizados;
- continúan dentro de su escala actual;
- todavía no han iniciado el servicio o descarga;
- se encuentran en aproximación (`APPROACH`) o fondeados (`ANCHORED`).

El notebook carga automáticamente el modelo registrado mediante el alias `Champion` y utiliza las tres variables seleccionadas durante el entrenamiento para generar la clasificación:

```text
JIT
```

o:

```text
NO_JIT
```

Además de la clasificación, se almacena la probabilidad estimada por el modelo y la versión de MLflow utilizada para generar el resultado.

Para los buques que ya se encuentran fondeados se añade además una regla operacional: si el tiempo que llevan esperando (`anchored_elapsed_hours`) ya ha superado la mediana histórica correspondiente a su puerto y rango de eslora, el registro se clasifica directamente como **NO_JIT**, independientemente del resultado del modelo.

El origen de cada clasificación se mantiene en el campo `prediction_source`, permitiendo distinguir entre:

```text
ML_MODEL
```

cuando la clasificación procede del modelo, y:

```text
ELAPSED_WAIT_RULE
```

cuando se aplica la regla basada en el tiempo de espera ya transcurrido.

El resultado se almacena en:

```text
gold.vessel_jit_current_predictions
```


De esta forma, el flujo completo puede resumirse como:

```text
AIS Bronze
    ↓
Silver Positions + Silver Static
    ↓
Gold Port Calls
    ↓
Histórico de tiempos de espera
    ↓
Mediana puerto + eslora
    ↓
Etiquetado JIT / NO_JIT
    ↓
Entrenamiento ML
    ↓
MLflow Champion
    ↓
Predicción sobre escalas activas
```


## Aspectos claves

Para este apartado del proyecto se ha trabajado íntegramente desde un workspace de **Databricks Premium**.

Además de los notebooks desarrollados, se han utilizado los siguientes componentes:

- **Databricks Secret Scope:** almacenamiento seguro del SAS Token utilizado para acceder al ADLS de origen.

- **Databricks Auto Loader:** lectura incremental de los nuevos datos AIS procedentes de Bronze, manteniendo schemas y checkpoints independientes para las fuentes de posiciones y datos estáticos.

- **Unity Catalog:** almacenamiento, organización y gobierno de las tablas Silver y Gold generadas durante la ejecución en DEV.

- **Databricks Jobs & Pipelines:** orquestación y planificación de las ejecuciones automáticas.

- **MLflow Model Registry:** registro y versionado del modelo ganador. La versión utilizada para inferencia se identifica mediante el alias `Champion`, permitiendo actualizar el modelo sin modificar el notebook encargado de generar las predicciones.


### Orquestación diaria

El procesamiento diario se ha configurado mediante un workflow de Databricks denominado:

```text
nautiq_daily_medallion
```

El workflow establece las dependencias entre las diferentes tareas para garantizar que cada etapa se ejecute únicamente después de disponer de los datos generados por la etapa anterior.

El flujo comienza con los dos procesos Silver, que pueden ejecutarse de forma independiente:

```text
silver_ais_positions_dev
silver_ais_static_dev
```

Una vez finalizados ambos, se ejecuta:

```text
gold_vessel_port_calls_jit
```

Posteriormente se actualiza la capa analítica histórica:

```text
gold_waiting_avg_per_length
```

y, finalmente, se generan las predicciones sobre las escalas portuarias activas:

```text
gold_vessel_jit_current_predictions
```


### Reentrenamiento semanal de Machine Learning

El entrenamiento del modelo se ha separado del flujo diario mediante un segundo workflow denominado:

```text
nautiq_weekly_ml
```

En este proceso se ejecuta inicialmente:

```text
ml_vessel_jit_classification
```

para volver a construir el conjunto de entrenamiento con las nuevas escalas disponibles, evaluar el modelo y registrar la nueva versión cuando corresponda.

Una vez finalizada esta tarea, se ejecuta:

```text
gold_vessel_jit_current_predictions
```

utilizando la versión activa del modelo registrada en MLflow.

El resultado constituye una prueba funcional de cómo los datos AIS históricos pueden utilizarse para generar una capa analítica adicional orientada a la identificación de escalas **JIT / NO_JIT**.

La principal limitación actual se encuentra en el reducido histórico disponible para entrenamiento. La ampliación progresiva del periodo de observación permitiría aumentar el número de escalas completas, mejorar la representatividad de los diferentes puertos y tipos de buque y, posteriormente, reevaluar los modelos desarrollados antes de plantear su integración definitiva en Producción y su utilización como apoyo a la parte cognitiva del proyecto.

Para consultar información visual adicional sobre este apartado del proyecto, véase la sección de anexos de la documentación entregada.

