# Nautiq Core — Terraform Main Configuration
# Cuenta Azure 1: Operativa y Data Lake
# Recursos: ADLS Gen2, Key Vault, ACR, App Service (FastAPI)

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
    key                  = "core.terraform.tfstate"
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }

  subscription_id = var.subscription_id_core
}

# Resource Group
resource "azurerm_resource_group" "core" {
  name     = "rg-nautiq-core-${var.environment}-${var.location_short}"
  location = var.location

  tags = local.common_tags
}

# Locals
locals {
  common_tags = {
    project     = "nautiq"
    environment = var.environment
    managed_by  = "terraform"
    team        = "nautiq-tfm"
  }
}
