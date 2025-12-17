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

cd "$INFRA_DIR"

terraform init

TFVARS_FILE="${TFVARS_FILE:-$INFRA_DIR/terraform.tfvars}"
VAR_FILE_ARGS=()
if [[ -f "$TFVARS_FILE" ]]; then
  VAR_FILE_ARGS+=("-var-file=$TFVARS_FILE")
fi

terraform plan "${VAR_FILE_ARGS[@]}" -var="create_container_apps=false" -out=tfplan
terraform apply tfplan
