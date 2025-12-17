locals {
  name_prefix = lower(replace(var.project_name, "_", "-"))
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "law" {
  name                = "${local.name_prefix}-law-${random_string.suffix.result}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_container_registry" "acr" {
  name                = substr(replace("${local.name_prefix}${random_string.suffix.result}", "-", ""), 0, 50)
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location

  sku           = "Standard"
  admin_enabled = false

  tags = var.tags
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "${local.name_prefix}-apps-mi"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_role_assignment" "foundry_project_ai_user" {
  count                = var.foundry_project_resource_id != "" ? 1 : 0
  scope                = var.foundry_project_resource_id
  role_definition_name = "Azure AI User"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_container_app_environment" "cae" {
  name                       = "${local.name_prefix}-cae"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id

  tags = var.tags
}

resource "azurerm_container_app" "writer" {
  count                        = var.create_container_apps ? 1 : 0
  name                         = "${local.name_prefix}-writer"
  container_app_environment_id = azurerm_container_app_environment.cae.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = true
    target_port      = var.writer_port

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    container {
      name   = "writer"
      image  = "${azurerm_container_registry.acr.login_server}/${var.writer_image}"
      cpu    = var.container_cpu
      memory = var.container_memory

      dynamic "env" {
        for_each = var.writer_public_url != "" ? { A2A_PUBLIC_URL = var.writer_public_url } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.expose_azure_client_id_env ? { AZURE_CLIENT_ID = azurerm_user_assigned_identity.apps.client_id } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.writer_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]

  tags = var.tags
}

resource "azurerm_container_app" "reviewer" {
  count                        = var.create_container_apps ? 1 : 0
  name                         = "${local.name_prefix}-reviewer"
  container_app_environment_id = azurerm_container_app_environment.cae.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = true
    target_port      = var.reviewer_port

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    container {
      name   = "reviewer"
      image  = "${azurerm_container_registry.acr.login_server}/${var.reviewer_image}"
      cpu    = var.container_cpu
      memory = var.container_memory

      dynamic "env" {
        for_each = var.reviewer_public_url != "" ? { A2A_PUBLIC_URL = var.reviewer_public_url } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.expose_azure_client_id_env ? { AZURE_CLIENT_ID = azurerm_user_assigned_identity.apps.client_id } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.reviewer_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]

  tags = var.tags
}
