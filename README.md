# Recommendation Algorithm Disclosure Report Agent

AI agent for generating recommendation algorithm disclosure and AI Act compliance reports, built with Agentic Star.

> **Category**: Cat 2 (a domain-specific pipeline for one job-to-be-done)
> **Industry**: Retail
> **Template ID**: RET-C2-342

## Overview

A retailer that personalises what its customers see has to be able to say how.
Japan's revised personal-information act adds a disclosure obligation for
operators whose recommendation algorithms take personal data as input, and the
AI Act that came into operation alongside it expects the system to be documented
before it is deployed. Both land on the same team, usually with a specification
written for engineers and a deadline written for lawyers.

This agent reads that specification and produces the four artefacts the
obligation actually needs:

* **consumer-facing disclosure language**, in Japanese and English, drawn from
  templates selected by the obligation level rather than generated freely;
* **a documentation checklist** against the AI Act's ten operational
  requirements, each marked met or gap, each carrying where its evidence came
  from;
* **a data-governance gap analysis** — retention, consent, minimisation,
  third-party transfer, access control, versioning, audit — with a remediation
  note per finding;
* **a compliance attestation** suitable for a legal team or a regulator, with an
  overall status of compliant, action-required or non-compliant.

Everything is rule-based. No model is called, so the same specification always
produces the same assessment, which is what makes the output usable as a record.

**What this agent does not do.** It assesses what the operator has *documented*.
Where the operator declares a control rather than describing it in the
specification, the attestation says so — "declared by the operator" — because a
declaration is an assertion, not a verification, and a compliance record that
cannot tell the two apart is not evidence of anything.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent fails at graph
compile / start-up preflight rather than starting in a partially working state. This is
intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Sending a request

The specification goes in `input`, as prose. Anything structured goes in
`input_context` — and only structured values are accepted there.

```json
{
  "input": "Our recommendation engine uses collaborative filtering. Input features: purchase history, browsing behaviour. Outputs: personalised product ranking. The system is fully automated with a human review escalation queue. We keep a retention policy of 90 days and run an annual third-party audit.",
  "input_context": {
    "operator_ref": "acme-retail-jp",
    "assessment_ref": "fy26-q3-001",
    "model_type": "collaborative_filtering",
    "data_categories": ["purchase_history", "browsing_behavior"],
    "automated_decision": true,
    "high_impact_outputs": ["pricing"],
    "governance": {
      "human_oversight": true,
      "audit_plan": true,
      "retention_days": 90
    }
  }
}
```

The two channels are deliberately different. The platform rewrites personal-data
shapes out of `input` at every node boundary, which is what makes it safe to
carry prose. It does not do that for `input_context`, so nothing free-form is
accepted there: `model_type`, `data_categories` and `high_impact_outputs` are
closed sets, the governance flags are booleans, `retention_days` is a finite
number in range, and `operator_ref` / `assessment_ref` — the two values that
render into the attestation — are limited to `[a-z0-9_-]{1,32}`. An unknown
field is **refused**, not ignored. A refused request names the field that failed
and never repeats the value.

Every field of `input_context` is optional. With none of it, the assessment runs
from the specification prose alone.

Standalone deployments authenticate the caller with a bearer token: set
`INVOKE_AUTH_TOKEN` on the server and send `Authorization: Bearer <token>`.
`docs/07_operation_guide.md` carries the full contract.

## Project Structure

```
src/          agent implementation (graphs, nodes, services, schemas)
tests/        unit, boundary and integration tests
config/       agent manifest and runtime parameters
deploy/       local deployment recipe and a smoke payload
docs/         design and operational documentation
```

`docs/` holds the design (`02_design.md`) and the test specification
(`03_test_spec.md`).

## Customising

1. Adjust `config/config.yaml` — the retention review threshold and the two gap
   ceilings all change the attestation's overall status.
2. The regulatory content lives in three places: the disclosure templates in
   `src/nodes/disclosure_language_gen_node.py`, the requirement list in
   `src/nodes/ai_act_doc_checklist_node.py`, and the gap rules in
   `src/nodes/data_gov_gap_flag_node.py`. Replace them with your own
   jurisdiction's.
3. Extend the accepted vocabularies in `src/services/caller_contract.py` if your
   systems classify data differently.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
