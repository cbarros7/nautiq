import asyncio
import websockets
import json
import os

import config


# ==========================================
# GESTIÓN DE ESTADO COMPARTIDO - Modular
# ==========================================
class PortState:
    def __init__(self):
        self.anchored_ships = set()


# ==========================================
# RUTINAS - Módulos independientes
# ==========================================
def load_targets():
    """Carga los MMSIs obtenidos en la Fase 1."""
    if os.path.exists(config.MMSI_TARGETS_FILE):
        with open(config.MMSI_TARGETS_FILE, "r") as f:
            return json.load(f)
    return []


async def flota_tracker(api_key, mmsi_list, message_queue):
    """Fase 2: Conexión global para rastrear nuestra flota."""
    if not mmsi_list:
        print("[INFO][Flota] No hay barcos en el archivo JSON. Omite rastreo global.")
        return

    print(f"[INICIO][Flota] Iniciando rastreo global para {len(mmsi_list)} barcos...")

    # Recordatorio: La API limita a 50 MMSIs por conexión.
    # En este MVP cogemos solo los primeros 50 para garantizar que funcione.
    subscribe_message = {
        "APIKey": api_key,
        "BoundingBoxes": config.GLOBAL_BOUNDING_BOX,
        "FiltersShipMMSI": [str(mmsi) for mmsi in mmsi_list][:50],
        "FilterMessageTypes": ["PositionReport"],
    }

    try:
        async with websockets.connect(config.AISSTREAM_URL) as websocket:
            await websocket.send(json.dumps(subscribe_message))
            async for msg_str in websocket:
                data = json.loads(msg_str)
                await message_queue.put(("flota", data))
    except asyncio.CancelledError:
        print("[INFO][Flota] Tarea cancelada. Cerrando conexión.")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[ADVERTENCIA][Flota] Desconectado: {e}")


async def puerto_monitor(api_key, message_queue):
    """Fase 3: Conexión local en Valencia sin filtros de MMSI."""
    print("[INICIO][Puerto] Iniciando monitorización del área de Valencia...")

    subscribe_message = {
        "APIKey": api_key,
        "BoundingBoxes": config.VALENCIA_BOUNDING_BOX,
        "FilterMessageTypes": ["PositionReport"],
    }

    try:
        async with websockets.connect(config.AISSTREAM_URL) as websocket:
            await websocket.send(json.dumps(subscribe_message))
            async for msg_str in websocket:
                data = json.loads(msg_str)
                await message_queue.put(("puerto", data))
    except asyncio.CancelledError:
        print("[INFO][Puerto] Tarea cancelada. Cerrando conexión.")
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[ADVERTENCIA][Puerto] Desconectado: {e}")


async def data_processor(message_queue, target_mmsis, port_state: PortState):
    """Procesador asíncrono. Actúa como si fuera el 'suscriptor' de Kafka o Redis."""
    target_status_history = {}  # Diccionario para rastrear el último estado conocido de nuestra flota

    try:
        while True:
            source, data = await message_queue.get()

            if data.get("MessageType") == "PositionReport":
                msg = data["Message"]["PositionReport"]
                mmsi = msg["UserID"]
                status = msg["NavigationalStatus"]

                # ---------------------------------------------------------
                # DETECCIÓN DE CAMBIOS DE ESTADO PARA NUESTRA FLOTA
                # ---------------------------------------------------------
                if mmsi in target_mmsis:
                    if mmsi in target_status_history:
                        old_status = target_status_history[mmsi]
                        if old_status != status:
                            print(
                                f"[CAMBIO ESTADO] El barco objetivo {mmsi} ha cambiado su estado operativo: {old_status} -> {status}"
                            )

                    # Actualizamos el historial con el estado actual
                    target_status_history[mmsi] = status

                # ---------------------------------------------------------
                # LÓGICA DE FUENTES (PUERTO VS GLOBAL)
                # ---------------------------------------------------------
                if source == "puerto":
                    # Lógica de Congestión Local
                    if status in (
                        1,
                        5,
                    ):  # 1 = Fondeado (At Anchor), 5 = Amarrado (Moored)
                        port_state.anchored_ships.add(mmsi)
                    else:
                        port_state.anchored_ships.discard(mmsi)

                    # Cruce de datos: ¡Un barco de nuestra lista ha entrado en Valencia!
                    if mmsi in target_mmsis:
                        # Nota: Esto imprimirá varias veces si el barco sigue mandando señal dentro.
                        # En el futuro se puede añadir una validación para imprimir solo la primera vez.
                        print(
                            f"[ALERTA LLEGADA] Nuestro barco de carga {mmsi} detectado DENTRO DE VALENCIA. Estado: {status}"
                        )

                elif source == "flota":
                    # Rastreo global de la flota
                    pass

            message_queue.task_done()
    except asyncio.CancelledError:
        pass


async def log_congestion(port_state: PortState):
    """Tarea auxiliar para imprimir métricas del puerto cada minuto."""
    try:
        while True:
            await asyncio.sleep(60)
            print(
                f"[MÉTRICA] Barcos fondeados/amarrados en Valencia: {len(port_state.anchored_ships)}"
            )
    except asyncio.CancelledError:
        pass


# ==========================================
# ORQUESTADOR PRINCIPAL
# ==========================================
async def main():
    api_key = config.AISSTREAM_API_KEY
    if not api_key:
        print("[ERROR] API KEY no configurada.")
        return

    target_mmsis = load_targets()
    state = PortState()

    # Cola unificada de mensajes (simulando un Broker como Kafka/Redis)
    queue = asyncio.Queue()

    # Lanzar tareas concurrentes
    print(
        f"[INICIO] Arrancando arquitectura de Tracker (Límite: {config.TRACKER_DURATION_SECONDS / 60} minutos)..."
    )
    tasks = [
        asyncio.create_task(flota_tracker(api_key, target_mmsis, queue)),
        asyncio.create_task(puerto_monitor(api_key, queue)),
        asyncio.create_task(data_processor(queue, set(target_mmsis), state)),
        asyncio.create_task(log_congestion(state)),
    ]

    # Mantener el bucle vivo el tiempo solicitado por el MVP
    await asyncio.sleep(config.TRACKER_DURATION_SECONDS)

    print("\n[INFO] Tiempo de monitorización cumplido. Apagando el sistema modular...")
    for t in tasks:
        t.cancel()

    # Esperar el cierre ordenado
    await asyncio.gather(*tasks, return_exceptions=True)
    print("[FIN] Sistemas apagados. ¡MVP finalizado!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPCIÓN] Interrupción manual. Apagando...")
