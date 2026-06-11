#!/bin/bash
# ============================================================
# Step 4: Create Event Hub and assign AIO managed identity role
# Run inside WSL2 / Linux, after AIO is deployed (script 03).
# ============================================================
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/config/variables.env"

az account set --subscription "$SUBSCRIPTION_ID"

echo "=== Creating Event Hub namespace: $EH_NAMESPACE ==="
az eventhubs namespace create \
  --name "$EH_NAMESPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --subscription "$SUBSCRIPTION_ID" \
  --sku Standard

echo "=== Creating Event Hub: $EH_CNC_NAME ==="
az eventhubs eventhub create \
  --name "$EH_CNC_NAME" \
  --namespace-name "$EH_NAMESPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --partition-count 2 \
  --cleanup-policy Delete \
  --retention-time-in-hours 24

echo "=== Retrieving AIO managed identity ==="
AIO_PRINCIPAL_ID=$(az k8s-extension list \
  --cluster-name "$CLUSTER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --cluster-type connectedClusters \
  --subscription "$SUBSCRIPTION_ID" \
  --query "[?extensionType=='microsoft.iotoperations'].identity.principalId | [0]" \
  -o tsv)

if [ -z "$AIO_PRINCIPAL_ID" ]; then
  echo "[ERROR] Could not retrieve AIO managed identity. Is AIO deployed?"
  exit 1
fi

EH_NAMESPACE_ID=$(az eventhubs namespace show \
  --name "$EH_NAMESPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --query id -o tsv)

echo "=== Assigning 'Azure Event Hubs Data Sender' to AIO identity ==="
az role assignment create \
  --assignee-object-id "$AIO_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure Event Hubs Data Sender" \
  --scope "$EH_NAMESPACE_ID" \
  --subscription "$SUBSCRIPTION_ID"

echo ""
echo "=== Retrieving connection string for Siemens IE CNC simulator ==="
EH_CONN_STR=$(az eventhubs namespace authorization-rule keys list \
  --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$EH_NAMESPACE" \
  --name RootManageSharedAccessKey \
  --subscription "$SUBSCRIPTION_ID" \
  --query primaryConnectionString -o tsv)

echo ""
echo "================================================================"
echo "Event Hub setup complete."
echo ""
echo "Namespace : $EH_NAMESPACE.servicebus.windows.net"
echo "Event Hub : $EH_CNC_NAME"
echo ""
echo "Use this connection string to run the Siemens IE CNC simulator:"
echo ""
echo "  export EH_CONNECTION_STRING='${EH_CONN_STR}'"
echo "  export EH_NAME='${EH_CNC_NAME}'"
echo "  python simulator/simulate_ie_cnc.py"
echo "================================================================"
