# Azure Container Apps Infra (writer + reviewer)

This folder contains Terraform to deploy:

- 1x Azure Container Registry (ACR)
- 1x Azure Container Apps Environment
- 2x Azure Container Apps (writer, reviewer)
- 1x User-assigned Managed Identity used by both apps
- RBAC: the managed identity gets `AcrPull` on the ACR so Container Apps can pull images

No Application Insights / Foundry resources are created here. The apps rely on existing resources via environment variables.

## Prereqs

- Azure subscription + `az login`
- Ensure a default subscription is selected (`az account set -s <subscriptionId>`) or set `ARM_SUBSCRIPTION_ID`
- Terraform installed
- Docker installed (to build/push images)

## Configure

Create `infra/terraform.tfvars`:

```hcl
project_name = "a2amaf"
location     = "westeurope"

# Optional: if your Azure CLI context has no default subscription
# subscription_id = "<subscription-guid>"

# Images are referenced as: <acrLoginServer>/<value>
writer_image   = "writer:latest"
reviewer_image = "reviewer:latest"

# Pass through runtime config to the containers
writer_env = {
  AZURE_AI_PROJECT_ENDPOINT       = "https://<aiservices-id>.services.ai.azure.com/api/projects/<project-name>"
  AZURE_AI_MODEL_DEPLOYMENT_NAME  = "<your-model-deployment-name>"
  # Optional telemetry
  # APPLICATIONINSIGHTS_CONNECTION_STRING = "<connection-string>"
}

reviewer_env = {
  AZURE_AI_PROJECT_ENDPOINT       = "https://<aiservices-id>.services.ai.azure.com/api/projects/<project-name>"
  AZURE_AI_MODEL_DEPLOYMENT_NAME  = "<your-model-deployment-name>"
  # APPLICATIONINSIGHTS_CONNECTION_STRING = "<connection-string>"
}

# Optional: advertise public URL in the A2A agent card
# You can set these after the first apply once you know the FQDNs.
# writer_public_url   = "https://<writer_fqdn>"
# reviewer_public_url = "https://<reviewer_fqdn>"

# By default, the deployment sets AZURE_CLIENT_ID in the containers so SDKs can
# explicitly target the user-assigned managed identity. Set this to false to opt out.
# expose_azure_client_id_env = false
```

## Deploy

From repo root:

```bash
./scripts/deploy-infra.sh
```

Then build + push images and create/update the Container Apps:

```bash
./scripts/deploy-agents.sh
```

After `apply`, Terraform outputs include:

- `acr_login_server`
- `writer_fqdn` / `reviewer_fqdn`
- `managed_identity_principal_id` / `managed_identity_client_id`

If you want to set `A2A_PUBLIC_URL` manually, populate `writer_public_url` / `reviewer_public_url` in `infra/terraform.tfvars` using the output FQDNs and re-run `./scripts/deploy-agents.sh`.

If you use `./scripts/deploy-agents.sh`, it will also set `writer_public_url` / `reviewer_public_url` automatically after the apps are created.

## Managed identity access to existing resources (Foundry + App Insights)

This deployment creates one user-assigned managed identity and assigns it to both Container Apps.

### Azure AI Foundry / model access

If your code uses Entra ID auth (recommended), grant the identity the appropriate RBAC role on the target Azure AI resource/project (role names depend on the resource type).

If you see an error like:

> The principal ... lacks the required data action `Microsoft.CognitiveServices/accounts/AIServices/agents/write` to perform `POST /api/projects/{projectName}/assistants`

Then the identity needs a Foundry *developer* role on the **Foundry Project** scope. The built-in role typically used for least privilege is:

- Role: `Azure AI User` (grants the project data actions needed to create/update agents)

You can grant this automatically via Terraform by setting:

```hcl
foundry_project_resource_id = "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>"
```

A common case for Azure OpenAI-compatible *model* inference (chat/completions) is still:

- Role: `Cognitive Services OpenAI User`

Example (you provide the right scope):

```bash
PRINCIPAL_ID="$(terraform -chdir=infra output -raw managed_identity_principal_id)"
# SCOPE should be the Azure resource id of your AI resource / project
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Cognitive Services OpenAI User" --scope "$SCOPE"
```

By default, this module sets `AZURE_CLIENT_ID` in the containers to the managed identity client id. If you want to opt out, set `expose_azure_client_id_env = false`.

### Application Insights

For ingestion/telemetry, the standard approach is to set `APPLICATIONINSIGHTS_CONNECTION_STRING` (no managed identity needed).

If you need the apps to *query* telemetry (rare for service runtime), grant an Azure Monitor/App Insights read role to the managed identity (for example `Monitoring Reader`) at the appropriate scope.
