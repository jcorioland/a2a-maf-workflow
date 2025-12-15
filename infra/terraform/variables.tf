variable "location" {
  type        = string
  description = "Azure region"
  default     = "eastus"
}

variable "name_prefix" {
  type        = string
  description = "Prefix used for resource naming"
  default     = "a2a-maf"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to resources"
  default     = {}
}

variable "create_foundry" {
  type        = bool
  description = "Whether to create a Microsoft Foundry (AIServices) account + Foundry project via AzAPI"
  default     = true
}

variable "foundry_account_name" {
  type        = string
  description = "Name of the Foundry (AIServices) account (Microsoft.CognitiveServices/accounts)"
  default     = null
}

variable "foundry_project_name" {
  type        = string
  description = "Name of the Foundry project (Microsoft.CognitiveServices/accounts/projects)"
  default     = null
}

variable "azure_ai_project_endpoint" {
  type        = string
  description = "Override for AZURE_AI_PROJECT_ENDPOINT. If set, Terraform will not try to derive it."
  default     = ""
}

variable "azure_ai_model_deployment_name" {
  type        = string
  description = "Value for AZURE_AI_MODEL_DEPLOYMENT_NAME (must already exist as a deployment in the Foundry account/project)"
}

variable "writer_image" {
  type        = string
  description = "Container image for the writer agent (e.g., <acr>.azurecr.io/writer:latest)"
}

variable "reviewer_image" {
  type        = string
  description = "Container image for the reviewer agent (e.g., <acr>.azurecr.io/reviewer:latest)"
}

variable "agent_timeout_seconds" {
  type        = number
  description = "Timeout for model calls"
  default     = 30
}

variable "foundry_scope_resource_id" {
  type        = string
  description = "If create_foundry=false, set this to the Resource ID of your existing Foundry (AIServices) account or project scope for RBAC."
  default     = ""
}

variable "foundry_role_definition_name" {
  type        = string
  description = "RBAC role assigned to the Container App identities on the Foundry scope."
  default     = "Cognitive Services User"
}
