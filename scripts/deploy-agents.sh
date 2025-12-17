#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infra"

if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: Azure CLI (az) not found. Install it or run from an environment that has it." >&2
  exit 1
fi

# azurerm provider needs a subscription id. If not explicitly provided, use Azure CLI context.
if [[ -z "${ARM_SUBSCRIPTION_ID:-}" ]]; then
  if ! ARM_SUBSCRIPTION_ID="$(az account show --query id -o tsv 2>/dev/null)"; then
    echo "ERROR: Not logged into Azure. Run 'az login' (and optionally 'az account set -s <subscriptionId>')." >&2
    exit 1
  fi
  export ARM_SUBSCRIPTION_ID
fi

cd "$ROOT_DIR"

TFVARS_FILE="${TFVARS_FILE:-$INFRA_DIR/terraform.tfvars}"

read_tfvar_string() {
  local key="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    return 1
  fi

  # Extract values from lines like: key = "value" (ignores inline comments)
  local line
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | head -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi

  echo "$line" | sed -E 's/#.*$//; s/^[[:space:]]*[^=]+=[[:space:]]*"([^"]+)"[[:space:]]*$/\1/'
}

cd "$INFRA_DIR"
terraform init

# Ensure infra exists (ACR output must be readable)
if ! ACR_LOGIN_SERVER="$(terraform output -raw acr_login_server 2>/dev/null)"; then
  echo "ERROR: Terraform outputs not available. Run ./scripts/deploy-infra.sh first." >&2
  exit 1
fi
ACR_NAME="$(terraform output -raw acr_name)"

WRITER_IMAGE_REF="$(read_tfvar_string writer_image "$TFVARS_FILE" || true)"
REVIEWER_IMAGE_REF="$(read_tfvar_string reviewer_image "$TFVARS_FILE" || true)"
WRITER_IMAGE_REF="${WRITER_IMAGE_REF:-writer:latest}"
REVIEWER_IMAGE_REF="${REVIEWER_IMAGE_REF:-reviewer:latest}"

cd "$ROOT_DIR"

echo "Logging into ACR: $ACR_NAME"
az acr login --name "$ACR_NAME"

echo "Building images..."
docker build -t "$ACR_LOGIN_SERVER/$WRITER_IMAGE_REF" -f src/agents/writer/Dockerfile .
docker build -t "$ACR_LOGIN_SERVER/$REVIEWER_IMAGE_REF" -f src/agents/reviewer/Dockerfile .

echo "Pushing images..."
docker push "$ACR_LOGIN_SERVER/$WRITER_IMAGE_REF"
docker push "$ACR_LOGIN_SERVER/$REVIEWER_IMAGE_REF"

cd "$INFRA_DIR"

VAR_FILE_ARGS=()
if [[ -f "$TFVARS_FILE" ]]; then
  VAR_FILE_ARGS+=("-var-file=$TFVARS_FILE")
fi

# Phase 1: create/update Container Apps referencing the pushed images
terraform plan "${VAR_FILE_ARGS[@]}" -var="create_container_apps=true" -out=tfplan
terraform apply tfplan

# Phase 2: set A2A_PUBLIC_URL automatically using the allocated FQDNs (optional)
WRITER_FQDN="$(terraform output -raw writer_fqdn)"
REVIEWER_FQDN="$(terraform output -raw reviewer_fqdn)"

if [[ -n "$WRITER_FQDN" && -n "$REVIEWER_FQDN" ]]; then
  terraform plan "${VAR_FILE_ARGS[@]}" \
    -var="create_container_apps=true" \
    -var="writer_public_url=https://$WRITER_FQDN" \
    -var="reviewer_public_url=https://$REVIEWER_FQDN" \
    -out=tfplan
  terraform apply tfplan
fi

echo "Writer URL:   https://$WRITER_FQDN"
echo "Reviewer URL: https://$REVIEWER_FQDN"
