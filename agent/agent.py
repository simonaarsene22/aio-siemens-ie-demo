"""
CNC Maintenance Agent — queries Microsoft Fabric KQL and reasons with Azure OpenAI.

The agent exposes four tools over the CncTelemetry table:
  current_status      — latest reading for a machine
  fault_history       — all fault events in a time window
  oee_trend           — OEE over time, binned by minute
  thermal_analysis    — tool temperature trend and overheat risk

Usage:
    # Set env vars (see docs/agents.md for full setup)
    export KUSTO_CLUSTER="https://<eventhouse>.<workspace-id>.kusto.fabric.microsoft.com"
    export KUSTO_DATABASE="DemoDatabase"
    export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
    export AZURE_OPENAI_API_KEY="<your-key>"
    export AZURE_OPENAI_DEPLOYMENT="gpt-4o"

    # Interactive loop
    python agent.py

    # Single question
    python agent.py "What is the current OEE and are there any active faults?"
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.helpers import dataframe_from_result_table
from openai import AzureOpenAI

# ── Config ────────────────────────────────────────────────────────────────────

KUSTO_CLUSTER    = os.environ["KUSTO_CLUSTER"]
KUSTO_DATABASE   = os.environ["KUSTO_DATABASE"]
OPENAI_ENDPOINT  = os.environ["AZURE_OPENAI_ENDPOINT"]
OPENAI_KEY       = os.environ["AZURE_OPENAI_API_KEY"]
OPENAI_DEPLOY    = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
TABLE            = os.environ.get("KQL_TABLE", "CncTelemetry")

# ── KQL client ────────────────────────────────────────────────────────────────

def _kusto_client() -> KustoClient:
    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        KUSTO_CLUSTER, credential
    )
    return KustoClient(kcsb)


def _run_kql(query: str) -> list[dict]:
    client = _kusto_client()
    response = client.execute(KUSTO_DATABASE, query)
    df = dataframe_from_result_table(response.primary_results[0])
    return df.to_dict(orient="records")


# ── Tools ─────────────────────────────────────────────────────────────────────

def current_status(machine_id: str = "CNC-001") -> dict[str, Any]:
    """Return the most recent telemetry row for a machine."""
    query = f"""
{TABLE}
| where device == '{machine_id}'
| order by timestamp desc
| take 1
| project
    timestamp, device,
    MotorSpeed_RPM, SpindleLoad_Pct, FeedRate_mm_min,
    ToolTemperature_C, OEE_Pct, FaultCode, RunningStatus, DemoPhase
"""
    rows = _run_kql(query)
    return rows[0] if rows else {"error": f"No data found for machine {machine_id}"}


def fault_history(machine_id: str = "CNC-001", lookback_minutes: int = 60) -> list[dict]:
    """Return all fault events in the last N minutes for a machine."""
    query = f"""
{TABLE}
| where device == '{machine_id}'
  and timestamp > ago({lookback_minutes}m)
  and FaultCode != 0
| order by timestamp desc
| project timestamp, FaultCode, ToolTemperature_C, OEE_Pct, DemoPhase
"""
    rows = _run_kql(query)
    return rows if rows else [{"message": f"No faults in the last {lookback_minutes} minutes"}]


def oee_trend(machine_id: str = "CNC-001", lookback_minutes: int = 30,
              bin_seconds: int = 60) -> list[dict]:
    """Return OEE averaged over time bins for a machine."""
    query = f"""
{TABLE}
| where device == '{machine_id}'
  and timestamp > ago({lookback_minutes}m)
| summarize
    avg_oee   = round(avg(OEE_Pct), 1),
    avg_speed = round(avg(MotorSpeed_RPM), 0),
    phase     = any(DemoPhase)
    by bin(timestamp, {bin_seconds}s)
| order by timestamp asc
"""
    return _run_kql(query)


def thermal_analysis(machine_id: str = "CNC-001",
                     lookback_minutes: int = 15) -> dict[str, Any]:
    """
    Return tool temperature statistics and a risk assessment.
    Overtemp threshold: 85 C (fault typically triggers at ~95 C).
    """
    query = f"""
{TABLE}
| where device == '{machine_id}'
  and timestamp > ago({lookback_minutes}m)
| summarize
    current_temp  = round(max(ToolTemperature_C), 1),
    avg_temp      = round(avg(ToolTemperature_C), 1),
    min_temp      = round(min(ToolTemperature_C), 1),
    samples       = count(),
    above_85c     = countif(ToolTemperature_C > 85),
    above_90c     = countif(ToolTemperature_C > 90)
"""
    rows = _run_kql(query)
    if not rows:
        return {"error": "No data"}
    row = rows[0]
    current = row.get("current_temp", 0)
    row["risk"] = (
        "CRITICAL — above fault threshold"   if current > 90 else
        "WARNING — approaching fault threshold" if current > 85 else
        "ELEVATED — monitor closely"         if current > 70 else
        "NORMAL"
    )
    return row


# ── Tool definitions for OpenAI ───────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "current_status",
            "description": "Get the latest telemetry reading for a CNC machine — speed, load, temperature, OEE, fault code, running state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "Machine identifier, e.g. CNC-001",
                        "default": "CNC-001"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fault_history",
            "description": "Retrieve all fault events for a machine within a lookback window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id":        {"type": "string", "default": "CNC-001"},
                    "lookback_minutes":  {"type": "integer", "description": "How far back to look in minutes", "default": 60}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "oee_trend",
            "description": "Get Overall Equipment Effectiveness (OEE) over time, binned by minute. Use this to spot degradation trends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id":       {"type": "string", "default": "CNC-001"},
                    "lookback_minutes": {"type": "integer", "default": 30},
                    "bin_seconds":      {"type": "integer", "description": "Bin size in seconds", "default": 60}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "thermal_analysis",
            "description": "Analyse tool temperature over a lookback window and return a risk level (NORMAL / ELEVATED / WARNING / CRITICAL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id":       {"type": "string", "default": "CNC-001"},
                    "lookback_minutes": {"type": "integer", "default": 15}
                }
            }
        }
    }
]

TOOL_FNS = {
    "current_status":  current_status,
    "fault_history":   fault_history,
    "oee_trend":       oee_trend,
    "thermal_analysis": thermal_analysis,
}

# ── Agent loop ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a CNC machine maintenance assistant with access to
real-time telemetry from Microsoft Fabric. Use the available tools to answer
questions about machine health, faults, OEE, and thermal state. Be concise
and actionable. When you detect a fault or high temperature, recommend a
specific next step."""


def run_agent(user_question: str) -> str:
    client = AzureOpenAI(
        azure_endpoint=OPENAI_ENDPOINT,
        api_key=OPENAI_KEY,
        api_version="2024-10-21",
    )

    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": user_question},
    ]

    while True:
        response = client.chat.completions.create(
            model=OPENAI_DEPLOY,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content

        # Execute all tool calls
        messages.append(msg)
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments or "{}")
            result  = TOOL_FNS[fn_name](**fn_args)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(result, default=str),
            })


def main():
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(run_agent(question))
        return

    print("CNC Maintenance Agent")
    print("Type your question or 'exit' to quit.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("exit", "quit"):
            break
        answer = run_agent(question)
        print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    main()
