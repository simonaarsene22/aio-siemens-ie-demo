# Azure IoT Operations + Siemens IE + Microsoft Fabric — End-to-End Demo

A complete reference implementation connecting a **Siemens Industrial Edge CNC simulator** to a **Microsoft Fabric Real-Time Intelligence dashboard** via **Azure IoT Operations (AIO)**.

## Architecture

```
┌──────────────────────────────────────┐
│  Siemens IE CNC Simulator (Python)   │
│  simulate_ie_cnc.py                  │
│  MotorSpeed · SpindleLoad · OEE      │
│  FeedRate · ToolTemp · FaultCode     │
└───────────────┬──────────────────────┘
                │ Azure Event Hub SDK
                │ (connection string)
                ▼
┌──────────────────────────────────────┐
│  Azure Event Hub                     │
│  cnc-telemetry                       │
└───────────────┬──────────────────────┘
                │ Fabric Eventstream
                ▼
┌──────────────────────────────────────┐
│  Microsoft Fabric                    │
│  KQL Database → CncTelemetry table  │
│  Real-Time Dashboard                 │
└──────────────────────────────────────┘

Azure IoT Operations (AIO) — edge platform layer
  K3s cluster  ·  MQTT Broker  ·  Asset Registry  ·  Dataflows
  (installed as the IoT platform; extensible for additional devices)
```

## What's included

| Component | Description |
|-----------|-------------|
| `scripts/` | Numbered bash scripts — run in order to stand up the full stack |
| `k8s/` | Kubernetes manifests for AIO broker and Event Hub dataflow endpoint |
| `simulator/` | Siemens IE CNC Python simulator with demo mode |
| `config/` | Variables template — fill in once, sourced by every script |
| `docs/` | Step-by-step Fabric setup guide |

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 11 + WSL2 (Ubuntu 22.04+) **or** Linux VM | All scripts run on Linux |
| 16 GB RAM, 4 vCPU | AIO deploys ~40 pods |
| Azure CLI (`az`) | [Install guide](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| `kubectl` | `az aks install-cli` or `sudo apt-get install kubectl` |
| Python 3.9+ | For the CNC simulator |
| Azure subscription | Contributor + User Access Administrator role |
| Microsoft Fabric capacity | F2 or higher; [free trial](https://learn.microsoft.com/fabric/get-started/fabric-trial) works |

---

## Quick start

### 1 — Clone and configure

```bash
git clone https://github.com/simonaarsene22/aio-siemens-ie-demo.git
cd aio-siemens-ie-demo

cp config/variables.env.template config/variables.env
# Edit config/variables.env — fill in SUBSCRIPTION_ID, STORAGE_ACCOUNT, EH_NAMESPACE
source config/variables.env
```

Key values:

| Variable | How to find it |
|---|---|
| `SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| `STORAGE_ACCOUNT` | Choose a globally unique name (3–24 lowercase alphanumeric) |
| `EH_NAMESPACE` | Choose a globally unique name, e.g. `eh-aio-demo-contoso` |

### 2 — Install K3s

```bash
bash scripts/01-install-k3s.sh
```

Verify: `kubectl get nodes` — node should be `Ready`.

### 3 — Connect to Azure Arc

```bash
az login
bash scripts/02-arc-connect.sh
```

Verify:
```bash
az connectedk8s show -n "$CLUSTER_NAME" -g "$RESOURCE_GROUP" \
  --query connectivityStatus -o tsv
# Expected: Connected
```

> If this fails with "provider not registered" — wait 2–3 minutes for async provider registration and retry.

### 4 — Deploy Azure IoT Operations

```bash
bash scripts/03-aio-deploy.sh
```

This takes **10–15 minutes**. AIO deploys ~40 pods in `azure-iot-operations`.

Verify: `az iot ops check` — all checks should pass.

### 5 — Create Event Hub

```bash
bash scripts/04-eventhub-setup.sh
```

This creates the `cnc-telemetry` Event Hub, assigns the AIO managed identity the **Data Sender** role, and **prints the connection string** you will use for the simulator.

Copy the printed `EH_CONNECTION_STRING` — you will need it in step 7.

### 6 — Apply Kubernetes manifests

```bash
bash scripts/05-apply-k8s.sh
```

Applies the MQTT broker listener (port 1883) and the Event Hub dataflow endpoint to the cluster.

### 7 — Run the Siemens IE CNC simulator

```bash
cd simulator
pip install -r requirements.txt

export EH_CONNECTION_STRING="<paste from step 5 output>"
export EH_NAME="cnc-telemetry"

# Normal mode (continuous telemetry):
python simulate_ie_cnc.py

# Demo mode (cycles Normal → Degrading → Fault → Recovering every 10 min):
DEMO_MODE=true DEMO_CYCLE_MINUTES=10 python simulate_ie_cnc.py
```

You should see JSON payloads printed every 5 seconds.

### 8 — Set up Microsoft Fabric

Follow [docs/fabric-setup.md](docs/fabric-setup.md) to:
- Create a Fabric Eventhouse and KQL database
- Create the `CncTelemetry` table
- Connect an Eventstream from Event Hub to the table
- Assign the Fabric managed identity access to Event Hub

### 9 — Verify end-to-end

```bash
bash scripts/06-verify.sh
```

In the Fabric KQL editor:
```kql
CncTelemetry
| order by timestamp desc
| take 10
```

You should see rows appearing within ~30 seconds of starting the simulator.

---

## Demo mode walkthrough

The simulator supports a scripted fault scenario useful for live demos:

```bash
DEMO_MODE=true DEMO_CYCLE_MINUTES=10 python simulator/simulate_ie_cnc.py
```

| Phase | Duration | What to show |
|-------|----------|--------------|
| **Normal** | 0–4 min | Stable OEE ~90%, tool temp ~45°C, no faults |
| **Degrading** | 4–7 min | OEE dropping, tool temp rising toward 90°C, overtemp warnings |
| **Fault** | 7–8 min | Machine stopped, FaultCode=101 latched, OEE near 0 |
| **Recovering** | 8–10 min | Restart sequence, metrics climbing back to baseline |

Useful KQL queries during the demo:

```kql
// Live OEE trend
CncTelemetry
| where timestamp > ago(15m)
| summarize avg(OEE_Pct) by bin(timestamp, 30s)
| render timechart

// Fault events
CncTelemetry
| where FaultCode != 0
| project timestamp, FaultCode, ToolTemperature_C, OEE_Pct
| order by timestamp desc
```

---

## Repository layout

```
aio-siemens-ie-demo/
├── README.md
├── .gitignore
├── config/
│   └── variables.env.template    ← copy to variables.env and fill in
├── scripts/
│   ├── 01-install-k3s.sh         ← K3s installation
│   ├── 02-arc-connect.sh         ← Azure Arc connection
│   ├── 03-aio-deploy.sh          ← AIO deployment (10-15 min)
│   ├── 04-eventhub-setup.sh      ← Event Hub + RBAC + connection string
│   ├── 05-apply-k8s.sh           ← Apply k8s manifests
│   └── 06-verify.sh              ← Full stack health check
├── k8s/
│   ├── broker-listener-1883.yaml ← AIO MQTT broker on port 1883
│   └── dataflow-endpoint-eh.yaml ← Event Hub Kafka endpoint (parameterized)
├── simulator/
│   ├── simulate_ie_cnc.py        ← Siemens IE CNC simulator
│   └── requirements.txt
└── docs/
    └── fabric-setup.md           ← Fabric Eventstream + KQL setup
```

---

## Troubleshooting

**Arc connection fails — "oidc-issuer not supported"**
```bash
az extension update --name connectedk8s
```

**AIO pods stuck in `Pending`**
```bash
kubectl describe pod <pod-name> -n azure-iot-operations
# Look for: Insufficient memory / Insufficient cpu
# Minimum: 8 GB free RAM before deploying AIO
```

**Simulator exits with "Set EH_CONNECTION_STRING"**
Re-run `bash scripts/04-eventhub-setup.sh` and copy the printed connection string.

**No data in Fabric KQL table**
1. Confirm the simulator is running and printing payloads
2. Check the Eventstream is in **Running** state in the Fabric portal
3. Verify the `Azure Event Hubs Data Receiver` role is assigned to the Fabric managed identity (see [docs/fabric-setup.md](docs/fabric-setup.md) step 4)
4. Check Event Hub metrics in Azure Portal — confirm messages are arriving

**Arc shows "Offline" in portal after restart**
This is a display lag. Check actual agent connectivity:
```bash
kubectl logs -n azure-arc \
  $(kubectl get pods -n azure-arc -l app=clusterconnect-agent -o name | head -1) \
  --tail=20
# Look for: "successfully sent heartbeat" or "Service Bus connection established"
```

---

## License

MIT
