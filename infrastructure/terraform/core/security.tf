# Nautiq Core — Security (Key Vault + Managed Identity)

data "azurerm_client_config" "current" {}

# User Assigned Managed Identity

resource "azurerm_user_assigned_identity" "nautiq" {
  name                = "id-nautiq-${var.environment}-${var.location_short}"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location

  tags = local.common_tags
}

# Azure Key Vault
resource "azurerm_key_vault" "main" {
  name                       = "kv-nautiq-${var.environment}-${var.location_short}"
  resource_group_name        = azurerm_resource_group.core.name
  location                   = azurerm_resource_group.core.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false # MVP: permitir borrado limpio
  soft_delete_retention_days = 7

  enable_rbac_authorization = true

  tags = local.common_tags
}

# RBAC: Managed Identity → Key Vault Secrets User
resource "azurerm_role_assignment" "identity_kv_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.nautiq.principal_id
}

# RBAC: Deployer → Key Vault Secrets Officer
resource "azurerm_role_assignment" "deployer_kv_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}
