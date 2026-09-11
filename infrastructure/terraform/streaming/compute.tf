# ==============================================================================
# Nautiq Streaming — Compute (Azure Linux Virtual Machines para DEV y PROD)
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. ENTORNO DEV (Opcional, condicionado por var.enable_dev)
# ------------------------------------------------------------------------------

# IP Pública para DEV
resource "azurerm_public_ip" "dev" {
  count               = var.enable_dev ? 1 : 0
  name                = "pip-nautiq-flink-dev-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = merge(local.common_tags, { environment = "dev" })
}

# Interfaz de Red para DEV
resource "azurerm_network_interface" "dev" {
  count               = var.enable_dev ? 1 : 0
  name                = "nic-nautiq-flink-dev-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.streaming.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.dev[0].id
  }

  tags = merge(local.common_tags, { environment = "dev" })
}

# Máquina Virtual DEV
resource "azurerm_linux_virtual_machine" "dev" {
  count               = var.enable_dev ? 1 : 0
  name                = "vm-nautiq-flink-dev"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location
  size                = var.vm_size_dev
  admin_username      = var.admin_username

  network_interface_ids = [azurerm_network_interface.dev[0].id]

  # Configuración Spot opcional para DEV (~80% de ahorro)
  priority        = var.spot_dev ? "Spot" : "Regular"
  eviction_policy = var.spot_dev ? "Deallocate" : null
  max_bid_price   = var.spot_dev ? -1 : null

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  # Inyección de dependencias, swap, scripts y certificados secretos de DEV vía cloud-init
  custom_data = base64encode(templatefile("${path.module}/cloud-init.tftpl", {
    admin_username      = var.admin_username
    git_repo_url        = var.git_repo_url
    ca_pem_b64          = filebase64("${path.root}/../../../.certs/ca.pem")
    service_cert_b64    = filebase64("${path.root}/../../../.certs/service.cert")
    service_key_b64     = filebase64("${path.root}/../../../.certs/service.key")
    azure_cert_filename = "azure_function_cert.pem"
    azure_cert_b64      = filebase64("${path.root}/../../../streaming/src/azure_function_cert.pem")
    env_filename        = ".env.dev"
    env_file_b64        = filebase64("${path.root}/../../../.env.dev")
    run_flink_b64       = filebase64("${path.root}/../../../run_flink.sh")
    target_env          = "dev"
  }))

  tags = merge(local.common_tags, { environment = "dev" })
}

# ------------------------------------------------------------------------------
# 2. ENTORNO PROD (Opcional, condicionado por var.enable_prod)
# ------------------------------------------------------------------------------

# IP Pública para PROD
resource "azurerm_public_ip" "prod" {
  count               = var.enable_prod ? 1 : 0
  name                = "pip-nautiq-flink-prod-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = merge(local.common_tags, { environment = "prod" })
}

# Interfaz de Red para PROD
resource "azurerm_network_interface" "prod" {
  count               = var.enable_prod ? 1 : 0
  name                = "nic-nautiq-flink-prod-${var.location_short}"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.streaming.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.prod[0].id
  }

  tags = merge(local.common_tags, { environment = "prod" })
}

# Máquina Virtual PROD
resource "azurerm_linux_virtual_machine" "prod" {
  count               = var.enable_prod ? 1 : 0
  name                = "vm-nautiq-flink-prod"
  resource_group_name = azurerm_resource_group.streaming.name
  location            = azurerm_resource_group.streaming.location
  size                = var.vm_size_prod
  admin_username      = var.admin_username

  network_interface_ids = [azurerm_network_interface.prod[0].id]

  # Configuración Spot (false por defecto en PROD para 100% SLA continuo)
  priority        = var.spot_prod ? "Spot" : "Regular"
  eviction_policy = var.spot_prod ? "Deallocate" : null
  max_bid_price   = var.spot_prod ? -1 : null

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  # Inyección de dependencias, swap, scripts y certificados secretos de PROD vía cloud-init
  custom_data = base64encode(templatefile("${path.module}/cloud-init.tftpl", {
    admin_username      = var.admin_username
    git_repo_url        = var.git_repo_url
    ca_pem_b64          = filebase64("${path.root}/../../../.certs/ca.pem")
    service_cert_b64    = filebase64("${path.root}/../../../.certs/service.cert")
    service_key_b64     = filebase64("${path.root}/../../../.certs/service.key")
    azure_cert_filename = "azure_function_cert_prod.pem"
    azure_cert_b64      = filebase64("${path.root}/../../../streaming/src/azure_function_cert_prod.pem")
    env_filename        = ".env.prod"
    env_file_b64        = filebase64("${path.root}/../../../.env.prod")
    run_flink_b64       = filebase64("${path.root}/../../../run_flink.sh")
    target_env          = "prod"
  }))

  tags = merge(local.common_tags, { environment = "prod" })
}
