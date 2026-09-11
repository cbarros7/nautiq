#!/bin/bash

# Default environment and mode
ENV_VAR="dev"
DETACH=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --env) ENV_VAR="$2"; shift ;;
        --detach|-d) DETACH=true ;;
        *) echo "Parametro desconocido: $1"; exit 1 ;;
    esac
    shift
done

if [[ "$ENV_VAR" != "prod" && "$ENV_VAR" != "dev" ]]; then
    echo "Error: Entorno '$ENV_VAR' no es válido. Solo se permite 'prod' y 'dev'."
    exit 1
fi

# Asegurar que ejecutamos comandos desde la carpeta 'streaming' independientemente de dónde se llame al script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$SCRIPT_DIR/streaming" || { echo "Error: No se encontró el directorio 'streaming'"; exit 1; }

# Asignar puerto según entorno para evitar colisiones
if [ "$ENV_VAR" == "prod" ]; then
    UI_PORT="${FLINK_UI_PORT_PROD:-8082}"
    PROM_JM_PORT="${FLINK_PROM_PORT_JM_PROD:-9249}"
    PROM_TM_PORT="${FLINK_PROM_PORT_TM_PROD:-9250}"
else
    UI_PORT="${FLINK_UI_PORT_DEV:-8081}"
    PROM_JM_PORT="${FLINK_PROM_PORT_JM_DEV:-9251}"
    PROM_TM_PORT="${FLINK_PROM_PORT_TM_DEV:-9252}"
fi

PROJECT_NAME="nautiq-${ENV_VAR}"
JOBMANAGER_CONTAINER="${PROJECT_NAME}-jobmanager-1"
TASKMANAGER_CONTAINER="${PROJECT_NAME}-taskmanager-1"

ENV_UPPER=$(echo "$ENV_VAR" | tr '[:lower:]' '[:upper:]')

echo "=================================================="
echo "  NAUTIQ STREAMING - ENTORNO: $ENV_UPPER"
echo "  - Proyecto Docker: $PROJECT_NAME"
echo "  - Web UI: http://localhost:$UI_PORT"
echo "  - Metrics JM: http://localhost:$PROM_JM_PORT/metrics"
echo "  - Metrics TM: http://localhost:$PROM_TM_PORT/metrics"
echo "=================================================="

echo "Deteniendo contenedores antiguos de $PROJECT_NAME..."
# Detener también contenedores legacy sin prefijo si existen para liberar puertos
docker stop streaming-jobmanager-1 streaming-taskmanager-1 2>/dev/null || true
docker rm -f streaming-jobmanager-1 streaming-taskmanager-1 2>/dev/null || true
docker compose -p "$PROJECT_NAME" --env-file "../.env.$ENV_VAR" down

echo "Levantando y reconstruyendo contenedores para $PROJECT_NAME (usando .env.$ENV_VAR)..."
ENV_FILE="../.env.$ENV_VAR" NAUTIQ_ENV=$ENV_VAR FLINK_UI_PORT=$UI_PORT FLINK_PROM_PORT_JM=$PROM_JM_PORT FLINK_PROM_PORT_TM=$PROM_TM_PORT docker compose -p "$PROJECT_NAME" --env-file "../.env.$ENV_VAR" up --build -d

echo "Esperando a que el JobManager ($JOBMANAGER_CONTAINER) esté saludable..."
RETRIES=0
MAX_RETRIES=60
while [ $RETRIES -lt $MAX_RETRIES ]; do
    RUNNING=$(docker inspect --format='{{.State.Running}}' "$JOBMANAGER_CONTAINER" 2>/dev/null || echo "false")
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$JOBMANAGER_CONTAINER" 2>/dev/null || echo "starting")
    
    if [ "$STATUS" == "healthy" ]; then
        echo -e "\nJobManager listo y saludable."
        break
    elif [ "$STATUS" == "unhealthy" ]; then
        echo -e "\nError: El JobManager falló su healthcheck. Revisa los logs con 'docker logs $JOBMANAGER_CONTAINER'."
        exit 1
    elif [ "$RUNNING" == "false" ] && [ "$STATUS" != "starting" ]; then
        echo -e "\nError: El JobManager no pudo arrancar. Revisa los logs con 'docker logs $JOBMANAGER_CONTAINER'."
        exit 1
    fi
    printf "."
    sleep 2
    RETRIES=$((RETRIES+1))
done

if [ $RETRIES -ge $MAX_RETRIES ]; then
    echo -e "\nError: Timeout esperando a que el JobManager esté saludable."
    exit 1
fi

if [ "$DETACH" = true ]; then
    echo "Ejecutando el orquestador de Flink en segundo plano (--detach) en entorno: $ENV_VAR..."
    docker exec -d -e NAUTIQ_ENV=$ENV_VAR "$JOBMANAGER_CONTAINER" python /opt/flink/usrlib/src/jobs/orchestrator.py --env $ENV_VAR
    echo "Orquestador Flink iniciado en background."
    echo "   Para ver los logs: docker logs -f $JOBMANAGER_CONTAINER"
else
    echo "Ejecutando el orquestador de Flink en entorno: $ENV_VAR..."
    if [ -t 0 ]; then
        DOCKER_TTY="-it"
    else
        DOCKER_TTY="-i"
    fi
    docker exec -e NAUTIQ_ENV=$ENV_VAR $DOCKER_TTY "$JOBMANAGER_CONTAINER" python /opt/flink/usrlib/src/jobs/orchestrator.py --env $ENV_VAR
fi
