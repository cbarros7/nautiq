"""
Módulo: orchestrator.py
Propósito: Gestionar el ciclo de vida del Flink Job como un proceso Bounded simulado.
           Se ejecuta via CronJob 3 veces al día.
           - Arranca el job usando el último Savepoint.
           - Detecta idleness monitoreando el Kafka Consumer Lag.
           - Detiene el job de forma limpia creando un nuevo Savepoint.
           - Rota Savepoints antiguos en ADLS para evitar acumulación infinita.
"""
import subprocess
import urllib.request
import json
import logging
import time
import os
import sys
import tempfile
from typing import Optional, List

import config

# Asegurar que Hadoop CLI incluya las librerías de Azure ABFS de Flink en su CLASSPATH
existing_classpath = os.getenv("HADOOP_CLASSPATH", "")
if "/opt/flink/lib/*" not in existing_classpath:
    os.environ["HADOOP_CLASSPATH"] = f"/opt/flink/lib/*:{existing_classpath}".strip(":")

# Structured logging estandarizado para ingesta en Grafana / Loki
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [nautiq.orchestrator] %(message)s"
)
logger = logging.getLogger("nautiq.orchestrator")

FLINK_REST = "http://localhost:8081"
SAVEPOINT_DIR = config.ADLS_SAVEPOINTS_URL
CHECKPOINT_DIR = f"abfss://checkpoints@{config.AZURE_STORAGE_ACCOUNT}.dfs.core.windows.net/flink_checkpoints"
LOCK_FILE = f"{SAVEPOINT_DIR}/.orchestrator.lock"
STATE_FILE = f"{SAVEPOINT_DIR}/.active_job_id"
MAX_SAVEPOINTS = 10
IDLE_STABLE_SAMPLES = 3         # Cuántas veces seguidas el lag debe ser 0 para confirmar que no hay más datos (evita falsos positivos).
IDLE_POLL_INTERVAL_S = 20       # Segundos de espera entre cada chequeo de lag en Kafka.
SAVEPOINT_POLL_TIMEOUT_S = 120  # Tiempo máximo esperado para que Flink termine de escribir el Savepoint en ADLS.

def _lock_exists() -> bool:
    """Verifica la existencia del lock file usando HDFS/ABFS native CLI."""
    result = subprocess.run(["hadoop", "fs", "-test", "-e", LOCK_FILE], capture_output=True)
    return result.returncode == 0

def _acquire_lock():
    """Adquiere el lock atómicamente creando un directorio en ADLS."""
    # Asegurar que el directorio de savepoints existe en ADLS
    subprocess.run(["hadoop", "fs", "-mkdir", "-p", SAVEPOINT_DIR], capture_output=True)
    
    # Intentar crear el directorio de lock SIN -p (falla si ya existe, operación atómica)
    res = subprocess.run(["hadoop", "fs", "-mkdir", LOCK_FILE], capture_output=True, text=True)
    if res.returncode != 0:
        if "File exists" in res.stderr or "already exists" in res.stderr:
            logger.warning("Carrera detectada: Otra instancia adquirió el lock una fracción de segundo antes.")
            sys.exit(0)
        else:
            logger.error(f"Error inesperado creando lock en ADLS: {res.stderr}")
            raise subprocess.CalledProcessError(res.returncode, "hadoop fs -mkdir", output=res.stdout, stderr=res.stderr)
            
    logger.info(f"Lock adquirido atómicamente - path={LOCK_FILE}")

def _release_lock():
    """Libera el lock eliminando el directorio en ADLS."""
    try:
        if _lock_exists():
            subprocess.run(["hadoop", "fs", "-rm", "-r", LOCK_FILE], check=True, capture_output=True)
            logger.info(f"Lock liberado - path={LOCK_FILE}")
    except Exception as e:
        logger.error(f"Fallo al liberar el lock - error={e}")

def _get_running_job_id() -> Optional[str]:
    """Consulta la REST API de Flink para encontrar si el job ya está corriendo."""
    try:
        req = urllib.request.Request(f"{FLINK_REST}/jobs/overview")
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            for job in data.get("jobs", []):
                if job.get("state") == "RUNNING":
                    # Verificamos si este job_id coincide con el del state file
                    state_job_id = _read_state(STATE_FILE)
                    if state_job_id and state_job_id == job.get("jid"):
                        return state_job_id
    except Exception as e:
        logger.warning(f"Error consultando Flink REST API - error={e}")
        # Intentar leer desde el state file como fallback
        state_job_id = _read_state(STATE_FILE)
        if state_job_id:
             logger.info(f"Usando JobID del state file como fallback - job_id={state_job_id}")
             return state_job_id
    return None

def _read_state(state_file: str) -> Optional[str]:
    """Lee el JobID desde el archivo de estado en ADLS."""
    try:
        result = subprocess.run(["hadoop", "fs", "-cat", state_file], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

def _clear_state(state_file: str):
    """Elimina el archivo de estado cuando el ciclo termina exitosamente."""
    try:
         subprocess.run(["hadoop", "fs", "-rm", state_file], capture_output=True)
    except Exception:
         pass

def get_all_savepoints() -> List[str]:
    """Lista todos los directorios de Savepoints en ADLS ordenados cronológicamente."""
    try:
        result = subprocess.run(["hadoop", "fs", "-ls", SAVEPOINT_DIR], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        # Filtra lineas que contengan directorios savepoint-
        savepoints = [line.split()[-1] for line in lines if 'savepoint-' in line]
        savepoints.sort()
        return savepoints
    except subprocess.CalledProcessError:
        return []

def find_latest_savepoint() -> Optional[str]:
    """Retorna la ruta del Savepoint o Checkpoint retenido más reciente en ADLS."""
    # 1. Buscar Savepoint manual explícito
    sps = get_all_savepoints()
    if sps:
        return sps[-1]
        
    # 2. Fallback: Buscar el Checkpoint automático retenido más reciente
    try:
        res = subprocess.run(
            ["hadoop", "fs", "-find", CHECKPOINT_DIR, "-name", "_metadata"],
            capture_output=True, text=True
        )
        if res.returncode == 0 and res.stdout.strip():
            metadata_files = res.stdout.strip().split('\n')
            chk_dirs = [os.path.dirname(f) for f in metadata_files if '_metadata' in f]
            if chk_dirs:
                chk_dirs.sort()
                latest_chk = chk_dirs[-1]
                logger.info(f"Checkpoint automatico de respaldo detectado en ADLS - path={latest_chk}")
                return latest_chk
    except Exception as e:
        logger.warning(f"Error buscando checkpoints de respaldo - error={e}")

    return None

def _submit_job(savepoint_path: Optional[str]) -> str:
    """Ejecuta el job en modo detached. Retorna el JobID leyendo el state file generado por nautiq_job."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    job_file = os.path.join(script_dir, "nautiq_job.py")
    cmd = ["flink", "run", "-d", "-py", job_file]
    
    if savepoint_path and not config.FLINK_FORCE_COLD_START:
        cmd.extend(["-s", savepoint_path])
        if config.FLINK_IGNORE_UNCLAIMED_STATE:
            cmd.extend(["-n"])
            logger.info("Mitigacion de Schema Evolution activada (flag -n)")
        logger.info(f"Lanzando job desde Savepoint - path={savepoint_path}")
    else:
        logger.info("Iniciando arranque en frio (sin Savepoint)")
        
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=script_dir)
        
        # Esperar a que el script de python (nautiq_job) escriba el state file
        for _ in range(15):
            time.sleep(2)
            job_id = _read_state(STATE_FILE)
            if job_id:
                return job_id
                
        raise RuntimeError("Job sometido pero no se pudo recuperar el JobID del state file.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Fallo al enviar el Job a Flink - stderr={e.stderr}")
        raise

def _get_kafka_consumer_lag() -> int:
    """
    Obtiene el lag total del Consumer Group usando las herramientas nativas de Kafka.
    Suma el lag de todas las particiones del topic de telemetría para el grupo de Flink.
    """
    props_path = None
    try:
        # Generar un archivo client.properties dinámico para la conexión SSL de Kafka CLI
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as props_file:
            props_file.write(f"security.protocol={config.KAFKA_SECURITY_PROTOCOL}\n")
            props_file.write(f"ssl.truststore.type=PEM\n")
            props_file.write(f"ssl.truststore.location={config.KAFKA_SSL_CA_LOCATION}\n")
            props_file.write(f"ssl.keystore.type=PEM\n")
            props_file.write(f"ssl.keystore.location={config.KAFKA_SSL_CERT_LOCATION}\n")
            props_path = props_file.name

        cmd = [
            "kafka-consumer-groups.sh",
            "--bootstrap-server", config.KAFKA_BOOTSTRAP_SERVERS,
            "--command-config", props_path, # Archivo properties dinámico
            "--group", config.KAFKA_GROUP_ID,
            "--describe"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        output = result.stdout + result.stderr
        
        # Casos donde el lag no es confiable (Consumer group/topic aún no creado)
        if "does not exist" in output or "Error:" in output:
            logger.info("Consumer group o topic aun no existe (esperando a que Flink inicie)...")
            return -1

        if result.returncode != 0:
            logger.warning(f"Error consultando lag CLI: {result.stderr}")
            return -1 # Retorna un lag inválido para no disparar el idleness accidentalmente
            
        total_lag = 0
        # Parseo de la salida tabular de kafka-consumer-groups.sh
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            # La columna de LAG suele ser la 6ta (index 5) en la salida estándar
            if len(parts) > 5 and parts[5].isdigit():
                total_lag += int(parts[5])
                
        return total_lag
    except FileNotFoundError:
        # Si no existe el binario en el contenedor, el lag no se puede calcular de forma nativa.
        # Retornamos -1 para evitar que el orquestador asuma falsamente que el lag es 0 y detenga el job.
        logger.error("kafka-consumer-groups.sh no encontrado. No se puede monitorear el idleness.")
        return -1
    except Exception as e:
        logger.error(f"Error parseando lag de Kafka: {e}")
        return -1
    finally:
        if props_path and os.path.exists(props_path):
            os.remove(props_path)

def _wait_until_idle(job_id: str):
    """
    Monitorea el lag del Consumer Group de Kafka. Requiere N muestras consecutivas de lag=0
    para considerar completado el procesamiento del backlog.
    También verifica si el Job ha sido cancelado o ha caído externamente en Flink.
    """
    stable_zero_count = 0
    while stable_zero_count < IDLE_STABLE_SAMPLES:
        # Verificar si el Job sigue en estado RUNNING en Flink
        active_job = _get_running_job_id()
        if not active_job or active_job != job_id:
            logger.warning(f"El Job {job_id} ya no está en estado RUNNING en Flink (Cancelado en la UI o caído). Finalizando monitoreo...")
            return

        lag = _get_kafka_consumer_lag()
        if lag == 0:
            stable_zero_count += 1
            logger.info(f"Lag cero verificado - sample={stable_zero_count}/{IDLE_STABLE_SAMPLES}")
        else:
            stable_zero_count = 0
            logger.info(f"Lag pendiente en Kafka - current_lag={lag}")
        time.sleep(IDLE_POLL_INTERVAL_S)

def _stop_with_savepoint(job_id: str) -> str:
    """
    Ejecuta 'flink stop' y realiza polling hasta confirmar la existencia del Savepoint en ADLS.
    """
    try:
        result = subprocess.run(
            ["flink", "stop", job_id, "--savepointPath", SAVEPOINT_DIR], 
            check=True, capture_output=True, text=True
        )
        out = result.stdout
        sp_path = None
        for line in out.split('\n'):
            if "Savepoint completed" in line or "Path:" in line:
                parts = line.split("Path:")
                if len(parts) > 1:
                    sp_path = parts[1].strip()
                    break
        
        if not sp_path:
            # Fallback buscando el ultimo savepoint en el directorio
            time.sleep(2)
            sp_path = find_latest_savepoint()
            
        if not sp_path:
            raise RuntimeError("Fallo crítico: No se pudo determinar la ruta del Savepoint tras detener el Job.")
            
        return str(sp_path)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error al detener con Savepoint - stderr={e.stderr}")
        raise

def rotate_savepoints(max_retained: int):
    """Lista, ordena y elimina Savepoints excedentes en ADLS."""
    all_sp = get_all_savepoints()
    to_delete = all_sp[:-max_retained] if len(all_sp) > max_retained else []
    for sp in to_delete:
        try:
            subprocess.run(["hadoop", "fs", "-rm", "-r", sp], check=True, capture_output=True)
            logger.info(f"Savepoint antiguo eliminado - path={sp}")
        except subprocess.CalledProcessError as e:
             logger.warning(f"No se pudo eliminar Savepoint - path={sp} error={e}")

def main():
    # 1. ACQUIRE LOCK
    if _lock_exists():
        if config.FLINK_FORCE_UNLOCK:
            logger.warning("Lock activo detectado, pero FLINK_FORCE_UNLOCK=true. Removiendo lock obsoleto...")
            _release_lock()
        else:
            logger.warning("Lock activo detectado - otra instancia del orquestador esta en ejecucion. Abortando. (Si fue un crash previo, usa FLINK_FORCE_UNLOCK=true para forzar el arranque).")
            sys.exit(0)
    _acquire_lock()
    
    try:
        # 2. PRE-FLIGHT CHECK
        job_id = _get_running_job_id()
        
        if job_id:
            logger.info(f"Job en estado RUNNING detectado - job_id={job_id}. Reanudando monitoreo.")
        else:
            # 3. SUBMIT JOB
            savepoint_path = find_latest_savepoint()
            job_id = _submit_job(savepoint_path)
            logger.info(f"Job enviado exitosamente - job_id={job_id}")
        
        # 4. IDLE DETECTION (via Kafka Consumer Group Lag & Flink Job Status)
        logger.info(f"Iniciando monitoreo de lag de Kafka - job_id={job_id}")
        _wait_until_idle(job_id)
        
        # Verificar si salimos porque el job se detuvo externamente
        if not _get_running_job_id():
            logger.info("El job ha finalizado o fue detenido externamente. Liberando recursos...")
            _clear_state(STATE_FILE)
            return

        logger.info(f"Lag cero confirmado - job_id={job_id}")
        
        # 5. GRACEFUL STOP CON SAVEPOINT
        logger.info(f"Iniciando parada de job con Savepoint - job_id={job_id}")
        new_savepoint_path = _stop_with_savepoint(job_id)
        logger.info(f"Savepoint confirmado en ADLS - path={new_savepoint_path}")
        
        # 6. ROTATION (no fatal si falla)
        try:
            rotate_savepoints(MAX_SAVEPOINTS)
            logger.info(f"Rotacion de Savepoints completada - max_retained={MAX_SAVEPOINTS}")
        except Exception as e:
            logger.warning(f"Error no critico durante rotacion de Savepoints - error={e}")
        
        _clear_state(STATE_FILE)
        logger.info(f"Ciclo del orquestador completado exitosamente - job_id={job_id}")
    
    except KeyboardInterrupt:
        logger.warning("Interrupcion manual detectada (CTRL+C). Generando Savepoint en ADLS antes de salir...")
        active_job = _get_running_job_id()
        if active_job:
            try:
                sp_path = _stop_with_savepoint(active_job)
                logger.info(f"Savepoint guardado exitosamente tras CTRL+C - path={sp_path}")
            except Exception as e:
                logger.error(f"No se pudo generar Savepoint durante CTRL+C - error={e}")
    except Exception as e:
        logger.error(f"Error critico en ejecucion del orquestador - error={e}", exc_info=True)
    
    finally:
        _release_lock()

if __name__ == "__main__":
    main()
