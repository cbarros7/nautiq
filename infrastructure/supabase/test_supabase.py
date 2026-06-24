import os
import asyncio
import random
from dotenv import load_dotenv
from supabase import create_client, Client


async def main():
    # Cargar variables de entorno desde .env
    load_dotenv()

    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print(
            "Faltan credenciales. Por favor añade SUPABASE_URL y SUPABASE_KEY en el archivo .env"
        )
        return

    print("Conectando a Supabase de forma exitosa")
    supabase: Client = create_client(url, key)

    try:
        # Definir varias opciones base de barcos
        vessels_pool = [
            {"name": "MALLORCA FERRY", "base_lat": 39.5696, "base_lon": 2.6502},
            {"name": "IBIZA YACHT", "base_lat": 38.9067, "base_lon": 1.4206},
            {"name": "MENORCA SAIL", "base_lat": 39.8879, "base_lon": 4.2546},
            {"name": "FORMENTERA FAST", "base_lat": 38.7226, "base_lon": 1.4290},
            {"name": "VALENCIA CARGO", "base_lat": 39.4699, "base_lon": -0.3774},
        ]

        # Escoger uno al azar y generarle un MMSI aleatorio para que siempre sea un registro nuevo
        chosen = random.choice(vessels_pool)
        random_vessel = {
            "mmsi": f"224{random.randint(100000, 999999)}",
            "name": chosen["name"],
            # Variar ligeramente la lat/lon simulando movimiento
            "lat": round(chosen["base_lat"] + random.uniform(-0.05, 0.05), 4),
            "lon": round(chosen["base_lon"] + random.uniform(-0.05, 0.05), 4),
        }

        print(
            f"Insertando barco aleatorio: {random_vessel['name']} (MMSI: {random_vessel['mmsi']})..."
        )
        supabase.table("vessels").insert(random_vessel).execute()

        # Consultar la tabla
        print("Consultando registros en la tabla 'vessels'...")
        response = supabase.table("vessels").select("*").execute()

        vessels = response.data
        print(f"Se encontraron {len(vessels)} barcos:")
        for v in vessels:
            print(
                f"MMSI: {v['mmsi']} | Nombre: {v['name']} | Coords: {v['lat']}, {v['lon']}"
            )

    except Exception as e:
        print(f"Error al interactuar con Supabase: {e}")


if __name__ == "__main__":
    asyncio.run(main())
