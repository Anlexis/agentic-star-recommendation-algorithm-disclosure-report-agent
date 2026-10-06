"""AgentCore Platform v1.0"""

# APPIObligationClassifyNode — inner domain node (ANONYMOUS trust level).
# Classifies APPI (Act on the Protection of Personal Information) 2026
# disclosure obligations based on the parsed engine specification.
#
# APPI Cabinet bill enacted April 7 2026 (effective July 6 2026):
#  - Article 24-bis: disclosure obligation for recommendation algorithm
#    operators who use personal information as input features.
#  - Article 26-ter: consent requirement for automated decisions with
#    significant impact (pricing, credit, employment).
#  - Article 28: data subject rights (access, correction, deletion).
#
# Obligation levels:
#  - "full"    : personal data as features + automated high-impact decisions
#  - "partial" : personal data as features OR automated decisions (not both)
#  - "none"    : no personal data features, no automated decisions

from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_PERSONAL_DATA_CATEGORIES = {
    "personal_information",
    "demographic",
    "browsing_behavior",
    "purchase_history",
    "behavioral_signals",
}

_HIGH_IMPACT_OUTPUT_KEYWORDS = [
    "price",
    "pricing",
    "credit",
    "loan",
    "employment",
    "hire",
    "reject",
    "block",
    "ban",
    "suspend",
    "restrict access",
]

# How many characters of operator prose the rationale may quote back in total.
# The rationale is rendered into the attestation document, so an unbounded quote
# would let one long sentence dominate a compliance record.
_RATIONALE_EVIDENCE_CHARS = 160


def _uses_personal_data(spec: Dict[str, Any]) -> bool:
    """True if spec data_categories overlap with APPI personal data set."""
    categories = set(spec.get("data_categories", []))
    return bool(categories & _PERSONAL_DATA_CATEGORIES)


def _has_high_impact_output(spec: Dict[str, Any]) -> bool:
    """True if the outputs include high-impact decisions.

    An explicit declaration decides on its own; otherwise the described output
    actions are read for the keyword set.
    """
    if spec.get("declared_high_impact_outputs"):
        return True
    actions_text = " ".join(spec.get("output_actions", [])).lower()
    return any(kw in actions_text for kw in _HIGH_IMPACT_OUTPUT_KEYWORDS)


def _determine_obligation_level(uses_personal: bool, automated: bool, high_impact: bool) -> str:
    """Determine APPI obligation level from three Boolean flags."""
    if uses_personal and automated and high_impact:
        return "full"
    if uses_personal or (automated and high_impact):
        return "partial"
    return "none"


def _build_triggered_articles(uses_personal: bool, automated: bool, high_impact: bool) -> List[str]:
    """Build the list of APPI articles that are triggered."""
    articles: List[str] = []
    if uses_personal:
        articles.append("Art.24-bis (algorithm disclosure — personal data features)")
        articles.append("Art.28 (data subject rights — access/correction/deletion)")
    if automated and high_impact:
        articles.append("Art.26-ter (consent — automated high-impact decisions)")
    # Art.24 (third-party provision disclosure) is triggered only when the spec
    # explicitly references third-party data providers; flagged separately in
    # DataGovGapFlagNode for the governance gap analysis.
    return articles


def _high_impact_evidence(spec: Dict[str, Any]) -> str:
    """Describe the high-impact evidence, preferring the inert declared codes.

    Declared codes come from a closed set, so they render as themselves. Prose
    evidence is operator text and is bounded before it reaches a rendered line.
    """
    declared = spec.get("declared_high_impact_outputs") or []
    if declared:
        return ", ".join(str(code) for code in declared)
    quoted = ", ".join(spec.get("output_actions", [])[:3])
    return quoted[:_RATIONALE_EVIDENCE_CHARS]


class APPIObligationClassifyNode(FunctionNode):
    """Classify APPI 2026 disclosure obligations from the parsed engine spec.

    Reads engine_spec_parsed from state and produces appi_obligations dict:
      obligation_level, triggered_articles, disclosure_required,
      consent_required, rationale.

    Trust level ANONYMOUS: inner domain node; caller is authenticated upstream.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        spec: Dict[str, Any] = state.get("engine_spec_parsed") or {}

        if not spec:
            emit_trace_event(
                "appi_classify_failed",
                {"reason": "missing_engine_spec_parsed"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["APPIObligationClassifyNode: engine_spec_parsed is missing"],
            }

        uses_personal = _uses_personal_data(spec)
        automated = bool(spec.get("automated_decision_flag", False))
        high_impact = _has_high_impact_output(spec)

        obligation_level = _determine_obligation_level(uses_personal, automated, high_impact)
        triggered_articles = _build_triggered_articles(uses_personal, automated, high_impact)
        disclosure_required = obligation_level in ("full", "partial")
        consent_required = automated and high_impact and uses_personal

        rationale_parts: List[str] = []
        if uses_personal:
            rationale_parts.append(
                "Specification references personal data categories " f"({', '.join(spec.get('data_categories', []))})"
            )
        if automated:
            rationale_parts.append("Automated decision-making is indicated")
        if high_impact:
            rationale_parts.append(f"Output actions suggest high-impact decisions ({_high_impact_evidence(spec)})")
        if not rationale_parts:
            rationale_parts.append("No personal data features and no automated high-impact decisions detected")
        rationale = "; ".join(rationale_parts) + "."

        obligations = {
            "obligation_level": obligation_level,
            "triggered_articles": triggered_articles,
            "disclosure_required": disclosure_required,
            "consent_required": consent_required,
            "uses_personal_data": uses_personal,
            "automated_decision_flag": automated,
            "high_impact_output_flag": high_impact,
            "rationale": rationale,
        }

        emit_trace_event(
            "appi_obligations_classified",
            {
                "obligation_level": obligation_level,
                "disclosure_required": disclosure_required,
                "consent_required": consent_required,
                "triggered_article_count": len(triggered_articles),
            },
            state,
        )

        return {
            "appi_obligations": obligations,
            "status": AgentStatus.SUCCESS,
        }
