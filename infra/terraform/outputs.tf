output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.ai.connection_string
  sensitive = true
}

output "azure_ai_project_endpoint" {
  value = local.azure_ai_project_endpoint
}

output "writer_invoke_url" {
  value = "https://${azurerm_container_app.writer.ingress[0].fqdn}/invoke"
}

output "reviewer_invoke_url" {
  value = "https://${azurerm_container_app.reviewer.ingress[0].fqdn}/invoke"
}
