# Nautiq Core — ADLS Gen2 (Data Lake Storage)

resource "azurerm_storage_account" "datalake" {
  name                     = "stnautiqdata${var.environment}${var.location_short}"
  resource_group_name      = azurerm_resource_group.core.name
  location                 = azurerm_resource_group.core.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true # Hierarchical Namespace = ADLS Gen2
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = false # No necesario para data lake append-only
  }

  tags = local.common_tags
}

# Contenedores - capas del Medallon
resource "azurerm_storage_container" "bronze" {
  name                  = "bronze"
  storage_account_id    = azurerm_storage_account.datalake.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "silver" {
  name                  = "silver"
  storage_account_id    = azurerm_storage_account.datalake.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "gold" {
  name                  = "gold"
  storage_account_id    = azurerm_storage_account.datalake.id
  container_access_type = "private"
}
