# Test Specification — RET-C2-342 RecommendationAlgorithmDisclosureAgent

## Test strategy

The suite is organised around one distinction: a test that exercises a node in isolation, and a
test that drives the agent the way a caller does.

Both are needed, and the second is the one that was missing. An earlier version of this suite
ran 51 tests in under half a second, every one of them at node level, none of them running the
agent — which is how a standalone deployment shipped unable to serve a single request, and how a
checklist shipped that returned the same verdict for every input. Every claim about caller-facing
behaviour in this document is therefore asserted through the real application.

| Layer | Location | What it proves |
|---|---|---|
| Unit | `tests/unit/` | Node contracts, the caller-contract validator, the classification rules |
| Boundary | `tests/proof_of_boundary/` | The structural invariants and the output boundary, probed both ways |
| Integration | `tests/integration/` | What a caller receives through the real ASGI application |

Coverage target: 80%+. Domain node tests patch `emit_trace_event` at the node's own module
rather than stubbing `shared.*` in `sys.modules` — the wheel ships `shared.*` and the framework
imports it at load time.

## Framework compliance

| TC-ID | Test | Expected result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | `State(AgentState)`; no model objects or dataclasses | PASS |
| TC-02 | Injection is refused by the template's own screen | `PreProcessNode.execute()` returns ERROR, called directly with no framework wrapper in front | PASS |
| TC-03 | No credential in State | CI credential scan: 0 violations | PASS |
| TC-04 | InvocationContext travels via configurable only | Not stored in State | PASS |
| TC-05 | No duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from every execute() body | PASS |
| TC-06 | The default input gate cannot be replaced | Overriding it raises `TypeError` at class definition (`tests/unit/test_framework_compliance_tc06_tc07.py`) | PASS |
| TC-07 | The default output gate cannot be replaced | Overriding it raises `TypeError` at class definition (same file) | PASS |
| TC-08 | `required_trust_level` is enforced | An ANONYMOUS caller is denied at the VERIFIED_EXTERNAL request boundary | PASS |
| TC-11 | At least one domain `emit_trace_event()` per execute() | All nodes emit, positional args only; CI audit-trace gate PASS | PASS |

## Proof of boundary

| PB-ID | Boundary | Test | Expected result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | Node → audit sink | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives, mappings and lists only | No model objects in State | PASS |
| PB-3 | External service | Rule-based pipeline — no external calls | None in any domain node | PASS |
| PB-4 | Import isolation | No platform SDK import | CI gate: 0 violations | PASS |
| PB-5 | Checkpoint safety | No credential in checkpointed State | CI gate: 0 violations | PASS |
| PB-6 | Backbone invoke order | `invoke()` at VERIFIED_EXTERNAL → `node_history` = [InitializeNode, PreProcessNode, DisclosureWorkflowGraphNode, PostProcessNode, FinalizeNode] | Order verified | PASS |
| PB-7 | Human-review interrupt propagation | Not enabled for this template (`propagate_hitl = False`, no interrupt checkpoint) — the module skips with that reason rather than asserting something trivially true | SKIP (documented) | SKIP |
| PB-S1 | Trust gate | An ANONYMOUS caller is denied at the request boundary | Denial confirmed | PASS |
| PB-S3 | Output boundary, both directions (`tests/proof_of_boundary/test_output_boundary.py`) | 18 values that must never be released are refused; 15 strings drawn from the agent's own report and from ordinary specification prose survive | Both directions verified | PASS |

The second list of PB-S3 is the one that matters most in practice: a gate that refuses every
legitimate report is an outage, not a strict gate. It includes
`tokenization: sentencepiece`, which a careless credential pattern reads as an assignment.

## Business logic

### Request boundary — `tests/unit/test_caller_contract.py`

| TC-ID | Test | Input | Expected result |
|-------|------|-------|----------------|
| BL-CON-01 | Ordinary specification accepted | A realistic spec containing "acts as a", "insert into", "ignore" and "system prompt" in ordinary sentences | Accepted — the fail-closed direction |
| BL-CON-02 | Empty / whitespace-only / non-string | `""`, `"  "`, `{}` | ContractError naming `input` |
| BL-CON-03 | Oversized specification | > 40,000 characters | ContractError |
| BL-CON-04 | Control tokens refused | `<|im_start|>`, `<|endoftext|>`, `[INST]`, `<<SYS>>` | Refused as a class |
| BL-CON-05 | Directive phrases refused | "ignore previous instructions", "system prompt:", "you are now a", "reveal your system prompt" | Refused |
| BL-CON-06 | Splice caught after markup strip | `ig<b>nore</b> previous <i>instructions</i>` | Refused |
| BL-CON-07 | Keys screened, not only values | `{"<\|im_start\|>system": "ok"}` | Refused |
| BL-CON-08 | Escaped payload caught post-parse | `<\|im_start\|> …` | Refused |
| BL-CON-09 | Unknown field refused, not ignored | `{"documents": [...]}` | ContractError naming the field |
| BL-CON-10 | Hostile key name not echoed back | `{"Drop TABLE users;--": 1}` | Reported by position, never quoted |
| BL-CON-11 | Rendered references locked to an inert alphabet | `"Acme Retail"`, `"ACME"`, 33 chars, a newline | ContractError |
| BL-CON-12 | Closed-set enums | `model_type: "magic"`, an unknown data category | ContractError naming the index |
| BL-CON-13 | Entry caps | 20 data categories | ContractError |
| BL-CON-14 | Non-finite numbers | `"NaN"`, `"Infinity"`, `"-Infinity"`, raw `float("nan")`, raw `float("inf")`, a bare JSON `NaN` | ContractError — the field fails closed |
| BL-CON-15 | Booleans are not numbers | `True` for `retention_days` | ContractError (`isinstance(True, int)` is True in Python) |
| BL-CON-16 | Out-of-range magnitudes | `-1`, `36_501`, `1e9` | ContractError |
| BL-CON-17 | In-range values accepted | `0`, `90`, `"365"`, `36_500`, `1.5` | Parsed to float |
| BL-CON-18 | A rejection never repeats the value | A credential-shaped value | The value is absent from the message |

### Domain nodes — `tests/unit/test_agent.py`

| TC-ID | Test | Expected result |
|-------|------|----------------|
| BL-PRE-01…06 | Request boundary: valid spec, empty, whitespace, non-string, injection, changed-keys-only | As the contract above; only changed keys returned |
| BL-ESP-01…04 | Specification parse: model-type detection, empty spec, completeness score range | Structured spec; ERROR on empty |
| BL-APC-01…04 | Obligation classification: full / partial / none, missing spec | The stated level; ERROR on a missing spec |
| BL-DLG-01…03 | Disclosure language: full, none, missing spec | JA + EN text from the selected template; ERROR on a missing spec |
| BL-DLG-04 | A credential in a disclosure field is refused at the boundary | The single output boundary reports a violation; ordinary text does not |
| BL-AAC-01…04 | Checklist: complete spec, minimal spec, missing spec, structure | Counts move with the input; ERROR on a missing spec |
| BL-DGG-01…04 | Gap analysis: retention gap, no personal data, missing spec, gap structure | Gaps move with the evidence; ERROR on a missing spec |
| BL-ATF-01…03, 05 | Attestation: status selection, missing spec, all four sections | As stated |
| BL-ATF-04 | A credential in the attestation is refused at the boundary | Including the connection-string form the removed per-node list missed |
| BL-PPR-01 | Report assembly | Every section present |
| BL-PPR-02 | A run that produced no attestation does not report success | ERROR with a truthy notice — a report of "(not generated)" placeholders is not a successful assessment |
| BL-PPR-03 | The boundary refuses what either detector alone would miss | Platform formats AND assignment forms both refused |

### Caller-facing behaviour — `tests/integration/`

| TC-ID | Test | Expected result |
|-------|------|----------------|
| BL-E2E-01 | Health endpoint | 200, agent named |
| BL-E2E-02 | Unauthenticated caller | 401 |
| BL-E2E-03 | Wrong token | 401, and the supplied token is not echoed |
| BL-E2E-04 | Authenticated caller | 200, a real report — the regression that this suite exists for |
| BL-E2E-05 | A documented specification vs a bare one | 10/10 and one gap vs 6/10 and five gaps; the two reports differ |
| BL-E2E-06 | Every checklist requirement is reachable | No critical gap on a fully documented specification |
| BL-E2E-07 | A structured declaration reaches the inner pipeline | The result differs from the bare one; the operator references render; the source is attributed |
| BL-E2E-08 | A declared model type overrides the keyword reading | The declared type appears in both languages |
| BL-E2E-09 | A configured value reaches the decision it governs | `assessment.retention_review_days` ± 1 changes the finding |
| BL-E2E-10 | Ten refusal paths publish nothing | `status: error`, `output: None` on each |
| BL-E2E-11 | A refusal never repeats the rejected value | Absent from the response body |
| BL-E2E-12 | A credential in the structured channel | 400 naming the field, never the value |
| BL-E2E-13 | Ordinary text on the same field | 200, success — the screen does not refuse real work |
| BL-E2E-14 | Oversized structured payload | 413 |
| BL-CNT-01…06 | Containment: refusal not document, value absent, document absent, no traceback or source path, notice truthy, clean request still published | The last is the control — without it a boundary that withheld everything would pass the rest |
| BL-CNT-07…10 | Error channel: only declared constants published; a sentinel seeded into `error_log` reaches no caller field at any depth; the violation label is a pattern name; every output-bearing field is cleared | As stated |
| BL-CNT-11…12 | The envelope never falls back to `result` on a non-success status, and still surfaces the report on success | As stated |
| BL-DEP-01…04 | The committed deployment payload is valid JSON, is the suite's own fixture, is accepted by the agent, and a payload the entry contract refuses would fail the same check | As stated |

The deployment smoke step tolerates a failure, so a payload the agent refuses leaves a green
pipeline and the only record is a `status: error` nothing asserts on. BL-DEP-03 drives the
committed payload through the real application; BL-DEP-04 is its negative control.

## Test execution summary

- Unit: `tests/unit/` — node contracts, the caller contract, framework compliance
- Boundary: `tests/proof_of_boundary/` — invoke order, import isolation, state safety, the
  output boundary, the human-review stub
- Integration: `tests/integration/` — end-to-end invoke, containment, manifest identity
  alignment, the deployment payload
- 212 tests, 1 skipped (PB-7, with its reason recorded in the module)
- Verified under the framework wheel the pipeline installs, not against import shims
