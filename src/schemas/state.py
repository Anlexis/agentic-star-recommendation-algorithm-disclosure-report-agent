"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from typing import Any, Dict, List, Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state for RecommendationAlgorithmDisclosureAgent.

    Tracks the multi-step disclosure document generation workflow:
    engine spec parse -> APPI obligation classify -> disclosure language gen
    -> Japan AI Act checklist -> data governance gap flag -> attestation format.

    All fields are JSON-serializable primitives, mappings and lists — never
    model objects. No credentials, JWT tokens or Python objects may be stored
    here. The shared fields (user_input, status, session_id, node_history,
    error_log, formatted_output, the human-review fields) are inherited from
    AgentState and are deliberately not redeclared.
    """

    # Input / parsing
    engine_spec_raw: Optional[str]
    """Validated recommendation engine specification text from the operator."""

    caller_contract: Optional[Dict[str, Any]]
    """The operator's validated structured declaration, as accepted by
    src/services/caller_contract.py. Closed-set codes, booleans, bounded finite
    numbers and inert identifiers only — never free text."""

    assessment: Optional[Dict[str, Any]]
    """Runtime assessment tuning, republished from config/config.yaml by the
    inner graph's initial-state hook (node execute() takes no config argument)."""

    engine_spec_parsed: Optional[Dict[str, Any]]
    """Structured parsed spec: model_type, input_features, output_actions,
    data_categories, automated_decision_flag, declared_high_impact_outputs,
    field_sources, spec_completeness_score."""

    # APPI 2026 obligation classification
    appi_obligations: Optional[Dict[str, Any]]
    """Classified APPI disclosure obligations.
    Keys: obligation_level (none/partial/full), triggered_articles (list[str]),
    disclosure_required (bool), consent_required (bool), rationale (str)."""

    # Evidence derivation shared by the checklist, the gap analysis and the
    # attestation, so the three cannot disagree about what was documented.
    governance_evidence: Optional[Dict[str, Any]]
    """Per control: {"present": bool, "sources": ["specification"|"declared"]}."""

    # Disclosure language generation
    disclosure_language_ja: Optional[str]
    """Consumer-facing disclosure text in Japanese (APPI + AI Act compliant)."""

    disclosure_language_en: Optional[str]
    """Consumer-facing disclosure text in English (APPI + AI Act compliant)."""

    # Japan AI Act documentation checklist
    ai_act_checklist: Optional[Dict[str, Any]]
    """Japan AI Act (2025) documentation checklist.
    Keys: items (list of {id, description, status, critical, sources, notes}),
    compliant_count (int), total_count (int), critical_gaps (list[str]),
    compliance_rate (float)."""

    # Data governance gap flags
    data_gov_gaps: Optional[List[Dict[str, Any]]]
    """Flagged data governance gaps.
    Each entry: {gap_type, severity (high/medium/low), description, remediation}."""

    # Attestation document
    attestation_doc: Optional[str]
    """Compliance attestation document text (combined APPI + AI Act assessment)."""
