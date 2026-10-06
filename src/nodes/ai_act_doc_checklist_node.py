"""AgentCore Platform v1.0"""

# AIActDocChecklistNode — inner domain node (ANONYMOUS trust level).
# Evaluates Japan AI Act (Act on Promotion of Development and Utilization
# of Artificial Intelligence, enacted May 28 2025; operationalised 2026)
# documentation requirements against the parsed engine specification.
#
# Checklist covers the 2026 operational guidance requirements for AI systems
# used in consumer-facing services (Tier-1 high-impact deployment scope).
#
# Evidence for the four narrative requirements (oversight, metrics, risk,
# audit) comes from the shared evidence service, not from a private keyword
# scan in this file. When this node derived its own signals it read a state key
# the inner graph never receives, so those four requirements reported "not
# documented" for EVERY specification — a specification that described human
# review, precision benchmarks, bias monitoring and an annual third-party audit
# produced a byte-identical checklist to one that described none of them.

from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.service import EVIDENCE_SERVICE

# ── AI Act documentation requirement definitions ──────────────────────────────
# Each entry: (id, description, critical flag, the signal key that evidences it)

_REQUIREMENTS: List[Dict[str, Any]] = [
    {
        "id": "AIA-DOC-01",
        "description": "System purpose and intended use documented",
        "critical": True,
        "check_key": "has_model_type",
    },
    {
        "id": "AIA-DOC-02",
        "description": "Input data types and sources documented",
        "critical": True,
        "check_key": "has_input_features",
    },
    {
        "id": "AIA-DOC-03",
        "description": "Output actions and scope of decisions documented",
        "critical": True,
        "check_key": "has_output_actions",
    },
    {
        "id": "AIA-DOC-04",
        "description": "Automated decision-making scope and impact level stated",
        "critical": True,
        "check_key": "has_automated_decision_statement",
    },
    {
        "id": "AIA-DOC-05",
        "description": "Training data categories and provenance documented",
        "critical": False,
        "check_key": "has_data_categories",
    },
    {
        "id": "AIA-DOC-06",
        "description": "Human oversight mechanism described",
        "critical": False,
        "check_key": "human_oversight",
    },
    {
        "id": "AIA-DOC-07",
        "description": "Performance metrics and accuracy benchmarks documented",
        "critical": False,
        "check_key": "performance_metrics",
    },
    {
        "id": "AIA-DOC-08",
        "description": "Risk mitigation measures described",
        "critical": True,
        "check_key": "risk_mitigation",
    },
    {
        "id": "AIA-DOC-09",
        "description": "Audit trail and monitoring plan documented",
        "critical": False,
        "check_key": "audit_plan",
    },
    {
        "id": "AIA-DOC-10",
        "description": "Disclosure language prepared for consumers",
        "critical": True,
        "check_key": "has_disclosure_language",
    },
]

# How each source label reads in the checklist notes.
_SOURCE_LABEL = {
    "specification": "evidenced in the specification",
    "declared": "declared by the operator",
}


def _spec_signals(spec: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, List[str]]:
    """Evidence sources for the requirements derived from the parsed spec."""
    field_sources = spec.get("field_sources") or {}
    signals: Dict[str, List[str]] = {}

    def record(key: str, present: bool, source: str) -> None:
        signals[key] = [source] if present else []

    record(
        "has_model_type",
        spec.get("model_type", "unspecified") != "unspecified",
        field_sources.get("model_type", "specification"),
    )
    record("has_input_features", bool(spec.get("input_features")), "specification")
    record(
        "has_output_actions",
        bool(spec.get("output_actions") or spec.get("declared_high_impact_outputs")),
        "declared" if spec.get("declared_high_impact_outputs") else "specification",
    )
    # The parsed spec ALWAYS carries an automated_decision_flag, so its mere
    # presence evidences nothing — reading it that way is how this requirement
    # used to pass unconditionally. It counts as documented only when the
    # operator declared the scope explicitly, or the specification actually says
    # something about it (either an automated-decision statement or a described
    # human-review step).
    oversight_evidenced = bool(
        EVIDENCE_SERVICE.evidence(
            str(state.get("engine_spec_raw") or ""), (state.get("caller_contract") or {}).get("governance")
        )["human_oversight"]["present"]
    )
    declared_scope = field_sources.get("automated_decision_flag") == "declared"
    record(
        "has_automated_decision_statement",
        declared_scope or bool(spec.get("automated_decision_flag")) or oversight_evidenced,
        "declared" if declared_scope else "specification",
    )
    record(
        "has_data_categories",
        bool(spec.get("data_categories")),
        field_sources.get("data_categories", "specification"),
    )
    record(
        "has_disclosure_language",
        bool(state.get("disclosure_language_ja") or state.get("disclosure_language_en")),
        "specification",
    )
    return signals


class AIActDocChecklistNode(FunctionNode):
    """Evaluate Japan AI Act (2025/2026) documentation requirements.

    Reads engine_spec_parsed, caller_contract and the disclosure language fields
    to produce ai_act_checklist:
      items: list of {id, description, status (met/gap), critical, sources, notes}
      compliant_count, total_count, critical_gaps, compliance_rate.

    Also publishes governance_evidence, so the gap analysis and the attestation
    read the same derivation rather than each re-deriving it.

    Trust level ANONYMOUS: inner domain node.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        spec: Dict[str, Any] = state.get("engine_spec_parsed") or {}

        if not spec:
            emit_trace_event(
                "ai_act_checklist_failed",
                {"reason": "missing_engine_spec_parsed"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["AIActDocChecklistNode: engine_spec_parsed is missing"],
            }

        specification = str(state.get("engine_spec_raw") or state.get("validated_input") or "")
        declared_governance = (state.get("caller_contract") or {}).get("governance")
        evidence = EVIDENCE_SERVICE.evidence(specification, declared_governance)
        spec_signals = _spec_signals(spec, state)

        items: List[Dict[str, Any]] = []
        critical_gaps: List[str] = []

        for req in _REQUIREMENTS:
            key = str(req["check_key"])
            if key in spec_signals:
                sources = spec_signals[key]
            else:
                sources = list(evidence.get(key, {}).get("sources", []))
            is_met = bool(sources)
            status = "met" if is_met else "gap"

            if is_met:
                notes = "; ".join(_SOURCE_LABEL.get(s, s) for s in sources)
            else:
                notes = "not found in the specification and not declared"
                if req["critical"]:
                    critical_gaps.append(str(req["id"]))

            items.append(
                {
                    "id": req["id"],
                    "description": req["description"],
                    "status": status,
                    "critical": req["critical"],
                    "sources": sources,
                    "notes": notes,
                }
            )

        compliant_count = sum(1 for item in items if item["status"] == "met")
        total_count = len(items)

        checklist = {
            "items": items,
            "compliant_count": compliant_count,
            "total_count": total_count,
            "critical_gaps": critical_gaps,
            "compliance_rate": round(compliant_count / total_count, 2) if total_count else 0.0,
        }

        emit_trace_event(
            "ai_act_checklist_evaluated",
            {
                "compliant_count": compliant_count,
                "total_count": total_count,
                "critical_gap_count": len(critical_gaps),
                "compliance_rate": checklist["compliance_rate"],
            },
            state,
        )

        return {
            "ai_act_checklist": checklist,
            "governance_evidence": evidence,
            "status": AgentStatus.SUCCESS,
        }
