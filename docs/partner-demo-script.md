# Partner demo script — Siemens ontology → AIO integration

Narrative in one line: *"Siemens describes this CNC using the open AAS
standard, AIO resolves assets through the W3C Web of Things standard — here's
proof that mapping stays honest across both hops into Azure IoT Operations,
live."*

Target length: ~15 minutes + Q&A.

---

## Decision point — confirm before the meeting

The live-telemetry segment below has two possible paths depending on what's
deployed right now:

| Path | Requires | What it shows |
|---|---|---|
| **A — Live Azure** | A real Event Hub (or MQTT broker on a deployed AIO cluster) with `EH_CONNECTION_STRING` set | Full edge→cloud path, optionally into a live Fabric KQL dashboard |
| **B — Console only** | Nothing — runs fully offline | Same ontology/telemetry story, no cloud dependency, zero risk of a live-infra hiccup in front of the partner |

As of now there's no cluster/Event Hub deployed in this session, so **Path B
is the safe default**. If you want Path A, we'd need to redeploy
(`scripts/01`–`05`) beforehand and confirm `az iot ops check` passes.

Path B is ready: `PUBLISH_MODE=console` prints payloads to stdout with no
Azure/AIO dependency at all (added specifically so this demo doesn't need
live infra). Also fixed while testing this: the simulator's startup banner
used to crash on Windows consoles (cp1252 can't print `→`/`—`) — it now
forces UTF-8 stdout, so `python simulate_ie_cnc.py` just works.

---

## Pre-demo checklist (T-15 min)

- [ ] Confirm Path A or B (above) and, if A, that `az iot ops check` is green
- [ ] Two terminals open, both `cd`'d into the repo root
- [ ] `python -m unittest ontology.test_ontology_mapping -v` run once beforehand as a dry run — confirm 13/13 pass
- [ ] `ontology/aas_cnc_submodel.json`, `ontology/cnc-001.td.json`, `k8s/asset-cnc-001.yaml`, and `docs/ontology.md`'s pipeline diagram open in editor tabs, ready to switch to
- [ ] Font size large enough to read from across a table / on screen share
- [ ] Know the two Siemens/standards-recognizable details to point at: (1) the Nameplate `semanticId` values (e.g. `0173-1#01-AHF579#001`) are real ECLASS/IRDI codes from the ZVEI Digital Nameplate spec, (2) the WoT Thing Description is real W3C WoT TD 1.1 shape (`@context`, `properties`, `forms`) — this is what signals "not a toy schema" to a technical audience

---

## Script

### 1. Frame the problem (2 min) — talking, no screen

Say something like: *"When you connect a Siemens edge asset into a partner's
IoT platform, the risk isn't the wire protocol — it's semantic drift. Their
asset model says one thing, your platform's asset model says another, and
nobody notices until a dashboard shows the wrong unit. We're going to show
you how we keep those two in sync, and prove it rather than just claim it."*

### 2. Show the Siemens-side ontology (3 min) — `ontology/aas_cnc_submodel.json`

- Open the file. Point at the `Nameplate` submodel first — *"this is the
  standard ZVEI Digital Nameplate shape, same semanticIds you'd get from a
  real Siemens AAS server."*
- Scroll to `CncOperationalData`. Point at one `Property` (e.g.
  `ToolTemperature_C`) — walk through `semanticId`, `valueType`, `unit`.
- Say: *"Every tag this machine exposes is declared once, here, with a type
  and a unit. This is the source of truth — not the simulator code, not the
  AIO config."*

### 3. Show the WoT layer (2 min) — `ontology/cnc-001.td.json`

- Say: *"AIO's connector framework doesn't read Siemens' ontology directly —
  it resolves what a device exposes through a W3C Web of Things Thing
  Description. So the ontology has to survive one more hop before it ever
  touches Azure."*
- Run the generator live:

```bash
python ontology/generate_wot_td.py
```

- Open the output. Point at one property (e.g. `ToolTemperature_C`) and show
  its `@type` — *"this is the exact same semanticId URN as the AAS property,
  not just the same name. That's checked, not assumed — if a rename on
  either side breaks that link, the test in a minute catches it."*

### 4. Show the AIO-side mapping (1 min) — `k8s/asset-cnc-001.yaml`

- Open the generated file. *"This is generated, not hand-maintained — one
  more command turns the WoT model into an Azure IoT Operations Asset
  definition."*

```bash
python ontology/generate_aio_asset.py
```

- *"If someone adds a tag on the Siemens side, both of these regenerate
  automatically — no manual asset editing in AIO."*

### 5. Prove it, live (2 min) — the integrity test

```bash
python -m unittest ontology.test_ontology_mapping -v
```

- While it runs: *"This isn't a demo of files that happen to agree today —
  it checks the AAS-to-WoT hop, the WoT-to-AIO hop, and the real simulator
  output, all three, every run. If any one of those drifts, this fails and
  names the exact property."*
- Let all 13 tests print `ok`.
- **Optional gut-punch moment**: if you want a bigger reaction, briefly
  rename a field in a scratch copy beforehand and show the test failing with
  a clear message, then switch back to the real file and show it passing.
  Only do this if you've rehearsed it — don't improvise a live break.

### 6. Live telemetry (5–6 min)

**Path A (live Azure):**
```bash
cd simulator
export EH_CONNECTION_STRING="<from scripts/04 output>"
DEMO_MODE=true DEMO_CYCLE_MINUTES=10 python simulate_ie_cnc.py
```
Narrate the phase cycle as it happens (Normal → Degrading → Fault →
Recovering) and, if Fabric is live, flip to the KQL dashboard and show
`OEE_Pct` dropping in real time — tie each field back to the ontology
Property you showed in step 2.

**Path B (console only):**
```bash
cd simulator
PUBLISH_MODE=console DEMO_MODE=true DEMO_CYCLE_MINUTES=10 python simulate_ie_cnc.py
```
Same narration, minus the cloud/Fabric leg — the payloads print locally and
you talk through them matching the ontology field-by-field.

### 7. Close (1 min)

*"So: one ontology file is the contract, one generated WoT model is the
handshake AIO actually understands, and the AIO asset is generated from
that, not hand-typed. All three are enforced by an automated test, not a
code review checklist. That's the pattern we'd extend to every other asset
type as this scales past one CNC."*

---

## Anticipated partner questions

| Question | Answer |
|---|---|
| "Is this the real AAS standard or a simplified version?" | Real AAS v3 JSON metamodel shape (IDTA-01001-3-0), with real ZVEI nameplate semanticIds. Simplified in that it's one instance, not a full AAS server/repository. |
| "Does this talk to a real AAS server / Siemens IE ontology export?" | Not yet — today it's a hand-authored submodel matching the simulator's actual tags. Natural next step is importing straight from an IE-exported AAS package instead of hand-authoring it. |
| "Why is WoT in here — is that actually what AIO uses?" | Yes — AIO's connector framework (Akri) resolves device/asset capabilities against a W3C WoT Thing Description, not against a vendor ontology directly. That's why the pipeline has that middle layer rather than mapping AAS straight to an AIO asset. |
| "Is the MQTT `jsonPath` field in the TD a real WoT keyword?" | No, flagged as such in the code — the WoT MQTT binding doesn't yet standardize "one topic, many properties via JSON path" the way this IE Databus topic works. It's a documented pragmatic extension, not a spec claim. |
| "How does this handle OPC UA specifically?" | AIO's native Asset CRDs target OPC UA/media/REST connectors most directly; this MQTT-sourced asset is the illustrative case — same WoT TD, same test, the dataflow-side mapping differs. Worth a follow-up if they want the OPC UA path specifically. |
| "What happens when you add a new machine type, not just CNC-002?" | New AAS submodel, same two generators, same test — the pattern doesn't change per asset type. |

---

## If something breaks live

- Test failure you didn't expect: don't debug live — say *"good, this is
  exactly the kind of thing this is designed to catch, let's come back to it
  after"* and move on to the next section.
- Live Azure (Path A) unreachable: switch to Path B (`PUBLISH_MODE=console`)
  on the spot — no setup needed — or fall back to a pre-recorded take.
