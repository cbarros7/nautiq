# ==============================================================================
# Nautiq Streaming — Network Security Groups (Firewall Azure DEV y PROD)
# ==============================================================================
# Se configuran NSGs separados por entorno y asociados a cada NIC para permitir
# políticas de acceso independientes y evitar reglas globales compartidas.

# ------------------------------------------------------------------------------
# 1. NSG para DEV
# ------------------------------------------------------------------------------
resource "azurerm_network_security_group" "dev" {
  name                = "nsg-nautiq-streaming-dev-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location

  # 1. SSH (Puerto 22)
  security_rule {
    name                       = "Allow-SSH"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.allowed_ssh_cidr
    destination_address_prefix = "*"
  }

  # 2. Flink Web UI DEV (Puerto 8081)
  security_rule {
    name                       = "Allow-Flink-UI-DEV"
    priority                   = 1010
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8081"
    source_address_prefix      = var.allowed_ui_cidr
    destination_address_prefix = "*"
  }

  # 3. Métricas Prometheus DEV (Puertos 9251 y 9252)
  security_rule {
    name                       = "Allow-Prometheus-DEV"
    priority                   = 1020
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["9251", "9252"]
    source_address_prefix      = var.allowed_metrics_cidr
    destination_address_prefix = "*"
  }

  tags = merge(local.common_tags, { environment = "dev" })
}

# Asociar NSG a la NIC de DEV
resource "azurerm_network_interface_security_group_association" "dev" {
  network_interface_id      = azurerm_network_interface.dev.id
  network_security_group_id = azurerm_network_security_group.dev.id
}

# ------------------------------------------------------------------------------
# 2. NSG para PROD
# ------------------------------------------------------------------------------
resource "azurerm_network_security_group" "prod" {
  name                = "nsg-nautiq-streaming-prod-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location

  # 1. SSH (Puerto 22)
  security_rule {
    name                       = "Allow-SSH"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.allowed_ssh_cidr
    destination_address_prefix = "*"
  }

  # 2. Flink Web UI PROD (Puerto 8082)
  security_rule {
    name                       = "Allow-Flink-UI-PROD"
    priority                   = 1010
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8082"
    source_address_prefix      = var.allowed_ui_cidr
    destination_address_prefix = "*"
  }

  # 3. Métricas Prometheus PROD (Puertos 9249 y 9250)
  security_rule {
    name                       = "Allow-Prometheus-PROD"
    priority                   = 1020
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["9249", "9250"]
    source_address_prefix      = var.allowed_metrics_cidr
    destination_address_prefix = "*"
  }

  tags = merge(local.common_tags, { environment = "prod" })
}

# Asociar NSG a la NIC de PROD
resource "azurerm_network_interface_security_group_association" "prod" {
  network_interface_id      = azurerm_network_interface.prod.id
  network_security_group_id = azurerm_network_security_group.prod.id
}
