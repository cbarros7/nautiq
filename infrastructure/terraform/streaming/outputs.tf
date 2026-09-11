# ==============================================================================
# Nautiq Streaming — Outputs (Azure)
# ==============================================================================

# DEV
output "dev_vm_public_ip" {
  description = "Dirección IP pública de la máquina de DEV"
  value       = azurerm_public_ip.dev.ip_address
}

output "dev_ssh_command" {
  description = "Comando para conectarse por SSH a la VM de DEV"
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.dev.ip_address}"
}

output "dev_flink_ui_url" {
  description = "URL del Dashboard de Flink en DEV"
  value       = "http://${azurerm_public_ip.dev.ip_address}:8081"
}

# PROD
output "prod_vm_public_ip" {
  description = "Dirección IP pública de la máquina de PROD"
  value       = azurerm_public_ip.prod.ip_address
}

output "prod_ssh_command" {
  description = "Comando para conectarse por SSH a la VM de PROD"
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.prod.ip_address}"
}

output "prod_flink_ui_url" {
  description = "URL del Dashboard de Flink en PROD (puerto 8082 si corre run_flink.sh --env prod)"
  value       = "http://${azurerm_public_ip.prod.ip_address}:8082"
}
