# ==============================================================================
# Nautiq Streaming — Variables (Azure)
# ==============================================================================

variable "subscription_id" {
  description = "ID de Suscripción de Azure donde se desplegarán las VMs de Streaming"
  type        = string
}

variable "location" {
  description = "Región de Azure (mismo datacenter que el Data Lake para evitar costes de transferencia)"
  type        = string
  default     = "swedencentral"
}

variable "location_short" {
  description = "Código corto de la región de Azure (ej. swc)"
  type        = string
  default     = "swc"
}

variable "admin_username" {
  description = "Usuario administrador de las máquinas virtuales Linux"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Ruta local a tu clave pública SSH para conectarte a las VMs"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "allowed_ssh_cidr" {
  description = "Rango CIDR con permiso para conectarse por SSH (puerto 22). Recomendado: tu IP pública x.x.x.x/32"
  type        = string
  default     = "0.0.0.0/0"
}

variable "allowed_ui_cidr" {
  description = "Rango CIDR con permiso para acceder al Dashboard de Flink (8081/8082). Recomendado: tu IP pública x.x.x.x/32"
  type        = string
  default     = "0.0.0.0/0"
}

variable "allowed_metrics_cidr" {
  description = "Rango CIDR con permiso para raspar métricas Prometheus (9249-9252). Recomendado: IP de Grafana/Prometheus scraper"
  type        = string
  default     = "0.0.0.0/0"
}

# Configuración de Tamaños de VM
variable "vm_size_prod" {
  description = "Tamaño de la VM para PROD (Recomendado: Standard_D2s_v5 con 2 vCPUs y 8 GB RAM, o Standard_D4s_v5 con 16 GB)"
  type        = string
  default     = "Standard_D2s_v5"
}

variable "vm_size_dev" {
  description = "Tamaño de la VM para DEV (Recomendado: Standard_D2s_v5 con 2 vCPUs y 8 GB RAM)"
  type        = string
  default     = "Standard_D2s_v5"
}

# Opciones de Descuento Spot
variable "spot_prod" {
  description = "Si es true, la VM de PROD se desplegará con precio Spot (~80% descuento). Requerido en Azure for Students porque la cuota regular es 0"
  type        = bool
  default     = true
}

variable "spot_dev" {
  description = "Si es true, la VM de DEV se desplegará con precio Spot (~80% descuento)"
  type        = bool
  default     = true
}

variable "git_repo_url" {
  description = "URL HTTPS del repositorio Git para clonar automáticamente en el arranque (dejar vacío si se clonará manualmente)"
  type        = string
  default     = ""
}

# Control de Entornos (Importante para Azure for Students con cuota de 1 VM activa/región)
variable "enable_dev" {
  description = "Habilitar el despliegue del entorno DEV (por defecto false si solo desplegamos PROD en Azure for Students)"
  type        = bool
  default     = false
}

variable "enable_prod" {
  description = "Habilitar el despliegue del entorno PROD"
  type        = bool
  default     = true
}
