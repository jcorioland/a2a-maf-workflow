variable "project_name" {
  description = "Short, human-readable prefix used to name resources (e.g. 'a2amaf')."
  type        = string
}

variable "location" {
  description = "Azure region (e.g. 'westeurope')."
  type        = string
  default     = "westeurope"
}

variable "subscription_id" {
  description = "Optional Azure subscription id. If empty, Terraform will try to use your Azure CLI context (az login)."
  type        = string
  default     = ""
}

variable "tenant_id" {
  description = "Optional Azure Tenant id. If empty, Terraform will try to use your Azure CLI context (az login)."
  type        = string
  default     = ""
}


variable "tags" {
  description = "Tags applied to resources."
  type        = map(string)
  default     = {}
}

variable "writer_image" {
  description = "Writer image reference without registry server (e.g. 'writer:latest' or 'agents/writer:1.0.0')."
  type        = string
  default     = "writer:latest"
}

variable "reviewer_image" {
  description = "Reviewer image reference without registry server (e.g. 'reviewer:latest' or 'agents/reviewer:1.0.0')."
  type        = string
  default     = "reviewer:latest"
}

variable "writer_port" {
  description = "Writer container target port."
  type        = number
  default     = 8000
}

variable "reviewer_port" {
  description = "Reviewer container target port."
  type        = number
  default     = 8000
}

variable "container_cpu" {
  description = "CPU cores per container (e.g. 0.25, 0.5, 1.0)."
  type        = number
  default     = 0.5
}

variable "container_memory" {
  description = "Memory per container (e.g. '0.5Gi', '1Gi', '2Gi')."
  type        = string
  default     = "1Gi"
}

variable "writer_env" {
  description = "Environment variables for the writer app."
  type        = map(string)
  default     = {}
}

variable "reviewer_env" {
  description = "Environment variables for the reviewer app."
  type        = map(string)
  default     = {}
}

variable "writer_public_url" {
  description = "Optional public URL advertised by the writer agent card (e.g. 'https://<fqdn>'). If empty, A2A_PUBLIC_URL is not set."
  type        = string
  default     = ""
}

variable "reviewer_public_url" {
  description = "Optional public URL advertised by the reviewer agent card (e.g. 'https://<fqdn>'). If empty, A2A_PUBLIC_URL is not set."
  type        = string
  default     = ""
}

variable "create_container_apps" {
  description = "If false, only shared infra (ACR, Container Apps Environment, identity) is created."
  type        = bool
  default     = true
}

variable "expose_azure_client_id_env" {
  description = "If true, sets AZURE_CLIENT_ID in the containers to the user-assigned managed identity client id."
  type        = bool
  default     = true
}

variable "foundry_project_resource_id" {
  description = "Optional Azure resource id of the Azure AI Foundry Project to grant the managed identity developer permissions (Azure AI User role). If empty, no Foundry RBAC assignment is created."
  type        = string
  default     = ""
}
