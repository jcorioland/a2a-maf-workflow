output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.apps.client_id
}

output "managed_identity_principal_id" {
  value = azurerm_user_assigned_identity.apps.principal_id
}

output "writer_fqdn" {
  value = try(azurerm_container_app.writer[0].ingress[0].fqdn, "")
}

output "reviewer_fqdn" {
  value = try(azurerm_container_app.reviewer[0].ingress[0].fqdn, "")
}
