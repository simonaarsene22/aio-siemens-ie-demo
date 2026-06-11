#!/bin/bash
# ============================================================
# Step 5: Apply Kubernetes manifests
# Substitutes EH_NAMESPACE into the dataflow endpoint manifest,
# then applies all AIO k8s resources.
# ============================================================
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/config/variables.env"

echo "=== Waiting for AIO dataflow webhook to be ready ==="
kubectl wait pod \
  --for=condition=Ready \
  -l app=aio-dataflow-webhook \
  -n azure-iot-operations \
  --timeout=120s

echo "=== Applying MQTT broker listener (port 1883) ==="
kubectl apply -f "$REPO_DIR/k8s/broker-listener-1883.yaml"

echo "=== Applying Event Hub dataflow endpoint ==="
sed "s/<EH_NAMESPACE>/$EH_NAMESPACE/g" \
  "$REPO_DIR/k8s/dataflow-endpoint-eh.yaml" \
  | kubectl apply -f -

echo ""
echo "=== Status ==="
kubectl get dataflowendpoint -n azure-iot-operations
kubectl get svc -n azure-iot-operations | grep -E "NAME|listener"
echo ""
echo "All manifests applied. Run script 06 to verify the full stack."
