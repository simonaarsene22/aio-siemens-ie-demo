# AI Agents on top of Fabric

Once telemetry is flowing into the Fabric KQL database, you can build two types of intelligence layer on top of it without writing any custom ingestion code:

1. **Fabric Data Activator** — no-code event-driven alerts
2. **Python agent** — conversational reasoning with Azure OpenAI tool calling

---

## Option 1: Fabric Data Activator (no-code alerts)

Data Activator watches a KQL table and fires actions — Teams messages, email, Power Automate flows — when conditions are met. No code required.

### Setup

1. In your Fabric workspace, click **New** → **Reflex**
2. Name it `CncAlerts`
3. Connect it to your Eventstream (`cnc-eventstream`)
4. Select `CncTelemetry` as the data source

### Useful triggers to configure

| Trigger name | Condition | Action |
|---|---|---|
| Tool overtemp | `ToolTemperature_C > 85` for 2 consecutive readings | Send Teams message: "CNC-001 tool temperature at {{ToolTemperature_C}}°C — inspect spindle cooling" |
| OEE degradation | `OEE_Pct < 70` for 5 minutes | Send email to shift lead |
| Fault latch | `FaultCode != 0` | Post to Teams channel with timestamp and fault code |
| Machine stopped | `RunningStatus == false` for 3 minutes | Trigger Power Automate flow to create maintenance ticket |

### No-code vs. custom agent tradeoffs

| | Data Activator | Python agent |
|---|---|---|
| Setup time | ~10 minutes | ~30 minutes |
| Custom logic | Threshold-based only | Arbitrary reasoning |
| Conversational | No | Yes |
| Historical analysis | No | Yes (any KQL window) |
| Cost | Included in Fabric | Azure OpenAI tokens |

---

## Option 2: Python agent with Azure OpenAI

`agent/agent.py` provides a conversational interface that queries the live KQL database and reasons over the results using Azure OpenAI function calling.

The agent has four tools:

| Tool | What it does |
|---|---|
| `current_status` | Latest telemetry snapshot for a machine |
| `fault_history` | All fault events in a time window |
| `oee_trend` | OEE binned over time — spotting degradation trends |
| `thermal_analysis` | Temperature stats + risk level (NORMAL / ELEVATED / WARNING / CRITICAL) |

The model decides which tools to call based on the user's question, calls them, and synthesises a natural-language answer with a recommended action.

### Prerequisites

- Python 3.9+
- Azure OpenAI resource with a `gpt-4o` or `gpt-4-turbo` deployment
- Fabric KQL database with the `CncTelemetry` table (from [fabric-setup.md](fabric-setup.md))
- Entra ID identity with **Viewer** role on the Fabric Eventhouse

### Environment variables

```bash
# Fabric KQL — find the query URI on the Eventhouse overview page
export KUSTO_CLUSTER="https://<eventhouse>.<workspace-id>.kusto.fabric.microsoft.com"
export KUSTO_DATABASE="DemoDatabase"

# Azure OpenAI
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
export AZURE_OPENAI_API_KEY="<your-key>"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"   # or your deployment name

# Optional — defaults to CncTelemetry
export KQL_TABLE="CncTelemetry"
```

### Installation

```bash
cd agent
pip install -r requirements.txt
```

### Authentication

The agent uses `DefaultAzureCredential`. In order of preference it picks up:
- Environment variables (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`)
- A Workload Identity or Managed Identity if running in Azure
- Your local `az login` session (recommended for local development)

For local development, log in once:
```bash
az login
```

### Running the agent

**Interactive loop:**
```bash
python agent.py
```

```
CNC Maintenance Agent
Type your question or 'exit' to quit.

You: What is the current status of CNC-001?
Agent: CNC-001 is running normally. Motor speed is 1420 RPM, OEE is 89.3%,
       tool temperature is 48°C (within normal range). No active faults.

You: Show me any faults in the last 2 hours
Agent: I found 3 fault events for CNC-001 in the last 2 hours:
       - 14:32 UTC — FaultCode 101 (spindle overtemp), temp was 97°C, OEE dropped to 0%
       ...

You: Is the tool temperature trending dangerously?
Agent: Tool temperature over the last 15 minutes: avg 71°C, current 74°C, max 76°C.
       Risk level: ELEVATED — monitor closely. Temperature is rising at roughly 1°C/min.
       Recommend: check spindle coolant flow before the next production cycle.
```

**Single question (useful for scripts or automation):**
```bash
python agent.py "What is the current OEE and are there any active faults?"
```

### Example questions

```
What is the current machine status?
Have there been any faults in the last hour?
Show me the OEE trend over the last 30 minutes
Is the tool temperature within safe limits?
What was happening when the last fault occurred?
Compare OEE during the degrading phase vs normal operation
```

---

## Extending the agent

### Add a new tool

1. Write a Python function that runs a KQL query and returns a dict or list
2. Add a tool definition to the `TOOLS` list in `agent.py`
3. Register the function in the `TOOL_FNS` dict

Example — add a parts-per-hour throughput tool:

```python
def throughput(machine_id: str = "CNC-001", lookback_minutes: int = 60) -> dict:
    query = f"""
CncTelemetry
| where device == '{machine_id}' and timestamp > ago({lookback_minutes}m)
| summarize parts = max(PartCount) - min(PartCount)
| extend parts_per_hour = round(parts * 60.0 / {lookback_minutes}, 1)
"""
    rows = _run_kql(query)
    return rows[0] if rows else {}
```

### Connect to multiple machines

Pass different `machine_id` values — the KQL queries are parameterised. To list all machines with active faults:

```python
def all_machines_with_faults() -> list[dict]:
    query = """
CncTelemetry
| where timestamp > ago(5m) and FaultCode != 0
| summarize last_fault = max(FaultCode), last_temp = max(ToolTemperature_C) by device
"""
    return _run_kql(query)
```

### Deploy as a web endpoint

Wrap `run_agent()` in a FastAPI handler to expose the agent as a REST endpoint:

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Question(BaseModel):
    question: str
    machine_id: str = "CNC-001"

@app.post("/ask")
def ask(body: Question):
    answer = run_agent(body.question)
    return {"answer": answer}
```

---

## Architecture with agents

```
  AZURE CLOUD
  +---------------------------------------------------------------------+
  |                                                                     |
  |  Event Hub → Fabric Eventstream → KQL Database → Dashboard         |
  |                                         |                           |
  |                                         v                           |
  |  +-------------------------------+  +---------------------------+  |
  |  |  Data Activator (Fabric)      |  |  Python Agent             |  |
  |  |  Threshold triggers           |  |  Azure OpenAI + KQL tools |  |
  |  |  → Teams / email / PA flow    |  |  Conversational reasoning |  |
  |  +-------------------------------+  +---------------------------+  |
  |                                                                     |
  +---------------------------------------------------------------------+
```
