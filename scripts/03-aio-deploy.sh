#!/bin/bash
# ============================================================
# Step 3: Deploy Azure IoT Operations
# Takes 10-15 minutes. Run inside WSL2 / Linux.
# ============================================================
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/config/variables.env"

az account set --subscription "$SUBSCRIPTION_ID"

echo "=== Installing/upgrading azure-iot-ops CLI extension ==="
az extension add --upgrade --name azure-iot-ops

echo "=== Creating storage account: $STORAGE_ACCOUNT ==="
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --location "$LOCATION" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --enable-hierarchical-namespace

echo "=== Creating schema registry: $SCHEMA_REGISTRY ==="
STORAGE_ID=$(az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  -o tsv --query id)
az iot ops schema registry create \
  --name "$SCHEMA_REGISTRY" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --registry-namespace "$SCHEMA_REGISTRY_NAMESPACE" \
  --sa-resource-id "$STORAGE_ID"

echo "=== Creating Azure Device Registry namespace: $ADR_NAMESPACE ==="
az iot ops ns create \
  -n "$ADR_NAMESPACE" \
  -g "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID"

echo "=== Collecting resource IDs ==="
SR_RESOURCE_ID=$(az iot ops schema registry show \
  --name "$SCHEMA_REGISTRY" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  -o tsv --query id)
NS_RESOURCE_ID=$(az iot ops ns show \
  --name "$ADR_NAMESPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  -o tsv --query id)

echo "=== Step 1/2: az iot ops init (prepare cluster) ==="
az iot ops init \
  --cluster "$CLUSTER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --no-preflight

echo "=== Step 2/2: az iot ops create (deploy AIO instance) ==="
az iot ops create \
  --cluster "$CLUSTER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --name "$AIO_INSTANCE_NAME" \
  --sr-resource-id "$SR_RESOURCE_ID" \
  --ns-resource-id "$NS_RESOURCE_ID" \
  --broker-frontend-replicas 1 \
  --broker-frontend-workers 1 \
  --broker-backend-part 1 \
  --broker-backend-workers 1 \
  --broker-backend-rf 2 \
  --broker-mem-profile Low \
  --no-preflight

echo "=== AIO deployment complete ==="
az iot ops check
