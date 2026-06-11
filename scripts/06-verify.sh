#!/bin/bash
# ============================================================
# Step 6: Verify the full stack
# ============================================================
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/config/variables.env"

echo "=== AIO health check ==="
az iot ops check

echo ""
echo "=== MQTT Broker pods ==="
kubectl get pods -n azure-iot-operations | grep -E "NAME|broker"

echo ""
echo "=== BrokerListener (port 1883) ==="
kubectl get svc -n azure-iot-operations | grep -E "NAME|listener"

echo ""
echo "=== DataflowEndpoint ==="
kubectl get dataflowendpoint -n azure-iot-operations

echo ""
echo "=== Arc connectivity ==="
az connectedk8s show \
  -n "$CLUSTER_NAME" \
  -g "$RESOURCE_GROUP" \
  --query "{name:name, status:connectivityStatus}" -o table

echo ""
echo "================================================================"
echo "Stack verified. Next: run the Siemens IE CNC simulator."
echo "See docs/getting-started.md for the end-to-end walkthrough."
echo "================================================================"
