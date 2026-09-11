#!/usr/bin/env bash
# entrypoint.sh — Substituye los placeholders de core-site.xml con los valores
# reales de las variables de entorno ANTES de que Flink/Hadoop arranque.
set -euo pipefail

CORE_SITE="/opt/hadoop/etc/hadoop/core-site.xml"

# Escapar caracteres especiales para sed
ACCOUNT="${AZURE_STORAGE_ACCOUNT:-}"
# La clave puede contener /, + y = que son especiales en sed → usamos | como separador
KEY="${AZURE_STORAGE_KEY:-}"

if [[ -n "${ACCOUNT}" && -n "${KEY}" ]]; then
    sed -i "s|STORAGE_ACCOUNT_PLACEHOLDER|${ACCOUNT}|g" "${CORE_SITE}"
    # Para la clave usamos python para evitar problemas con caracteres especiales
    python3 -c "
import re, os, sys
path = '${CORE_SITE}'
with open(path) as f:
    content = f.read()
content = content.replace('STORAGE_KEY_PLACEHOLDER', os.environ['AZURE_STORAGE_KEY'])
with open(path, 'w') as f:
    f.write(content)
print('[entrypoint] core-site.xml configurado con AZURE_STORAGE_KEY')
"
else
    echo "[entrypoint] WARNING: AZURE_STORAGE_ACCOUNT o AZURE_STORAGE_KEY no están definidas. ADLS no estará disponible."
fi

# Sincronizar y configurar el almacén de certificados SSL de Java (cacerts)
if [[ -f "/opt/java/openjdk/lib/security/cacerts" ]]; then
    echo "[entrypoint] Sincronizando certificados raíz en cacerts de Java..."
    mkdir -p /etc/ssl/certs/java 2>/dev/null || true
    cp -f /opt/java/openjdk/lib/security/cacerts /etc/ssl/certs/java/cacerts 2>/dev/null || true
    
    # Sincronizar también con OpenJDK de Debian si existe
    for jvm_sec in /usr/lib/jvm/*/lib/security; do
        if [[ -d "$jvm_sec" ]]; then
            cp -f /opt/java/openjdk/lib/security/cacerts "$jvm_sec/cacerts" 2>/dev/null || true
        fi
    done
fi

# Importar certificado de Azure Function en el cacerts si está disponible
AZURE_CERT="/opt/flink/usrlib/src/azure_function_cert_prod.pem"
if [[ ! -f "$AZURE_CERT" ]]; then
    AZURE_CERT="/opt/flink/usrlib/src/azure_function_cert.pem"
fi
if [[ -f "$AZURE_CERT" && -f "/opt/java/openjdk/lib/security/cacerts" ]]; then
    echo "[entrypoint] Importando certificado de Azure Function ($AZURE_CERT) en cacerts..."
    keytool -importcert -noprompt -trustcacerts -alias azurefunction \
        -file "$AZURE_CERT" \
        -keystore /opt/java/openjdk/lib/security/cacerts \
        -storepass changeit 2>/dev/null || true
    cp -f /opt/java/openjdk/lib/security/cacerts /etc/ssl/certs/java/cacerts 2>/dev/null || true
fi

# Delegar al entrypoint oficial de Flink
exec /docker-entrypoint.sh "$@"
