# Terraform (Azure Container Apps + AI Foundry)

This provisions:

- Resource group
- Log Analytics Workspace
- Application Insights
- Container Apps Environment
- Two Container Apps (writer + reviewer), each exposing `POST /invoke`
- (Optional) Microsoft Foundry (AIServices) account + Foundry project via AzAPI

## Variables

Required:

- `azure_ai_model_deployment_name`
- `writer_image`
- `reviewer_image`

Optional:

- `azure_ai_project_endpoint` (if you prefer to paste the exact endpoint from Foundry)

## Apply

From this folder:

- `terraform init`
- `terraform apply`

## Notes

- The Foundry project endpoint is best provided explicitly (from the Foundry portal) via `azure_ai_project_endpoint`.
  If you omit it, Terraform derives a best-effort endpoint based on naming.
- Ensure your model deployment exists and the container app identities have permission to call it.
