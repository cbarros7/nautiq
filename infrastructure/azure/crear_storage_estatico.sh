#!/usr/bin/env bash
# ============================================================================
# Crea las dos cuentas de Storage con sitio estatico que sirven el frontal (DEV y PRO).
#
#   ./crear_storage_estatico.sh                  # simula, no crea nada
#   ./crear_storage_estatico.sh --crear          # crea
#   REGION=austriaeast ./crear_storage_estatico.sh --crear
#
# Solo se necesita si hay que recrear la infraestructura desde cero: los recursos ya existen
# (ver la tabla del final). El despliegue del dia a dia lo hace subir_estatico.sh.
#
# POR QUE STORAGE Y NO STATIC WEB APPS
# La politica de la suscripcion (Azure for Students) rechaza las CINCO regiones donde existe
# Static Web Apps —- comprobado una por una, falla con RequestDisallowedByAzure— y todos los
# recursos de la suscripcion viven en austriaeast, donde ese servicio no esta disponible.
# El portal falla igual: la politica se aplica tambien alli, no es una limitacion del CLI.
# Storage existe en practicamente cualquier region, incluida la permitida.
#
# Lo que se pierde frente a Static Web Apps:
#   - Deja de ser gratis, aunque cuesta centimos: unos MB y el trafico de un demo.
#   - No hay dominio propio con TLS automatico. El endpoint de Azure ya es HTTPS
#     (https://<cuenta>.z*.web.core.windows.net); un dominio propio requeriria Front Door.
#   - No hay previews por PR ni entornos de staging.
#   - El enrutado SPA se cubre con el documento de error: 404 -> index.html.
# ============================================================================
set -euo pipefail

CREAR=false
[[ "${1:-}" == "--crear" ]] && CREAR=true

# Region por defecto: la unica que la politica de la suscripcion admite, demostrado por que
# es donde ya viven el resto de recursos del proyecto.
REGION="${REGION:-austriaeast}"
SUFIJO="${SUFIJO:-aue}"

# Nombre de cuenta de almacenamiento: 3-24 caracteres, solo minusculas y digitos, y
# GLOBALMENTE unico en todo Azure. De ahi que no lleve guiones.
cuenta_de() { echo "stnautiqfront$1${SUFIJO}"; }
rg_de()     { echo "rg-nautiq-front-$1-${SUFIJO}"; }

ejecutar() { if $CREAR; then "$@"; else echo "    [simulacion] $*"; fi }

echo "== 1. Sesion =="
az account show -o none 2>/dev/null || { echo "  Sin sesion. Se abre con: az login --use-device-code"; exit 1; }
az account show --query "{suscripcion:name, id:id}" -o table
echo "  Esta es la suscripcion sobre la que se creara todo."
echo "  REGION: $REGION"

echo
echo "== 2. Nombres disponibles =="
for e in dev pro; do
  C=$(cuenta_de "$e")
  if [[ ${#C} -gt 24 ]]; then
    echo "  ERROR: '$C' tiene ${#C} caracteres (maximo 24). Se requiere un SUFIJO mas corto."; exit 1
  fi
  LIBRE=$(az storage account check-name --name "$C" --query nameAvailable -o tsv 2>/dev/null || echo desconocido)
  MOTIVO=$(az storage account check-name --name "$C" --query message -o tsv 2>/dev/null || true)
  if [[ "$LIBRE" == "true" ]]; then
    echo "  $C  libre"
  elif az storage account show -n "$C" -g "$(rg_de "$e")" -o none 2>/dev/null; then
    echo "  $C  ya pertenece al proyecto"
  else
    echo "  $C  OCUPADA: ${MOTIVO:-nombre en uso por otra suscripcion}"
    echo "     los nombres de cuenta son globales; se resuelve cambiando SUFIJO."
    exit 1
  fi
done

echo
echo "== 3. Grupos de recursos y cuentas =="
for e in dev pro; do
  G=$(rg_de "$e"); C=$(cuenta_de "$e")
  az group show -n "$G" -o none 2>/dev/null || ejecutar az group create -n "$G" -l "$REGION" -o none
  if az storage account show -n "$C" -g "$G" -o none 2>/dev/null; then
    echo "  ya existe: $C"
  else
    echo "  creando:   $C"
    # StorageV2 es el unico kind que admite sitio estatico. Hot y no Cool: esto se lee de
    # forma continua y Cool cobra por lectura.
    ejecutar az storage account create -n "$C" -g "$G" -l "$REGION" \
      --sku Standard_LRS --kind StorageV2 --access-tier Hot \
      --min-tls-version TLS1_2 --allow-blob-public-access true -o none
  fi
done

echo
echo "== 4. Activar el sitio estatico =="
for e in dev pro; do
  C=$(cuenta_de "$e")
  # 404 -> index.html hace de navigationFallback. La aplicacion no tiene rutas de cliente,
  # asi que con esto basta. Storage conserva el codigo 404, no lo reescribe a 200.
  ejecutar az storage blob service-properties update --account-name "$C" \
    --static-website true --index-document index.html --404-document index.html -o none
done

echo
echo "== 5. URLs =="
if ! $CREAR; then
  echo "  (en simulacion todavia no existen)"
else
  for e in dev pro; do
    C=$(cuenta_de "$e"); G=$(rg_de "$e")
    URL=$(az storage account show -n "$C" -g "$G" --query "primaryEndpoints.web" -o tsv)
    echo "  $e -> $URL"
  done
fi

cat <<'AYUDA'

== 6. Publicar el frontal ==

  ./subir_estatico.sh dev
  ./subir_estatico.sh pro

Construye con las VITE_* del entorno y publica. Se ejecuta con la sesion de `az` del
operador, sin credenciales guardadas en el repositorio.

Automatizarlo en GitHub Actions requeriria la clave de la cuenta como secreto o un service
principal; en un tenant universitario la creacion de service principals suele estar
restringida, y publicar a mano evita almacenar credenciales.
AYUDA
