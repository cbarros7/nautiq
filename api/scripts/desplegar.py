"""
Despliega el zip de la Function con el endpoint OneDeploy de Azure.

Por qué no se usa Azure/functions-action
----------------------------------------
Con perfil de publicación, esa action construye el hostname SCM clásico
`<app>.scm.azurewebsites.net`, que en Flex Consumption NO existe: el real
es regional y con hash (`<app>-<hash>.scm.<region>-01.azurewebsites.net`).
Falla con "zipDeploy ... Not Found (CODE: 404)", un error que parece del
paquete y en realidad es de resolución de host. El nombre correcto está
dentro del propio perfil, en `publishUrl`, que es de donde se lee aquí.

La vía oficial para Flex es azure/login + ARM, pero eso exige un service
principal que el tenant de la universidad no permite registrar.

Por qué en Python y no en el YAML con curl
------------------------------------------
La primera versión hacía `eval` de unas asignaciones generadas para pasar
usuario y contraseña a curl, y devolvía 401: las contraseñas de los
perfiles de Azure llevan caracteres que bash expande o parte ($, +...),
así que llegaban corruptas. Aquí las credenciales nunca pasan por un
shell, de modo que ese fallo no puede reproducirse.

Uso:
    python scripts/desplegar.py paquete.zip
    (el perfil de publicación se lee de la variable de entorno PERFIL)
"""

from __future__ import annotations

import base64
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

TIMEOUT_S = 300


def _credenciales(perfil_xml: str) -> tuple[str, str, str]:
    """Extrae (host_scm, usuario, contraseña) del perfil ZipDeploy."""
    raiz = ET.fromstring(perfil_xml)
    perfiles = raiz.findall("publishProfile")
    try:
        p = next(x for x in perfiles if x.get("publishMethod") == "ZipDeploy")
    except StopIteration:
        metodos = [x.get("publishMethod") for x in perfiles]
        raise SystemExit(f"El perfil no trae ZipDeploy; métodos disponibles: {metodos}")

    # publishUrl viene como "host:443"; OneDeploy va sobre HTTPS estándar.
    host = p.get("publishUrl", "").split(":")[0]
    usuario, contrasena = p.get("userName"), p.get("userPWD")
    if not (host and usuario and contrasena):
        raise SystemExit("El perfil de publicación está incompleto (falta host, usuario o contraseña).")
    return host, usuario, contrasena


def _publicar_host_app(host_scm: str) -> str:
    """
    Deriva el hostname público de la app y, en CI, lo expone como salida
    del paso (GITHUB_OUTPUT) para que la prueba de humo lo use.

    Existe porque componer `<app>.azurewebsites.net` a mano NO funciona en
    Flex Consumption: el hostname real lleva un hash y la región
    (`<app>-<hash>.<region>-01.azurewebsites.net`). Ese nombre no se puede
    adivinar desde el nombre de la app, pero sí se obtiene del perfil —el
    del SCM es el mismo quitando el ".scm"—, así que se deriva de ahí en
    vez de mantenerlo como otra variable de configuración que puede
    quedarse desincronizada.
    """
    host_app = host_scm.replace(".scm.", ".", 1)
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a", encoding="utf-8") as f:
            f.write(f"host_app={host_app}\n")
    print(f"Host público de la app: {host_app}")
    return host_app


def desplegar(zip_path: Path, perfil_xml: str) -> str:
    """Sube el paquete y devuelve el id de despliegue que responde Azure."""
    host, usuario, contrasena = _credenciales(perfil_xml)

    # GitHub enmascara el secret completo, pero NO los valores derivados de
    # él: sin esto, la contraseña aparecería en claro en cualquier traza.
    print(f"::add-mask::{contrasena}")
    print(f"Desplegando {zip_path.name} ({zip_path.stat().st_size / 1024:.0f} KB) a {host}")

    autorizacion = base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()
    peticion = urllib.request.Request(
        f"https://{host}/api/publish?RemoteBuild=true",
        data=zip_path.read_bytes(),
        method="POST",
        headers={
            "Authorization": f"Basic {autorizacion}",
            "Content-Type": "application/zip",
        },
    )

    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", "replace").strip()
            print(f"Aceptado (HTTP {respuesta.status}), id de despliegue: {cuerpo}")
            _publicar_host_app(host)
            return cuerpo
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace").strip()
        pista = ""
        if exc.code == 401:
            pista = (
                " — revisa que el secret lleve el XML COMPLETO del perfil y que la "
                "autenticación básica de SCM siga habilitada en la app "
                "(basicPublishingCredentialsPolicies/scm, properties.allow=true)."
            )
        print(f"::error::OneDeploy devolvió HTTP {exc.code}{pista}\n{detalle}")
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/desplegar.py <paquete.zip>")
    perfil = os.environ.get("PERFIL")
    if not perfil:
        raise SystemExit("Falta la variable de entorno PERFIL con el perfil de publicación.")
    desplegar(Path(sys.argv[1]), perfil)
