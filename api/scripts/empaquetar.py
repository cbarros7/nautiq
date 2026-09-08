"""
Empaqueta la Function en un zip listo para desplegar.

Existe porque el despliegue ya no lo hace `Azure/functions-action` (ver
.github/workflows/deploy_function.yml): esa action, con perfil de
publicación, construye el hostname SCM clásico `<app>.scm.azurewebsites.net`,
que en Flex Consumption NO existe —el real es regional y con hash— y falla
con un 404 confuso. El despliegue se hace ahora con un POST directo al
endpoint OneDeploy, así que el zip hay que armarlo aquí.

Las exclusiones se leen de `.funcignore` en vez de repetirlas: si se
duplicaran, acabarían divergiendo y el paquete llevaría cosas que el
despliegue manual con `func` sí deja fuera (secretos incluidos).

Uso:
    python scripts/empaquetar.py salida.zip
"""

from __future__ import annotations

import fnmatch
import os
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _patrones_funcignore() -> list[str]:
    """Lee .funcignore (una línea por patrón, '#' comenta)."""
    fichero = RAIZ / ".funcignore"
    if not fichero.exists():
        return []
    return [
        linea.strip().rstrip("/")
        for linea in fichero.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
    ]


def _ignorado(ruta_rel: str, patrones: list[str]) -> bool:
    """
    True si la ruta (o cualquiera de sus carpetas padre) casa con un patrón.

    Se comprueba cada segmento por separado para que un patrón de
    directorio como "scripts" excluya todo su contenido, no solo la
    entrada del propio directorio.
    """
    partes = Path(ruta_rel).parts
    for patron in patrones:
        if any(fnmatch.fnmatch(p, patron) for p in partes):
            return True
        if fnmatch.fnmatch(ruta_rel, patron):
            return True
    return False


def empaquetar(destino: Path) -> tuple[int, int]:
    """Crea el zip y devuelve (nº de ficheros, bytes)."""
    patrones = _patrones_funcignore()
    destino.parent.mkdir(parents=True, exist_ok=True)

    incluidos = 0
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for carpeta, subcarpetas, ficheros in os.walk(RAIZ):
            rel_carpeta = Path(carpeta).relative_to(RAIZ)
            # Poda in-situ: evita descender en .venv y demás, que además de
            # inútil sería lentísimo.
            subcarpetas[:] = [
                d for d in subcarpetas
                if not d.startswith(".") and not _ignorado(str(rel_carpeta / d), patrones)
            ]
            for fichero in ficheros:
                rel = (rel_carpeta / fichero).as_posix().lstrip("./")
                if _ignorado(rel, patrones):
                    continue
                z.write(Path(carpeta) / fichero, rel)
                incluidos += 1

    return incluidos, destino.stat().st_size


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/empaquetar.py <salida.zip>")
    n, tam = empaquetar(Path(sys.argv[1]))
    print(f"{n} ficheros, {tam / 1024:.0f} KB -> {sys.argv[1]}")
