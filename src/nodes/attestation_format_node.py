"""AgentCore Platform v1.0"""

# AttestationFormatNode — inner domain node (ANONYMOUS trust level).
# Produces the final compliance attestation document by aggregating:
#  - APPI obligation classification result
#  - Japan AI Act documentation checklist result
#  - Data governance gap flags
#  - Disclosure language status
#
# The attestation document is a structured text artifact suitable for
# submission to a regulator or a legal team as evidence of a compliance review.
#
# Every evidence line names its SOURCE — the specification's own wording, or the
# operator's declaration. A declaration is an assertion by the operator, not a
# verification by this agent, and a compliance record that cannot tell the two
# apart is not evidence of anything.

from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Tuple

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Fallbacks for the two ceilings; the live values come from
# config/config.yaml -> assessment, seeded into inner state.
_HIGH_SEVERITY_GAP_CEILING = 0
_CRITICAL_GAP_CEILING = 0


def _ceiling(state: Dict[str, Any], key: str, fallback: int) -> int:
    """Read an integer ceiling from the seeded assessment config."""
    configured = (state.get("assessment") or {}).get(key)
    if isinstance(configured, bool) or not isinstance(configured, int) or configured < 0:
        return fallback
    return configured


def _overall_status(
    obligations: Dict[str, Any],
    checklist: Dict[str, Any],
    gaps: List[Dict[str, Any]],
    high_severity_ceiling: int,
    critical_ceiling: int,
) -> Tuple[str, str]:
    """Return (status_code, status_label) for the attestation cover.

    status_code: COMPLIANT | REQUIRES_ACTION | NON_COMPLIANT
    """
    high_gaps = [g for g in gaps if g.get("severity") == "high"]
    critical_checklist_gaps = checklist.get("critical_gaps", [])
    obligation_level = obligations.get("obligation_level", "none")
    disclosure_required = obligations.get("disclosure_required", False)

    over_high = len(high_gaps) > high_severity_ceiling
    over_critical = disclosure_required and len(critical_checklist_gaps) > critical_ceiling
    if over_high or over_critical:
        return "NON_COMPLIANT", "Non-Compliant — Immediate Action Required"
    if gaps or critical_checklist_gaps or obligation_level in ("partial", "full"):
        return "REQUIRES_ACTION", "Partially Compliant — Action Required"
    return "COMPLIANT", "Compliant"


def _reference_line(contract: Dict[str, Any]) -> List[str]:
    """Render the operator's own references, when supplied.

    Both values passed the inert-identifier check at the request boundary
    (`[a-z0-9_-]{1,32}`), which is what makes them safe to render verbatim into
    a document: they cannot carry a line break, a heading marker or an
    instruction.
    """
    lines: List[str] = []
    if contract.get("operator_ref"):
        lines.append(f"Operator Reference:     {contract['operator_ref']}")
    if contract.get("assessment_ref"):
        lines.append(f"Assessment Reference:   {contract['assessment_ref']}")
    return lines


def _evidence_lines(checklist: Dict[str, Any]) -> List[str]:
    """One line per checklist requirement, carrying its status and its source."""
    lines: List[str] = []
    for item in checklist.get("items", []):
        mark = "MET" if item.get("status") == "met" else "GAP"
        lines.append(f"  [{mark}] {item.get('id')}  {item.get('description')}")
        lines.append(f"        {item.get('notes', '')}")
    return lines


def _format_attestation(
    spec: Dict[str, Any],
    obligations: Dict[str, Any],
    checklist: Dict[str, Any],
    gaps: List[Dict[str, Any]],
    contract: Dict[str, Any],
    has_disclosure: bool,
    status_code: str,
    status_label: str,
) -> str:
    """Build the full attestation document text."""
    today = datetime.now(timezone.utc).date().isoformat()
    model_type = spec.get("model_type", "unspecified")
    obligation_level = obligations.get("obligation_level", "none")
    triggered_articles = obligations.get("triggered_articles", [])
    consent_required = obligations.get("consent_required", False)
    compliant = checklist.get("compliant_count", 0)
    total = checklist.get("total_count", 0)
    critical_checklist_gaps = checklist.get("critical_gaps", [])

    high_gaps = [g for g in gaps if g.get("severity") == "high"]
    medium_gaps = [g for g in gaps if g.get("severity") == "medium"]
    low_gaps = [g for g in gaps if g.get("severity") == "low"]

    lines: List[str] = [
        "=" * 72,
        "AI RECOMMENDATION ALGORITHM COMPLIANCE ATTESTATION",
        "APPI 2026 (Art. 24-bis) + Japan AI Act (enacted 2025, operationalised 2026)",
        "=" * 72,
        "",
        f"Date of Assessment:     {today}",
    ]
    lines += _reference_line(contract)
    lines += [
        f"Algorithm Type:         {model_type}",
        f"APPI Obligation Level:  {obligation_level.upper()}",
        f"Overall Status:         {status_label}",
        "",
        "-" * 72,
        "SECTION 1: APPI 2026 OBLIGATION ASSESSMENT",
        "-" * 72,
        f"Disclosure Required:    {'Yes' if obligations.get('disclosure_required') else 'No'}",
        f"Consent Required:       {'Yes' if consent_required else 'No'}",
        "",
    ]

    if triggered_articles:
        lines.append("Triggered Articles:")
        for art in triggered_articles:
            lines.append(f"  - {art}")
        lines.append("")

    lines.append(f"Rationale: {obligations.get('rationale', 'N/A')}")
    lines += [
        "",
        "-" * 72,
        "SECTION 2: JAPAN AI ACT DOCUMENTATION CHECKLIST",
        "-" * 72,
        f"Requirements Met:       {compliant}/{total}",
        f"Compliance Rate:        {checklist.get('compliance_rate', 0.0):.0%}",
        "",
        "Evidence source is stated per requirement. 'declared by the operator'",
        "records an assertion made in the request; it is not verified here.",
        "",
    ]
    lines += _evidence_lines(checklist)

    if critical_checklist_gaps:
        lines.append("")
        lines.append("Critical Documentation Gaps (must remediate before deployment):")
        for gap_id in critical_checklist_gaps:
            lines.append(f"  - {gap_id}")

    lines += [
        "",
        "-" * 72,
        "SECTION 3: DATA GOVERNANCE GAP ANALYSIS",
        "-" * 72,
        f"Total Gaps Identified:  {len(gaps)}",
        f"  High severity:        {len(high_gaps)}",
        f"  Medium severity:      {len(medium_gaps)}",
        f"  Low severity:         {len(low_gaps)}",
    ]

    if high_gaps:
        lines += ["", "High-Severity Gaps (immediate action required):"]
        for gap in high_gaps:
            lines.append(f"  [{gap['gap_type']}] {gap['description']}")
            lines.append(f"    Remediation: {gap['remediation']}")

    if medium_gaps:
        lines += ["", "Medium-Severity Gaps (action required before production):"]
        for gap in medium_gaps:
            lines.append(f"  [{gap['gap_type']}] {gap['description']}")

    lines += [
        "",
        "-" * 72,
        "SECTION 4: DISCLOSURE LANGUAGE STATUS",
        "-" * 72,
        f"Consumer Disclosure Prepared: {'Yes' if has_disclosure else 'No — See Sections 1-3'}",
        "",
        "-" * 72,
        "ATTESTATION",
        "-" * 72,
        "",
        f"Overall Compliance Status: {status_code}",
        "",
    ]

    if status_code == "COMPLIANT":
        lines += [
            "This recommendation engine specification has been assessed against APPI 2026",
            "Article 24-bis disclosure requirements and Japan AI Act (2025) documentation",
            "requirements. No critical gaps were identified.",
            "",
            "Consumer-facing disclosure language has been prepared in Japanese and English.",
        ]
    elif status_code == "REQUIRES_ACTION":
        lines += [
            "This recommendation engine specification has been assessed. Partial compliance",
            "has been identified. The operator must address the items listed above before",
            "the APPI 2026 effective date (July 6, 2026) or prior to deployment.",
        ]
    else:
        lines += [
            "NON-COMPLIANT: Critical gaps were identified that must be remediated before",
            "deployment. Proceeding without remediation may result in enforcement action",
            "under APPI 2026 or the Japan AI Act 2026 operational guidance.",
        ]

    lines += [
        "",
        "Generated by: RecommendationAlgorithmDisclosureAgent (RET-C2-342)",
        "=" * 72,
    ]

    return "\n".join(lines)


class AttestationFormatNode(FunctionNode):
    """Produce the final compliance attestation document.

    Reads engine_spec_parsed, appi_obligations, ai_act_checklist, data_gov_gaps,
    caller_contract, the seeded assessment tuning and the disclosure language
    state fields. Produces attestation_doc: structured text attestation.

    This node carries no private credential scan. The single output boundary in
    post_process_node.py scans the assembled report — a superset of this
    document — with a wider detector, and a second gate that contained the same
    leak on its own would make that one unfalsifiable.

    Trust level ANONYMOUS: inner domain node.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        spec: Dict[str, Any] = state.get("engine_spec_parsed") or {}
        obligations: Dict[str, Any] = state.get("appi_obligations") or {}
        checklist: Dict[str, Any] = state.get("ai_act_checklist") or {}
        gaps: List[Dict[str, Any]] = state.get("data_gov_gaps") or []
        contract: Dict[str, Any] = state.get("caller_contract") or {}
        has_disclosure = bool(state.get("disclosure_language_ja") or state.get("disclosure_language_en"))

        if not spec or not obligations:
            emit_trace_event(
                "attestation_format_failed",
                {"reason": "missing_spec_or_obligations"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["AttestationFormatNode: engine_spec_parsed or appi_obligations missing"],
            }

        high_ceiling = _ceiling(state, "high_severity_gap_ceiling", _HIGH_SEVERITY_GAP_CEILING)
        critical_ceiling = _ceiling(state, "critical_gap_ceiling", _CRITICAL_GAP_CEILING)
        status_code, status_label = _overall_status(obligations, checklist, gaps, high_ceiling, critical_ceiling)
        attestation_doc = _format_attestation(
            spec, obligations, checklist, gaps, contract, has_disclosure, status_code, status_label
        )

        emit_trace_event(
            "attestation_document_formatted",
            {
                "overall_status": status_code,
                "attestation_length": len(attestation_doc),
                "gap_count": len(gaps),
                "has_disclosure_language": has_disclosure,
                "high_severity_gap_ceiling": high_ceiling,
                "critical_gap_ceiling": critical_ceiling,
            },
            state,
        )

        return {
            "attestation_doc": attestation_doc,
            "status": AgentStatus.SUCCESS,
        }
