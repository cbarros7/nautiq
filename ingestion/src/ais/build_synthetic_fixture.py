"""
Genera `synthetic_fixtures.json` a partir de los ficheros REALES locales
(`data/reference/thetis_mrv.xlsx`, `data/reference/un_locode.csv`), sin tocar
Postgres. Herramienta de desarrollo, no se importa desde `synthetic.py` ni desde
ningún camino de producción — se ejecuta a mano cuando hace falta rehacer la
flota (más buques, otra mezcla de categorías, otros puertos):

    uv run python -m ingestion.src.ais.build_synthetic_fixture

Para cambiar el tamaño de la flota, edita las cantidades de `muestra(...)` más
abajo (mantén la proporción entre categorías si quieres seguir siendo fiel a la
distribución medida en `docs/ais_catalogos.md`) y vuelve a ejecutar.
"""
import hashlib
import json
import random
import warnings

warnings.filterwarnings("ignore")

from ingestion.src.reference import locode, thetis

random.seed(20260809)  # reproducible

_ROMANOS = ["", "II", "III", "IV", "V", "VI", "VII", "VIII"]

TARGET_LOCODES = {"ESVLC", "ESALG", "ESBCN"}
OTHER_LOCODES = [
    "MATNG", "ITGOA", "ITGIT", "ITNAP", "ITLIV", "FRMRS", "GRPIR", "MTMLA",
    "PTLIS", "PTSIE", "MACAS", "ESALC", "ESCAR", "FRFOS", "TNTUN", "ESPMI",
    "ESLPA", "PTPDL",
]

NOMBRES_RECREO = ["ALEGRIA", "BRISA", "SOL NACIENTE", "MAR AZUL", "LIBERTAD",
                  "ESTRELLA DEL SUR", "VIENTO FRESCO", "AURORA", "PACIFICA",
                  "SIRENA", "HORIZONTE", "ILUSION", "AMANECER", "TRAMONTANA"]
NOMBRES_PESCA = ["NUEVA ESPERANZA", "SAN PEDRO", "VIRGEN DEL MAR", "DOS HERMANOS",
                 "PUNTA FARO", "COSTA BRAVA", "MARINERO FIEL"]
NOMBRES_REMOLQUE = ["REMOLCADOR", "PUERTO NORTE", "BAHIA TUG", "ATLAS",
                    "HERCULES", "NEPTUNO", "TRITON"]
NOMBRES_VELA = ["ALBATROS", "GAVIOTA", "PONIENTE", "MISTRAL", "VELERO DEL SUR"]
NOMBRES_OTROS = ["PATRULLA COSTERA", "GUARDACOSTAS", "PRACTICO DE PUERTO",
                 "SUMINISTROS MAR", "AUXILIAR PORTUARIO"]
_CODIGOS_OTROS = [0, 33, 51, 53, 90]


def _nombre_ciclico(base_list: list[str], idx: int) -> str:
    """Reutiliza nombres con sufijo romano (como la flota pesquera real) en vez de
    inventar uno por buque: en AIS solo el MMSI es único, el nombre no."""
    base = base_list[idx % len(base_list)]
    vuelta = idx // len(base_list)
    return f"{base} {_ROMANOS[vuelta]}".strip() if vuelta else base


def _muestra(by_type: dict, tipo: str, n: int, ya_usados: set[int]) -> list[dict]:
    """
    Muestrea `n` filas de THETIS del `tipo` dado, excluyendo IMOs ya elegidos por
    OTRA llamada anterior. Necesario porque "Ro-pax ship" se pide dos veces (para
    `ro_ro` y para `passenger`) con sorteos que si no se coordinan entre sí pueden
    sacar el MISMO buque real dos veces -> dos objetos de buque simulados
    independientes con el mismo IMO (y, tras el fix de MMSI estable, el mismo
    MMSI) moviéndose a la vez. `ya_usados` es compartido entre todas las llamadas
    de un `build()`, así que nunca se repite un IMO entre categorías.
    """
    pool = [r for r in by_type.get(tipo, []) if r["imo"] not in ya_usados]
    if len(pool) < n:
        print(f"[!] {tipo!r}: solo {len(pool)} disponibles en THETIS (tras excluir "
              f"ya usados), pedidas {n}")
    elegidos = random.sample(pool, min(n, len(pool)))
    ya_usados.update(r["imo"] for r in elegidos)
    return elegidos


def build(path: str = "ingestion/src/ais/synthetic_fixtures.json") -> None:
    all_ports = {r["locode"]: r for r in locode.build_rows() if r["lat"] and r["lon"]}
    ports_out = {lc: all_ports[lc] for lc in TARGET_LOCODES | set(OTHER_LOCODES)
                if lc in all_ports}
    print(f"puertos: {len(ports_out)}")

    rows = thetis.build_rows()
    by_type: dict = {}
    for r in rows:
        by_type.setdefault(r["ship_type"], []).append(r)

    ya_usados_thetis: set[int] = set()

    def add(tipo, n, categoria, ais_types):
        for r in _muestra(by_type, tipo, n, ya_usados_thetis):
            vessels.append({"imo": r["imo"], "name": r["name"], "category": categoria,
                            "ais_types": ais_types})

    vessels: list[dict] = []
    # Carga (AIS 70-79): mayoría portacontenedores, foco del negocio.
    add("Container ship", 52, "container", [70, 71, 74, 79])
    add("Bulk carrier", 32, "bulk", [70, 79])
    add("General cargo ship", 10, "general_cargo", [70, 79])
    add("Ro-pax ship", 6, "ro_ro", [70, 79])
    # Tanque (AIS 80-89).
    add("Oil tanker", 20, "tanker", [80, 81, 89])
    add("Chemical tanker", 16, "tanker", [80, 81, 89])
    add("Gas carrier", 6, "tanker", [80, 89])
    add("LNG carrier", 6, "tanker", [80, 89])
    # Pasaje (AIS 60-69).
    add("Ro-pax ship", 14, "passenger", [60, 69])
    add("Other ship types", 12, "passenger", [60, 69])

    n_thetis = len(vessels)
    print(f"con IMO real (THETIS): {n_thetis}")

    # Categorías pequeñas: sin equivalente en THETIS (no reportan MRV) -> imo=0,
    # igual que en AIS real (las embarcaciones pequeñas no llevan número IMO).
    for i in range(20):
        vessels.append({"imo": 0, "name": _nombre_ciclico(NOMBRES_RECREO, i),
                        "category": "recreational", "ais_types": [37]})
    for i in range(14):
        vessels.append({"imo": 0, "name": _nombre_ciclico(NOMBRES_PESCA, i),
                        "category": "fishing", "ais_types": [30]})
    for i in range(14):
        vessels.append({"imo": 0, "name": _nombre_ciclico(NOMBRES_REMOLQUE, i),
                        "category": "tug", "ais_types": [31, 32, 52]})
    for i in range(10):
        vessels.append({"imo": 0, "name": _nombre_ciclico(NOMBRES_VELA, i),
                        "category": "sailing", "ais_types": [36]})
    for i in range(10):
        vessels.append({"imo": 0, "name": _nombre_ciclico(NOMBRES_OTROS, i),
                        "category": "other", "ais_types": [_CODIGOS_OTROS[i % 5]]})

    print(f"sin IMO (categorías pequeñas): {len(vessels) - n_thetis}")
    print(f"TOTAL flota: {len(vessels)}")

    # MMSI sintéticos: prefijo 990 (no es un MID real asignado a buques), marcador
    # explícito de tráfico simulado si algún día se mezcla con datos reales.
    #
    # Derivado de la IDENTIDAD del buque (IMO real, o categoría+nombre para las
    # embarcaciones pequeñas sin IMO), nunca de su posición en la lista. Así, al
    # regenerar el fixture con más buques o distinto muestreo, un buque que ya
    # existía conserva el MISMO MMSI. Con posición (`990_000_000 + i`) un mismo
    # MMSI pasaba a representar un IMO distinto entre una regeneración y la
    # siguiente — cualquier estado con TTL largo en Flink (o una tabla de buques
    # persistida) acumula ambos pares y ve "un MMSI con más de un IMO/buque".
    #
    # La resolución de colisiones de hash (~3% de probabilidad de que exista
    # alguna con ~250 buques en 1.000.000 de huecos) se decide por CONTENIDO
    # (hash, luego clave en orden alfabético), no por el orden en que aparece
    # cada buque en `vessels` — ese orden cambia entre regeneraciones si cambia
    # cuántos buques se muestrean, y decidir el ganador por orden de lista
    # reintroduciría la misma inestabilidad de MMSI que este esquema corrige.
    claves = [f"imo:{v['imo']}" if v["imo"] else f"synthetic:{v['category']}:{v['name']}"
             for v in vessels]
    hash_de = {c: int(hashlib.sha256(c.encode()).hexdigest(), 16) % 1_000_000 for c in set(claves)}

    mmsi_de: dict[str, int] = {}
    usados: set[int] = set()
    for clave in sorted(set(claves), key=lambda c: (hash_de[c], c)):
        suf = hash_de[clave]
        while suf in usados:  # colisión -> siguiente hueco libre, determinista
            suf = (suf + 1) % 1_000_000
        usados.add(suf)
        mmsi_de[clave] = 990_000_000 + suf

    for i, (v, clave) in enumerate(zip(vessels, claves)):
        v["mmsi"] = mmsi_de[clave]
        v["callsign"] = f"SYN{i + 1:04d}"
        v["imo"] = v["imo"] or None

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ports": ports_out, "vessels": vessels}, f, ensure_ascii=False, indent=1)

    import collections
    import os
    print(f"\nescrito {path} ({os.path.getsize(path) / 1024:.1f} KB)")
    for cat, n in collections.Counter(v["category"] for v in vessels).most_common():
        print(f"  {cat:15s} {n:3d}")


if __name__ == "__main__":
    build()
