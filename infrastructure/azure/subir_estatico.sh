#!/usr/bin/env bash
# ============================================================================
# Construye el frontal para un entorno y lo publica en su sitio estatico de Storage.
#
#   ./subir_estatico.sh dev
#   ./subir_estatico.sh pro
#   ./subir_estatico.sh dev --muestra     # sube el fixture, para probar la cadena
#
# Se ejecuta con la sesion de `az` del operador (`az login --use-device-code`), de modo que
# no hace falta guardar ninguna credencial en el repositorio ni en GitHub.
#
# Las variables de Supabase se resuelven por orden:
#   1. del entorno (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY)
#   2. de frontend/.env.<entorno>   (fichero local, ignorado por git)
#   3. de frontend/.env
# ============================================================================
set -euo pipefail

ENTORNO="${1:-}"
case "$ENTORNO" in
  dev) NAUTIQ_ENV=DEV ;;
  pro) NAUTIQ_ENV=PRO ;;
  *) echo "Uso: $0 dev|pro [--muestra]"; exit 1 ;;
esac

# --muestra: publica con el FIXTURE en lugar de con la tabla. Sirve para validar la cadena
# de despliegue antes de disponer de las credenciales de Supabase. No se admite en pro:
# produccion no debe mostrar datos de ejemplo ni de forma temporal.
MUESTRA=false
if [[ "${2:-}" == "--muestra" ]]; then
  if [[ "$ENTORNO" == "pro" ]]; then
    echo "--muestra no se admite en pro: produccion no debe servir datos de ejemplo."
    exit 1
  fi
  MUESTRA=true
fi

SUFIJO="${SUFIJO:-aue}"
CUENTA="stnautiqfront${ENTORNO}${SUFIJO}"
GRUPO="rg-nautiq-front-${ENTORNO}-${SUFIJO}"
# La raiz se deduce de la ubicacion del script; REPO la sobreescribe si se invoca desde otro
# sitio o sobre una copia de trabajo distinta.
RAIZ="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
FRONT="$RAIZ/frontend"

if [[ ! -d "$FRONT" ]]; then
  echo "No se encuentra el repositorio en '$RAIZ'. La ruta se indica con:  REPO=/ruta/a/nautiq $0 $*"
  exit 1
fi

az account show -o none 2>/dev/null || { echo "Sin sesion de Azure. Se abre con: az login --use-device-code"; exit 1; }

# --- credenciales de Supabase -------------------------------------------------
for f in "$FRONT/.env.$ENTORNO" "$FRONT/.env"; do
  if [[ -f "$f" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$f"; set +a
    break
  fi
done
if ! $MUESTRA && [[ -z "${VITE_SUPABASE_URL:-}" || -z "${VITE_SUPABASE_ANON_KEY:-}" ]]; then
  echo "Faltan VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY."
  echo "Se definen en frontend/.env.$ENTORNO o se exportan antes de ejecutar."
  echo "Sin ellas el frontal arrancaria con datos de ejemplo; para probar solo la cadena de"
  echo "despliegue existe:  $0 $ENTORNO --muestra"
  exit 1
fi

echo "== Construyendo para $NAUTIQ_ENV =="
$MUESTRA && echo "   MODO MUESTRA: se publica el fixture, no la tabla."
cd "$FRONT"
npm ci --no-fund --no-audit --silent
VITE_NAUTIQ_ENV="$NAUTIQ_ENV" \
VITE_USE_MOCK="$($MUESTRA && echo true || echo false)" \
VITE_SUPABASE_URL="${VITE_SUPABASE_URL:-}" \
VITE_SUPABASE_ANON_KEY="${VITE_SUPABASE_ANON_KEY:-}" \
VITE_ORACLE_RECOMMENDATIONS_TABLE="${VITE_ORACLE_RECOMMENDATIONS_TABLE:-}" \
  npm run build

echo
echo "== Subiendo a $CUENTA =="
# `--auth-mode login` no sirve aqui aunque la cuenta sea Owner de la suscripcion: Owner es
# plano de CONTROL, y escribir blobs es plano de DATOS (requeriria el rol "Storage Blob Data
# Contributor", que se asigna aparte). Se lee la clave al vuelo —- eso si lo permite Owner— y
# se pasa a cada comando. La clave no se persiste: vive en esta variable mientras dura el
# proceso.
CLAVE=$(az storage account keys list -n "$CUENTA" -g "$GRUPO" --query "[0].value" -o tsv)

# Dos pasadas de cache DISTINTAS, y la diferencia importa:
#   - /assets/* llevan hash en el nombre, asi que admiten cache de un ano.
#   - index.html NO lleva hash: si se cachea, un redespliegue sigue sirviendo el bundle
#     anterior hasta que caduque. Va con no-store.
az storage blob upload-batch --account-name "$CUENTA" --account-key "$CLAVE" \
  -d '$web/assets' -s dist/assets --overwrite \
  --content-cache "public, max-age=31536000, immutable" -o none

az storage blob upload-batch --account-name "$CUENTA" --account-key "$CLAVE" \
  -d '$web' -s dist --pattern '*.html' --overwrite \
  --content-cache "no-store" -o none

URL=$(az storage account show -n "$CUENTA" -g "$GRUPO" --query "primaryEndpoints.web" -o tsv)
echo
echo "Publicado: $URL"
echo "La cabecera debe mostrar la chapa $NAUTIQ_ENV y la tabla correspondiente."
