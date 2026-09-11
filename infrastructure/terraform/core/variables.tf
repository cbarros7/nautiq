# Nautiq Core — Variables

variable "subscription_id_core" {
  description = "Azure Subscription ID for the core operational account"
  type        = string
}

variable "location" {
  description = "Azure region for all core resources"
  type        = string
  default     = "swedencentral"
}

variable "location_short" {
  description = "Short code for the Azure region (used in naming)"
  type        = string
  default     = "swc"
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
  default     = "dev"
}

variable "app_service_sku" {
  description = "SKU for the App Service Plan (F1 = Free, B1 = Basic)"
  type        = string
  default     = "B1"
}
