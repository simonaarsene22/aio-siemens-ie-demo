# Microsoft Fabric Setup

This guide sets up the Fabric Eventstream and KQL Database that receive CNC telemetry from the Siemens IE CNC simulator.

---

## 1. Create a Fabric workspace

1. Open [app.fabric.microsoft.com](https://app.fabric.microsoft.com)
2. Click **Workspaces** → **New workspace**
3. Name it (e.g. `AIO-Siemens-Demo`) and assign a Fabric capacity (F2+ or trial)

---

## 2. Create the KQL Database

1. In your workspace, click **New** → **Eventhouse**
2. Name it (e.g. `DemoEventhouse`)
3. Inside the Eventhouse, create a KQL database named `DemoDatabase`
4. Create the CNC telemetry table:

```kql
.create table CncTelemetry (
    timestamp:      datetime,
    device:         string,
    MotorSpeed_RPM: real,
    SpindleLoad_Pct: real,
    FeedRate_mm_min: real,
    ToolTemperature_C: real,
    PartCount:      long,
    FaultCode:      int,
    RunningStatus:  bool,
    OEE_Pct:        real,
    DemoPhase:      string
)
```

---

## 3. Create the Eventstream

1. In your workspace, click **New** → **Eventstream**
2. Name it `cnc-eventstream`

### Add source: Azure Event Hubs

- **Event Hub namespace**: `<EH_NAMESPACE>.servicebus.windows.net`
- **Event Hub**: `cnc-telemetry` (or your `EH_CNC_NAME`)
- **Consumer group**: `$Default`
- **Authentication**: Shared Access Signature — paste the connection string from script 04 output

### Add destination: KQL Database

- Select your Eventhouse and `DemoDatabase`
- Table: `CncTelemetry`
- Input format: **JSON**
- Map fields:

| Source field | Destination column | Type |
|---|---|---|
| `timestamp` | `timestamp` | datetime |
| `device` | `device` | string |
| `MotorSpeed_RPM` | `MotorSpeed_RPM` | real |
| `SpindleLoad_Pct` | `SpindleLoad_Pct` | real |
| `FeedRate_mm_min` | `FeedRate_mm_min` | real |
| `ToolTemperature_C` | `ToolTemperature_C` | real |
| `PartCount` | `PartCount` | long |
| `FaultCode` | `FaultCode` | int |
| `RunningStatus` | `RunningStatus` | bool |
| `OEE_Pct` | `OEE_Pct` | real |
| `DemoPhase` | `DemoPhase` | string |

---

## 4. Assign Fabric managed identity access to Event Hub

Fabric reads from Event Hub using its own managed identity. Assign it the **Azure Event Hubs Data Receiver** role:

```bash
source config/variables.env

# Get your Fabric workspace managed identity object ID from:
# Azure Portal → Microsoft Fabric → your workspace → Settings → Managed Identity
FABRIC_IDENTITY_ID="<your-fabric-workspace-managed-identity-object-id>"

EH_NAMESPACE_ID=$(az eventhubs namespace show \
  --name "$EH_NAMESPACE" \
  --resource-group "$RESOURCE_GROUP" \
  --query id -o tsv)

az role assignment create \
  --assignee-object-id "$FABRIC_IDENTITY_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure Event Hubs Data Receiver" \
  --scope "$EH_NAMESPACE_ID"
```

---

## 5. Verify data is arriving

Start the simulator (see README), then run this KQL query in the Fabric KQL editor:

```kql
CncTelemetry
| order by timestamp desc
| take 10
```

---

## 6. Sample queries

**Current OEE and machine status:**
```kql
CncTelemetry
| summarize
    avg_oee = avg(OEE_Pct),
    avg_temp = avg(ToolTemperature_C),
    last_fault = max(FaultCode)
    by device, bin(timestamp, 1m)
| order by timestamp desc
```

**Fault events only:**
```kql
CncTelemetry
| where FaultCode != 0
| project timestamp, device, FaultCode, ToolTemperature_C, OEE_Pct
| order by timestamp desc
```

**Demo phase timeline:**
```kql
CncTelemetry
| summarize count() by bin(timestamp, 30s), DemoPhase
| render timechart
```
