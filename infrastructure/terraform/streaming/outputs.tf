# ==============================================================================
# Nautiq Streaming — Outputs (Azure)
# ==============================================================================

# DEV
output "dev_vm_public_ip" {
  description = "Dirección IP pública de la máquina de DEV"
  value       = var.enable_dev ? azurerm_public_ip.dev[0].ip_address : null
}

output "dev_ssh_command" {
  description = "Comando para conectarse por SSH a la VM de DEV"
  value       = var.enable_dev ? "ssh ${var.admin_username}@${azurerm_public_ip.dev[0].ip_address}" : null
}

output "dev_flink_ui_url" {
  description = "URL del Dashboard de Flink en DEV"
  value       = var.enable_dev ? "http://${azurerm_public_ip.dev[0].ip_address}:8081" : null
}

# PROD
output "prod_vm_public_ip" {
  description = "Dirección IP pública de la máquina de PROD"
  value       = var.enable_prod ? azurerm_public_ip.prod[0].ip_address : null
}

output "prod_ssh_command" {
  description = "Comando para conectarse por SSH a la VM de PROD"
  value       = var.enable_prod ? "ssh ${var.admin_username}@${azurerm_public_ip.prod[0].ip_address}" : null
}

output "prod_flink_ui_url" {
  description = "URL del Dashboard de Flink en PROD (puerto 8082 si corre run_flink.sh --env prod)"
  value       = var.enable_prod ? "http://${azurerm_public_ip.prod[0].ip_address}:8082" : null
}
