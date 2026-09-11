# ==============================================================================
# Nautiq Streaming — Terraform Main Configuration (Azure)
# Despliegue desacoplado de clústeres Apache Flink para DEV y PROD
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-nautiq-tfstate-swc"
    storage_account_name = "stnautiqtfstate"
    container_name       = "tfstate"
    key                  = "streaming.terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Resource Group dedicado para streaming
resource "azurerm_resource_group" "streaming" {
  name     = "rg-nautiq-streaming-${var.location_short}"
  location = var.location

  tags = local.common_tags
}

# Red Virtual (VNet) y Subnet para ambos entornos
resource "azurerm_virtual_network" "streaming" {
  name                = "vnet-nautiq-streaming-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location
  address_space       = ["10.10.0.0/16"]

  tags = local.common_tags
}

resource "azurerm_subnet" "streaming" {
  name                 = "snet-nautiq-streaming-${var.location_short}"
  resource_group_name  = azurerm_resource_group.streaming.name
  virtual_network_name = azurerm_virtual_network.streaming.name
  address_prefixes     = ["10.10.1.0/24"]
}

locals {
  common_tags = {
    project    = "nautiq"
    managed_by = "terraform"
    tier       = "streaming"
    team       = "nautiq-tfm"
  }
}
