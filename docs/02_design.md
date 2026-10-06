# Template Design Specification

## Position in the framework architecture

- **Agent Class**: RecommendationAlgorithmDisclosureAgent
- **L1 Base (framework base class)**: AgentBaseGraph — direct framework inheritance
- **Category**: Cat 2 — a document-generation pipeline for one job-to-be-done
- **Three-layer separation**:
  - State: flat TypedDict composition (`src/schemas/state.py` extends `AgentState`; never a
    model object — checkpoints are serialized with msgpack and model objects corrupt silently)
  - Node: `FunctionNode` inheritance; `execute(self, state: AgentState) -> Dict[str, Any]` is the
    only override, and it returns ONLY the fields it changes
  - Graph: composition via `register_nodes()`; outer `AgentBaseGraph` + inner `BaseGraph`

## Architecture overview

### Nested composition

Outer graph (`src/graph/graph.py`): `RecommendationAlgorithmDisclosureAgent(AgentBaseGraph)`
runs the fixed five-node backbone. The domain pipeline is encapsulated inside
`DisclosureWorkflowGraphNode(GraphNode)` in the `main` slot.
Inner graph (`src/graph/domain_workflow_graph.py`): `DomainWorkflowGraph(BaseGraph)` runs the
six-node linear disclosure pipeline.

### Outer backbone (fixed — AgentBaseGraph)

```
START -> initialize -> pre_process -> main -> {route} -> post_process -> finalize -> END
                                           (RETRY -> pre_process, bounded by max_retry)
```

`add_edges()` is not overridden. `route()` sends a non-success `main` straight to `finalize`,
past `post_process` — which is why the output boundary is not the only place containment lives
(see below).

### Inner domain workflow (inside DisclosureWorkflowGraphNode)

```
START -> engine_spec_parse -> appi_obligation_classify -> disclosure_language_gen
      -> ai_act_doc_checklist -> data_gov_gap_flag -> attestation_format -> END
```

### The subgraph boundary, and why there is a bridge

The framework invokes a nested graph as `subgraph.invoke(user_input, session_id=…, ctx=…)`.
**Only the request string crosses.** Neither the outer state nor the caller's structured
invocation parameters are forwarded.

That is not a theoretical limitation here. Four of the ten AI Act checklist requirements and
five of the seven governance gap checks read their evidence from `state["engine_spec_raw"]`,
which the inner graph never received — so a specification documenting human review, performance
benchmarks, bias monitoring and an annual third-party audit produced a **byte-identical**
checklist to one documenting none of them.

`src/graph/context_bridge.py` closes it with the two sanctioned subclass hooks:

| step | hook | what it does |
|---|---|---|
| before the inner invoke | `DisclosureWorkflowGraphNode.extract_input()` | stashes the validated specification and the validated caller contract on a `ContextVar` |
| inside the inner invoke | `DomainWorkflowGraph._extra_initial_state()` | seeds both into the inner state, along with the live `assessment` tuning |

Only validated values cross. A `ContextVar` keeps the hand-off per thread and per task, so
concurrent invocations in one process cannot see each other's request.

### Node configuration

| Node | Class | Responsibility | Trust Level | Input State Keys | Output State Keys |
|------|-------|---------------|-------------|-----------------|------------------|
| initialize | InitializeNode (framework) | Set schema_version, session_id, trust_level | — | — | session_id, schema_version |
| pre_process | PreProcessNode | Validate both caller channels; screen for injection | VERIFIED_EXTERNAL | user_input, input_context | validated_input, engine_spec_raw, caller_contract |
| main | DisclosureWorkflowGraphNode | Wrap the inner DomainWorkflowGraph | GraphNode (pass-through) | validated_input, engine_spec_raw, caller_contract | result, all domain fields |
| post_process | PostProcessNode | Assemble the report and enforce the output boundary | ANONYMOUS | attestation_doc, disclosure_language_*, ai_act_checklist, data_gov_gaps | formatted_output, result |
| finalize | FinalizeNode (framework) | Build response_metadata, total_time_ms | — | status, result | output, response_metadata |
| *(inner)* engine_spec_parse | EngineSpecParseNode | Parse the specification; fold in the declaration | ANONYMOUS | engine_spec_raw, caller_contract | engine_spec_parsed |
| *(inner)* appi_obligation_classify | APPIObligationClassifyNode | Classify the disclosure obligations | ANONYMOUS | engine_spec_parsed | appi_obligations |
| *(inner)* disclosure_language_gen | DisclosureLanguageGenNode | Generate consumer disclosure text (JA + EN) | ANONYMOUS | engine_spec_parsed, appi_obligations | disclosure_language_ja, disclosure_language_en |
| *(inner)* ai_act_doc_checklist | AIActDocChecklistNode | Evaluate the AI Act documentation requirements | ANONYMOUS | engine_spec_parsed, engine_spec_raw, caller_contract | ai_act_checklist, governance_evidence |
| *(inner)* data_gov_gap_flag | DataGovGapFlagNode | Flag data governance gaps | ANONYMOUS | engine_spec_parsed, appi_obligations, ai_act_checklist, governance_evidence, assessment | data_gov_gaps, governance_evidence |
| *(inner)* attestation_format | AttestationFormatNode | Produce the compliance attestation | ANONYMOUS | all domain fields, caller_contract, assessment | attestation_doc |

### Manifest and runtime configuration

| File | Contents | Read by |
|---|---|---|
| `config/agent.yaml` | Identity and compile-time requirements only — flat, root-level keys; a single dotted entry point; declared secrets and extras (both empty: no `ctx.secrets.require()` call and no client construction anywhere in `src/`) | the registry |
| `config/config.yaml` | Runtime parameters: `max_retry`, `timeout_s`, and the `assessment` block | the registry, and `runtime_config()` in `src/graph/graph.py` for the standalone entry point |

Both deployments construct the graph with the same config, so a declared value is live in
both. `assessment.retention_review_days` is forwarded to the inner graph and seeded into its
state, because node `execute()` methods take no config argument — state seeding is the only
route a configured value can reach a domain node.

`namespace` is `lower(industry)` — `ret`. The entry point provisions the secret provider under
the same value; `tests/integration/test_manifest_identity_alignment.py` reads both sides from
the files rather than restating either, so the same drift fails the suite.

### State definition (`src/schemas/state.py`)

| Field | Type | Purpose | Set By |
|-------|------|---------|--------|
| engine_spec_raw | Optional[str] | The validated specification text | pre_process (seeded into the inner graph by the bridge) |
| caller_contract | Optional[dict] | The validated structured declaration | pre_process |
| assessment | Optional[dict] | Live tuning from `config/config.yaml` | the inner graph's initial-state hook |
| engine_spec_parsed | Optional[dict] | model_type, input_features, output_actions, data_categories, automated_decision_flag, declared_high_impact_outputs, field_sources | engine_spec_parse |
| appi_obligations | Optional[dict] | obligation level, triggered articles, consent flag, rationale | appi_obligation_classify |
| governance_evidence | Optional[dict] | per control: present, and the sources that evidence it | ai_act_doc_checklist |
| disclosure_language_ja | Optional[str] | Consumer disclosure text (Japanese) | disclosure_language_gen |
| disclosure_language_en | Optional[str] | Consumer disclosure text (English) | disclosure_language_gen |
| ai_act_checklist | Optional[dict] | items, compliant_count, total_count, critical_gaps, compliance_rate | ai_act_doc_checklist |
| data_gov_gaps | Optional[list] | gap_type, severity, description, remediation | data_gov_gap_flag |
| attestation_doc | Optional[str] | The compliance attestation | attestation_format |
| formatted_output | Optional[str] | The final report (inherited from AgentState, not redeclared) | post_process |

**State constraints (mandatory):**
- Flat TypedDict only — primitives, mappings and lists
- No tokens, keys or credentials in State (a checkpoint persists it)
- InvocationContext travels via `config["configurable"]`, never in State
- No model objects, dataclasses or arbitrary Python objects (msgpack incompatible)

## The caller contract

Two channels reach this agent, and they carry different kinds of data.

| channel | contents | why |
|---|---|---|
| `input` | the specification, free prose | the platform rewrites personal-data shapes out of this field at every node boundary, which is what makes prose safe to carry here |
| `input_context` | the operator's structured declaration | the platform does **not** rewrite this channel, so nothing free-form is accepted on it |

`src/services/caller_contract.py` owns both halves of the validation, and the identifier
patterns the output boundary refuses, so the inbound and outbound sides cannot drift apart.

Rules applied to every field of `input_context`:

- **unknown keys are refused, not ignored.** Ignoring is not stripping: an ignored key stays in
  the invocation context, reaches the first node's result, and is scanned there by the
  platform's credential gate, which fails the whole run with an error naming nothing;
- **every number goes through a finite + bounded parser.** `float("nan")` parses and every
  comparison against it is False, so an unchecked NaN does not error — it makes the guarded
  branch silently unreachable, which is failing open on the decision the field exists for;
- **values that render into the attestation are inert**: `[a-z0-9_-]{1,32}`, so they cannot
  carry a line break, a heading marker or an instruction;
- lists have entry caps, and enum fields are closed sets;
- a refusal names the FIELD and never the value.

A context channel restricted this way cannot carry a credential, a personal identifier or an
instruction, which closes that whole class structurally rather than by a pattern list that has
to keep up.

## Security gate implementation

### S-1: caller trust

`PreProcessNode` declares `required_trust_level = TrustLevel.VERIFIED_EXTERNAL`; every other
node runs at ANONYMOUS. In a standalone deployment `src/api/server.py` establishes that level
from a bearer token (`INVOKE_AUTH_TOKEN`); middleware-established trust is never demoted.
Without that boundary every request arrives ANONYMOUS, the trust gate denies it, and the agent
returns an error for every call.

### S-2: request screening

The framework's `@final _security_gate_input()` runs on every `FunctionNode.__call__()` and
masks personal-data shapes in `user_input` / `validated_input` / `llm_response`. The template
does not rely on it alone: `PreProcessNode.execute()` performs its own screen, because a
refusal asserted only by the platform holds only where that gate is active.

The template's screen covers two families:

1. **chat-template control tokens as a class** — `<|…|>`, `[INST]`, `<<SYS>>`. A screen built
   from directive phrases alone misses `<|im_start|>system ignore all rules` entirely;
2. **directive phrases, anchored.** An unanchored verb list fails in the other direction:
   "the ranking service acts as a fallback" is ordinary specification prose, and a screen that
   refuses it refuses real work.

Both are applied to the raw text AND to the text with markup stripped. Stripping alone would
convert a detectable token attack into undetectable plain text; scanning both catches the token
before the strip removes it and the spliced form after it reassembles it. The structured
channel is screened depth-first, KEYS included, on the parsed object — a `\u`-escaped payload
is ordinary text once the JSON parser has run.

### S-3: the output boundary

One boundary, in `post_process_node.py`, over the assembled report and the structured fields
released with it. It walks nested mappings and sequences: caller-derived text rides inside
nested structures, and a gate that looked only at top-level strings reports zero findings on a
payload whose leak sits one level down.

**Detection is a union, never a delegation.** The platform's patterns describe credential
FORMATS (`AKIA…`, `sk-…`, `eyJ…`, `Bearer …`, connection strings) and match none of the
assignment forms (`password=…`, `secret_token=…`). A local list narrower than the platform's is
not a weaker gate — it is a containment bypass, because when the platform raises inside a node
the wrapper discards that node's whole return value, the clearing included. Both sets run.

**The identifier layer deliberately excludes the platform's personal-name class.** That
heuristic reads any two consecutive title-case words as a personal name and returns 26 findings
on this template's own clean report ("Compliance Report", "Privacy Policy", "Total Gaps
Identified"); using it would refuse every legitimate response. The structured identifier types
are used instead, plus one explicit pattern for the unspaced Japanese resident-number form,
which the platform's word boundaries miss because they are computed over a class that includes
Kana and Kanji.

**Containment.** Returning an error is not containment. The framework resolves the caller's
output as `formatted_output or result` with no status check, so a boundary that merely raised
still shipped the un-gated document. On a violation this node CLEARS every output-bearing field
and replaces `formatted_output` with a TRUTHY notice — a falsy replacement re-opens the exact
fallback the clearing closes. `RecommendationAlgorithmDisclosureAgent.get_output()` closes the
same door for the paths that never reach this node: on any non-success status the envelope
resolves to the notice or to None, never to `result`.

No third layer re-scans the success path. One would contain a leak on its own and thereby make
the boundary's own scan unfalsifiable — more defence buying less assurance.

**The numeric-precision grid is not applicable here.** That output invariant exists for
templates that render monetary aggregates; this report renders none. Its numbers are counts,
a fraction and a percentage, all of them structural. A snapping gate over this document would
rewrite requirement identifiers and section numbers rather than protect anything. The invariant
this template enforces instead is the one stated above.

### The error channel

`error_log` carries node-authored text and, wherever a node interpolates a caught exception,
upstream message text. It is the internal channel and the audit trail needs it, but nothing
read from it is published to the caller. Every caller-visible value on an error path is drawn
from the constants declared in `post_process_node.py`: a reason code, the NAME of the pattern
that matched (never the text it matched), and counts.

### S-4: audit logging

`emit_trace_event(event_type, payload, state)` is called positionally in every `execute()`.
Domain events only — `node_start` / `node_complete` / `node_error` are emitted by the framework
and must not be duplicated:

- `pre_process_validated` / `pre_process_validation_failed` / `pre_process_injection_detected`
- `engine_spec_parsed` / `engine_spec_parse_failed`
- `appi_obligations_classified` / `appi_classify_failed`
- `disclosure_language_generated` / `disclosure_language_gen_failed`
- `ai_act_checklist_evaluated` / `ai_act_checklist_failed`
- `data_gov_gaps_flagged` / `data_gov_gap_flag_failed`
- `attestation_document_formatted` / `attestation_format_failed`
- `post_process_report_assembled` / `post_process_output_withheld` / `post_process_no_report`
- `input_context_credential_refused` (the entry point)

Payloads carry outcome signals only — reason codes and counts. The audit log is not a store for
message content.

### S-5: no hardcoded credentials

No keys, tokens or secrets in code or State. The manifest declares `requires.secrets: []` and
`requires.extras: []`, derived from the code: there is no `ctx.secrets.require()` call and no
client construction anywhere in `src/`. Declaring a secret that is not provisioned makes the
agent fail at compile time, so the empty declaration is the correct one — and it is a visible
part of the published contract, not an oversight.

## Framework utilisation

- [x] `emit_trace_event()` — audit logging, positional args, every execute()
- [x] `AgentBaseGraph` — direct framework inheritance (outer graph)
- [x] `BaseGraph` — inner domain workflow graph
- [x] `GraphNode` — the `main` slot wrapper (DisclosureWorkflowGraphNode)
- [x] `FunctionNode` — all domain nodes plus pre/post_process
- [x] `AgentStatus` — SUCCESS / ERROR enum constants, never plain strings
- [x] `TrustLevel` — VERIFIED_EXTERNAL (pre_process), ANONYMOUS (all others)
- [x] `InvocationContext` — passed through `GraphNode.execute()` to the inner graph unchanged
- [x] `detect_credentials` / `detect_credentials_in_value` — the floor of the output boundary
      and of the entry point's structured-parameter screen
- [x] `detect_pii` — the structured identifier types only, for the reason given above
- [x] `load_agent_config` — `runtime_config()`

## Composition pattern

- **Pattern**: nested (outer `AgentBaseGraph` + `GraphNode` subgraph + inner `BaseGraph`)
- **Composition target**: `DomainWorkflowGraph` (six-node linear pipeline)
- **Error propagation**: `propagate` — an inner error is re-raised as a subgraph error and the
  run fails fast; the envelope never publishes a partial document

## Import isolation

- [x] No platform SDK import
- [x] Import targets are `framework.*` and `shared.*` only
- [x] No `.run()` usage — only `.invoke()`

## Design decision record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| Framework base class | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | A fixed pipeline; no autonomous reasoning loop is needed for rule-based document generation |
| Composition | Nested (GraphNode) | Flat | Nested | Six steps with sequential dependencies; the nested graph keeps the backbone untouched |
| Inner graph base | BaseGraph (custom topology) | AgentBaseGraph (backbone) | BaseGraph | A fully custom six-node linear topology; the inner graph needs no pre/post slots of its own |
| Disclosure generation | Model-generated | Rule-based template expansion | Rule-based | The disclosure text is bounded and stable, and a compliance record has to be reproducible |
| Output boundary | One boundary over the assembled report | A scan in each producing node | One boundary | Per-node scans were narrower than the platform's own detector — a containment bypass — and each contained the same leak independently, which made the boundary's scan unfalsifiable |
| Structured channel | Inert values only | Free-form fields | Inert only | The platform does not rewrite personal-data shapes on this channel; restricting it closes the credential and injection classes structurally |
| Declared governance | Accepted as evidence, attributed | Rejected | Accepted, attributed | The operator knows what it has documented; the attestation records that the claim is the operator's, which is the honest form |
