# Nautiq Core — Compute (ACR + App Service)

# Azure Container Registry
resource "azurerm_container_registry" "main" {
  name                = "crnautiq${var.environment}${var.location_short}"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  sku                 = "Basic"
  admin_enabled       = true # Necesario para App Service pull en Basic tier

  tags = local.common_tags
}

# App Service Plan (Linux)
resource "azurerm_service_plan" "main" {
  name                = "plan-nautiq-${var.environment}-${var.location_short}"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku

  tags = local.common_tags
}

# App Service - Web App
resource "azurerm_linux_web_app" "api" {
  name                = "app-nautiq-core-${var.environment}-${var.location_short}"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
  service_plan_id     = azurerm_service_plan.main.id

  # Managed Identity para acceder a Key Vault sin credenciales
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.nautiq.id]
  }

  site_config {
    always_on = var.app_service_sku != "F1" # F1 no soporta always_on

    application_stack {
      docker_registry_url      = "https://${azurerm_container_registry.main.login_server}"
      docker_image_name        = "nautiq-api:latest"
      docker_registry_username = azurerm_container_registry.main.admin_username
      docker_registry_password = azurerm_container_registry.main.admin_password
    }
  }

  app_settings = {
    # Key Vault URI para que FastAPI sepa dónde buscar secretos
    "AZURE_KEY_VAULT_URI" = azurerm_key_vault.main.vault_uri

    # Managed Identity Client ID para la SDK de Azure Identity
    "AZURE_CLIENT_ID" = azurerm_user_assigned_identity.nautiq.client_id

    # Docker config
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "DOCKER_ENABLE_CI"                    = "true"
  }

  tags = local.common_tags
}
