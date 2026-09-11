# ==============================================================================
# Nautiq Streaming — Network Security Group (Firewall Azure)
# ==============================================================================

resource "azurerm_network_security_group" "streaming" {
  name                = "nsg-nautiq-streaming-${var.location_short}"
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

  # 2. Flink Web UI (Puertos 8081 y 8082)
  security_rule {
    name                       = "Allow-Flink-UI"
    priority                   = 1010
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["8081", "8082"]
    source_address_prefix      = var.allowed_ssh_cidr
    destination_address_prefix = "*"
  }

  # 3. Métricas Prometheus (Puertos 9249 a 9252)
  security_rule {
    name                       = "Allow-Prometheus-Metrics"
    priority                   = 1020
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["9249", "9250", "9251", "9252"]
    source_address_prefix      = var.allowed_ssh_cidr
    destination_address_prefix = "*"
  }

  tags = local.common_tags
}

# Asociar NSG a la Subnet de Streaming
resource "azurerm_subnet_network_security_group_association" "streaming" {
  subnet_id                 = azurerm_subnet.streaming.id
  network_security_group_id = azurerm_network_security_group.streaming.id
}
