locals {
  name_prefix = lower(replace(var.project_name, "_", "-"))
}

data "azuread_client_config" "current" {}

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

# Entra app registrations for Container Apps Authentication (Easy Auth)
resource "azuread_application_registration" "a2a_maf_auth" {
  count            = var.create_container_apps ? 1 : 0
  display_name     = "${local.name_prefix}-a2a-maf-auth"
  sign_in_audience = "AzureADMyOrg"

  # Required for Container Apps Easy Auth (OIDC sign-in).
  implicit_id_token_issuance_enabled     = true
  implicit_access_token_issuance_enabled = false
}

resource "azuread_service_principal" "a2a_maf_auth" {
  count     = var.create_container_apps ? 1 : 0
  client_id = azuread_application_registration.a2a_maf_auth[0].client_id

  # Not strictly required for Easy Auth, but keeps the enterprise app present.
  app_role_assignment_required = false
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

resource "azapi_resource" "writer_auth_config" {
  count     = var.create_container_apps ? 1 : 0
  type      = "Microsoft.App/containerApps/authConfigs@2025-07-01"
  name      = "current"
  parent_id = azurerm_container_app.writer[0].id

  body = {
    properties = {
      platform = {
        enabled = true
      }

      httpSettings = {
        requireHttps = true
      }

      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureActiveDirectory"

        # Keep the existing infra health checks working.
        excludedPaths = ["/healthz"]
      }

      identityProviders = {
        azureActiveDirectory = {
          enabled = true

          registration = {
            clientId     = azuread_application_registration.a2a_maf_auth[0].client_id
            openIdIssuer = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
          }
        }
      }
    }
  }
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

resource "azapi_resource" "reviewer_auth_config" {
  count     = var.create_container_apps ? 1 : 0
  type      = "Microsoft.App/containerApps/authConfigs@2025-07-01"
  name      = "current"
  parent_id = azurerm_container_app.reviewer[0].id

  body = {
    properties = {
      platform = {
        enabled = true
      }

      httpSettings = {
        requireHttps = true
      }

      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureActiveDirectory"
        excludedPaths               = ["/healthz"]
      }

      identityProviders = {
        azureActiveDirectory = {
          enabled = true

          registration = {
            clientId     = azuread_application_registration.a2a_maf_auth[0].client_id
            openIdIssuer = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
          }
        }
      }
    }
  }
}

resource "azuread_application_redirect_uris" "a2a_maf_auth" {
  count          = var.create_container_apps ? 1 : 0
  application_id = azuread_application_registration.a2a_maf_auth[0].id
  type           = "Web"

  redirect_uris = [
    "https://${azurerm_container_app.writer[0].ingress[0].fqdn}/.auth/login/aad/callback",
    "https://${azurerm_container_app.reviewer[0].ingress[0].fqdn}/.auth/login/aad/callback",
  ]
}
