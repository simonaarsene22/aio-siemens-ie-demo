# Partner demo script — one profile, two very different machines

Narrative in one line: *"Here's one Siemens machine exactly as Industrial Edge
sees it today — a bag of tags, no shared meaning. Watch what happens when we
give it a profile: it becomes a typed asset Azure IoT Operations understands.
Then watch a legacy machine with none of the modern conveniences — cryptic
PLC tags, wrong units — land in the exact same shape. That same pattern feeds
Fabric today and any other consumer — Databricks included — tomorrow."*

Target length: ~13 minutes + Q&A. Deeper technical proof (the full 14-test
suite) is an appendix at the end — pull it out only if asked.

---

## Decision point — confirm before the meeting

| Path | Requires | What it shows |
|---|---|---|
| **B — Console only (default)** | Nothing — runs fully offline | The whole story, zero cloud dependency, zero live-infra risk |
| **A — Live Azure** | A real Event Hub / deployed AIO cluster | Same story, plus a live Fabric KQL dashboard as the downstream leg |

As of now there's no cluster/Event Hub deployed, so **Path B is the
default**. `PUBLISH_MODE=console` (the default for both simulators) prints
payloads to stdout with no Azure/AIO dependency.

**On Databricks**: it is not part of this build. It comes up only as a
one-line generalization at the close — don't demo it, don't imply it's wired
up.

---

## Pre-demo checklist (T-10 min)

- [ ] One terminal, `cd`'d into the repo root
- [ ] `python ontology/show_live_mapping.py cnc001` and `python ontology/show_live_mapping.py grind077` both run once beforehand — confirm two clean 8-row tables
- [ ] `ontology/aas_cnc_submodel.json` open in an editor tab — the only ontology file you need on screen for the main flow
- [ ] Font size large enough to read from across a table / on screen share
- [ ] Two recognizable details ready to point at if asked: (1) the Nameplate `semanticId` values (e.g. `0173-1#01-AHF579#001`) are real ECLASS/IRDI codes from the ZVEI Digital Nameplate spec, (2) GRIND-077's raw tags (`DB10.DBD4`, `MW102`) are realistic S7 absolute addresses — signals "not a toy problem"

---

## Script

### 1. Before — the device as Industrial Edge sees it today (2 min)

Start the CNC simulator, console mode, **without** narrating any ontology yet:

```bash
cd simulator
PUBLISH_MODE=console DEMO_MODE=true DEMO_CYCLE_MINUTES=10 python simulate_ie_cnc.py
```

Let a couple of payloads print, then say:

*"This is one Siemens CNC, managed the way Industrial Edge Management shows
it today — a stream of tags. `MotorSpeed_RPM`, `ToolTemperature_C`,
`FaultCode`. No enforced type, no unit, no shared meaning outside this one
JSON blob. If AIO, Fabric, or anything else wants to consume this, someone
hand-writes that mapping today — and it silently breaks the moment a tag
gets renamed."*

Leave it running in the background for the rest of the demo.

### 2. Add the profile — the Siemens asset model (2 min) — `ontology/aas_cnc_submodel.json`

- Open the file. Point at `Nameplate` first — *"real ZVEI Digital Nameplate
  shape, same semanticIds a real Siemens AAS server would give you."*
- Scroll to `CncOperationalData`, point at one property (e.g.
  `ToolTemperature_C`) — *"same tag you just saw in the raw stream, but now
  it has a `semanticId`, a `valueType`, a unit. And this isn't private to
  this one CNC — it's an instance of a shared profile,
  `machine_operational_data_profile.json`. Any machine that implements the
  same profile becomes interchangeable to AIO. That's what we're about to
  prove."*

### 3. Transform and ingest — into AIO (2 min)

*"AIO doesn't read Siemens' ontology directly — it speaks a different
language, the W3C Web of Things standard. So the profile gets transformed,
automatically, into the shape AIO actually understands, then into an AIO
asset."*

```bash
python ontology/generate_wot_td.py cnc001
python ontology/generate_aio_asset.py cnc001
python ontology/show_live_mapping.py cnc001
```

Point at the last command's output — one table, one row per tag: the AIO
asset property, the raw field, the transform (all `identity` for this
device), and the **live value** resolved from the device streaming in the
background.

*"That's the 'after' picture for a well-behaved device. Now the actual
test."*

### 4. The hard case — a machine that doesn't cooperate (3 min) — the payoff

*"Every machine you'll actually meet in the field doesn't look like CNC-001.
Here's GRIND-077 — a legacy S7-300 grinding cell, no IE Databus, just raw PLC
addresses."*

```bash
python -c "import sys; sys.path.insert(0,'simulator'); import simulate_grind077_plc as g; print(g.build_raw_payload())"
```

*"Look at that: `DB10.DBD4`, `MW102`, `M20.1`. No semantic names. And the
units are wrong on top of it — load is a scaled integer, temperature is in
Fahrenheit, running status is a raw 0-or-1, not true/false. This is the
actual hard problem."*

```bash
python ontology/generate_wot_td.py grind077
python ontology/generate_aio_asset.py grind077
python ontology/show_live_mapping.py grind077
```

Point at the `transform` column — `divide_10`, `fahrenheit_to_celsius`,
`int_to_bool` — then at the `AIO dataPoint` column.

*"Same property names. Same units. Same shape as CNC-001, two commands ago —
because both machines implement the same profile, and the profile is what
AIO actually cares about, not the wire format underneath. Nothing about this
machine's messiness reached AIO."*

### 5. Flows onward — Fabric today, anything tomorrow (2 min)

**Path A (live Azure)**: flip to the Fabric KQL dashboard, show
`CncTelemetry` rows landing with the same field names and units you just
saw in the ontology.

**Path B (console only)**: *"From here it's one Event Hub hop into a Fabric
Eventstream and a KQL table — same field names, same types, same units, for
both machines. And because what AIO has is just typed data on a standard
shape, the exact same pattern is what would feed Databricks, or any other
consumer, without touching either machine's ontology again."*

### 6. Close (1 min)

*"One profile is the contract. Two machines — one modern, one from 2011 with
none of the conveniences — both land in AIO looking identical, because both
implement it. That's the difference between 'a bag of tags' and 'an asset,'
and it's the pattern we'd repeat for every machine on the floor, not just
these two."*

---

## Anticipated partner questions

| Question | Answer |
|---|---|
| "Is this the real AAS standard or a simplified version?" | Real AAS v3 JSON metamodel shape (IDTA-01001-3-0), with real ZVEI nameplate semanticIds. Simplified in that it's one instance, not a full AAS server/repository. |
| "Is GRIND-077 a real machine or a made-up example?" | Simulated, but the raw tag shape (absolute S7 addresses, scaled integers, Fahrenheit) is deliberately realistic — modeled on genuine legacy-PLC integration pain, not invented for effect. |
| "Is Databricks actually wired up?" | No — mentioned only as a generalization. The pattern (typed data, standard shape) is what makes adding a second consumer straightforward; it isn't built or demoed today. |
| "Why is WoT in here — is that actually what AIO uses?" | Yes — AIO's connector framework (Akri) resolves device/asset capabilities against a W3C WoT Thing Description, not a vendor ontology directly. |
| "How do I know the profile, the ontology, and the transforms actually agree, not just today?" | There's a 14-test automated suite (`ontology/test_ontology_mapping.py`) that checks profile conformance across both devices, both AAS→WoT hops, every transform's correctness, and both WoT→AIO hops — all against real simulator output. Happy to run it — see appendix. |
| "How does this handle OPC UA specifically?" | AIO's native Asset CRDs target OPC UA/media/REST connectors most directly; this MQTT-sourced asset is the illustrative case — same pattern, the dataflow-side mapping differs. |
| "What happens when you add a third machine type?" | New AAS submodel conforming to the same profile, a binding file only if its raw tags need reconciling, same two generators, same test — the pattern doesn't change per asset type. |

---

## If something breaks live

- Simulator or generator errors: don't debug live — say *"let's come back to
  that after"* and move to the next beat.
- Live Azure (Path A) unreachable: fall back to Path B narration — no setup
  needed, nothing to fix.

---

## Appendix — deeper technical proof (only if asked)

Everything in the main script is generated by a handful of commands and
shown via two tables. If a technical stakeholder wants to see it's actually
*enforced*, not just internally consistent today, run the full test suite:

```bash
python -m unittest ontology.test_ontology_mapping -v
```

14 tests, across both devices: each AAS submodel is well-formed; both
genuinely conform to the same profile (same submodel-level semanticId, same
property set, same type/unit/semanticId per property); GRIND-077's raw
payload is confirmed to contain none of the canonical names (the premise
check — otherwise the binding wouldn't be proving anything) while CNC-001's
does; each AAS property survives the hop into its WoT Thing Description with
the *same* semanticId; applying each device's transform to real raw
telemetry resolves to a value matching the ontology's declared type; and
each generated AIO asset has one dataPoint per property, resolving against
real telemetry. Open `ontology/profiles/machine_operational_data_profile.json`,
`ontology/bindings/grind077_binding.json`, `ontology/*.td.json`, and
`k8s/asset-*.yaml` if they want to see the intermediate artifacts — all
generated, none hand-maintained.
