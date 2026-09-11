#!/usr/bin/env bash
# Ejecutar UNA SOLA VEZ
# Crea el Storage Account donde se almacenará el terraform.tfstate compartido.
#
# Prerequisitos:
#   1. Azure CLI instalado y autenticado (`az login`)
#   2. Suscripción Core seleccionada (`az account set --subscription <ID>`)
#
# Uso:
#   chmod +x setup_tf_backend.sh
#   ./setup_tf_backend.sh

set -euo pipefail

# --- Configuración -----------------------------------------------------------
RESOURCE_GROUP="rg-nautiq-tfstate-swc"
LOCATION="swedencentral"
STORAGE_ACCOUNT="stnautiqtfstate"
CONTAINER_NAME="tfstate"

echo "  Nautiq — Creando backend remoto para Terraform"

# 1. Resource Group
echo " Creando Resource Group: ${RESOURCE_GROUP}..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none

# 2. Storage Account
echo " Creando Storage Account: ${STORAGE_ACCOUNT}..."
az storage account create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${STORAGE_ACCOUNT}" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --location "${LOCATION}" \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --output none

# 3. Habilitar versionado de blobs
echo " Habilitando versionado de blobs..."
az storage account blob-service-properties update \
  --resource-group "${RESOURCE_GROUP}" \
  --account-name "${STORAGE_ACCOUNT}" \
  --enable-versioning true \
  --output none

# 4. Contenedor de blobs
echo " Creando contenedor: ${CONTAINER_NAME}..."
az storage container create \
  --name "${CONTAINER_NAME}" \
  --account-name "${STORAGE_ACCOUNT}" \
  --auth-mode login \
  --output none

echo ""
echo "  Backend remoto creado exitosamente"
echo ""
echo "  Valores en bloque 'backend' de Terraform:"
echo ""
echo "    backend \"azurerm\" {"
echo "      resource_group_name  = \"${RESOURCE_GROUP}\""
echo "      storage_account_name = \"${STORAGE_ACCOUNT}\""
echo "      container_name       = \"${CONTAINER_NAME}\""
echo "      key                  = \"core.terraform.tfstate\"   # o analytics.terraform.tfstate"
echo "    }"
echo ""
