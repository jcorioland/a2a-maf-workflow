locals {
  suffix = substr(random_id.suffix.hex, 0, 6)

  rg_name  = "${var.name_prefix}-rg-${local.suffix}"
  law_name = "${var.name_prefix}-law-${local.suffix}"
  ai_name  = "${var.name_prefix}-ai-${local.suffix}"
  cae_name = "${var.name_prefix}-cae-${local.suffix}"

  foundry_account_name = coalesce(var.foundry_account_name, "${var.name_prefix}ai${local.suffix}")
  foundry_project_name = coalesce(var.foundry_project_name, "${var.name_prefix}-proj-${local.suffix}")

  # Best-effort derived endpoint if you don't provide one explicitly.
  # The Azure AI Agents SDK expects an endpoint shaped like:
  #   https://<aiservices-id>.services.ai.azure.com/api/projects/<project-name>
  derived_project_endpoint = "https://${local.foundry_account_name}.services.ai.azure.com/api/projects/${local.foundry_project_name}"

  azure_ai_project_endpoint = trimspace(var.azure_ai_project_endpoint) != "" ? var.azure_ai_project_endpoint : local.derived_project_endpoint

  foundry_scope_id = var.create_foundry ? try(azapi_resource.foundry_account[0].id, "") : trimspace(var.foundry_scope_resource_id)
}

resource "random_id" "suffix" {
  byte_length = 8
}

resource "azurerm_resource_group" "rg" {
  name     = local.rg_name
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "law" {
  name                = local.law_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_application_insights" "ai" {
  name                = local.ai_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.law.id
  tags                = var.tags
}

resource "azurerm_container_app_environment" "cae" {
  name                       = local.cae_name
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = var.tags
}

# --- Microsoft Foundry account + project (AzAPI) ---

resource "azapi_resource" "foundry_account" {
  count     = var.create_foundry ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  parent_id = azurerm_resource_group.rg.id
  name      = local.foundry_account_name
  location  = azurerm_resource_group.rg.location

  identity {
    type = "SystemAssigned"
  }

  body = {
    kind = "AIServices"
    properties = {
      allowProjectManagement        = true
      customSubDomainName           = "cog-${local.foundry_account_name}"
      disableLocalAuth              = false
      dynamicThrottlingEnabled      = false
      publicNetworkAccess           = "Enabled"
      restrictOutboundNetworkAccess = false
    }
    sku = {
      name = "S0"
    }
  }

  schema_validation_enabled = false
  response_export_values    = ["*"]
  tags                      = var.tags
}

resource "azapi_resource" "foundry_project" {
  count     = var.create_foundry ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  parent_id = azapi_resource.foundry_account[0].id
  name      = local.foundry_project_name
  location  = azurerm_resource_group.rg.location

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      displayName = local.foundry_project_name
      description = "Foundry project for ACA agents"
    }
  }

  schema_validation_enabled = false
  response_export_values    = ["*"]
  tags                      = var.tags
}

# --- Container Apps (two independent services) ---

resource "azurerm_container_app" "writer" {
  name                         = "${var.name_prefix}-writer-${local.suffix}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    container {
      name   = "writer"
      image  = var.writer_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "SERVICE_NAME"
        value = "writer-agent"
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.ai.connection_string
      }

      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = local.azure_ai_project_endpoint
      }

      env {
        name  = "AZURE_AI_MODEL_DEPLOYMENT_NAME"
        value = var.azure_ai_model_deployment_name
      }

      env {
        name  = "AGENT_TIMEOUT_SECONDS"
        value = tostring(var.agent_timeout_seconds)
      }
    }
  }
}

resource "azurerm_container_app" "reviewer" {
  name                         = "${var.name_prefix}-reviewer-${local.suffix}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.cae.id
  revision_mode                = "Single"

  identity {
    type = "SystemAssigned"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    container {
      name   = "reviewer"
      image  = var.reviewer_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "SERVICE_NAME"
        value = "reviewer-agent"
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.ai.connection_string
      }

      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = local.azure_ai_project_endpoint
      }

      env {
        name  = "AZURE_AI_MODEL_DEPLOYMENT_NAME"
        value = var.azure_ai_model_deployment_name
      }

      env {
        name  = "AGENT_TIMEOUT_SECONDS"
        value = tostring(var.agent_timeout_seconds)
      }
    }
  }
}

resource "azurerm_role_assignment" "writer_foundry_user" {
  count                = local.foundry_scope_id != "" ? 1 : 0
  scope                = local.foundry_scope_id
  role_definition_name = var.foundry_role_definition_name
  principal_id         = azurerm_container_app.writer.identity[0].principal_id
}

resource "azurerm_role_assignment" "reviewer_foundry_user" {
  count                = local.foundry_scope_id != "" ? 1 : 0
  scope                = local.foundry_scope_id
  role_definition_name = var.foundry_role_definition_name
  principal_id         = azurerm_container_app.reviewer.identity[0].principal_id
}
