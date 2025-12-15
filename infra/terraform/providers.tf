provider "azurerm" {
  features {}
}

provider "azapi" {
  # Keep provider registration enabled; Foundry resource types may need it.
  skip_provider_registration = false
}
