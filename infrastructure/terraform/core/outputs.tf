# Nautiq Core — Outputs

output "resource_group_name" {
  description = "Name of the core resource group"
  value       = azurerm_resource_group.core.name
}

output "key_vault_uri" {
  description = "URI of the Key Vault (for FastAPI's AZURE_KEY_VAULT_URI)"
  value       = azurerm_key_vault.main.vault_uri
}

output "key_vault_name" {
  description = "Name of the Key Vault"
  value       = azurerm_key_vault.main.name
}

output "managed_identity_client_id" {
  description = "Client ID of the Managed Identity (for azure.identity SDK)"
  value       = azurerm_user_assigned_identity.nautiq.client_id
}

output "datalake_account_name" {
  description = "Storage account name for ADLS Gen2"
  value       = azurerm_storage_account.datalake.name
}

output "datalake_primary_dfs_endpoint" {
  description = "DFS endpoint for ADLS Gen2 (used by Flink and Databricks)"
  value       = azurerm_storage_account.datalake.primary_dfs_endpoint
}

output "acr_login_server" {
  description = "ACR login server URL (for docker push)"
  value       = azurerm_container_registry.main.login_server
}

output "app_service_default_hostname" {
  description = "Default hostname of the App Service"
  value       = azurerm_linux_web_app.api.default_hostname
}
