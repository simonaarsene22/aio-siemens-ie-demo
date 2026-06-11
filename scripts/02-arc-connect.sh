#!/bin/bash
# ============================================================
# Step 2: Connect K3s cluster to Azure Arc
# Run inside WSL2 / Linux. Requires: az login completed.
# ============================================================
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/config/variables.env"

echo "=== Registering Azure resource providers ==="
for rp in \
  "Microsoft.ExtendedLocation" \
  "Microsoft.Kubernetes" \
  "Microsoft.KubernetesConfiguration" \
  "Microsoft.IoTOperations" \
  "Microsoft.DeviceRegistry" \
  "Microsoft.SecretSyncController" \
  "Microsoft.Storage" \
  "Microsoft.EventHub"; do
  echo "  Registering $rp ..."
  az provider register -n "$rp" --subscription "$SUBSCRIPTION_ID"
done
echo "Provider registration is async — if step 3 fails with 'provider not registered', wait 2 min and retry."

echo "=== Creating resource group: $RESOURCE_GROUP ==="
az group create \
  --location "$LOCATION" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID"

echo "=== Connecting cluster to Azure Arc ==="
az connectedk8s connect \
  --name "$CLUSTER_NAME" \
  --location "$LOCATION" \
  --resource-group "$RESOURCE_GROUP" \
  --subscription "$SUBSCRIPTION_ID" \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --disable-auto-upgrade

echo "=== Retrieving OIDC issuer URL ==="
OIDC_ISSUER=$(az connectedk8s show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CLUSTER_NAME" \
  --query oidcIssuerProfile.issuerUrl \
  --output tsv)
echo "OIDC Issuer: $OIDC_ISSUER"

echo "=== Updating K3s to use Arc OIDC issuer ==="
sudo tee /etc/rancher/k3s/config.yaml > /dev/null <<EOF
kube-apiserver-arg:
  - service-account-issuer=${OIDC_ISSUER}
  - service-account-max-token-expiration=24h
EOF

echo "=== Enabling custom-locations feature ==="
OBJECT_ID=$(az ad sp show \
  --id bc313c14-388c-4e7d-a58e-70017303ee3b \
  --query id -o tsv)
az connectedk8s enable-features \
  -n "$CLUSTER_NAME" \
  -g "$RESOURCE_GROUP" \
  --custom-locations-oid "$OBJECT_ID" \
  --features cluster-connect custom-locations

echo "=== Restarting K3s to apply OIDC config ==="
sudo systemctl restart k3s
sleep 15
kubectl get nodes

echo "=== Arc connection complete ==="
az connectedk8s show -n "$CLUSTER_NAME" -g "$RESOURCE_GROUP" --query connectivityStatus -o tsv
