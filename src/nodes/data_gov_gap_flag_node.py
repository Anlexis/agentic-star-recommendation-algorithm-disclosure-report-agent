"""AgentCore Platform v1.0"""

# DataGovGapFlagNode — inner domain node (ANONYMOUS trust level).
# Flags data governance gaps in the recommendation engine specification
# based on the parsed engine spec, APPI obligations, the AI Act checklist and
# the shared governance evidence.
#
# Gap categories:
#  - data_retention:    no retention policy for personal data
#  - consent_mechanism: consent collection path unclear when required
#  - data_minimisation: spec uses personal data not strictly necessary
#  - cross_border:      spec references third-party / external data sources
#  - access_control:    no statement of who can access training data
#  - model_versioning:  no model version tracking or rollback
#  - audit_plan:        no internal or third-party audit plan
#
# Evidence comes from the shared service rather than a private keyword scan.
# When this node scanned a state key the inner graph never receives, every
# keyword-driven gap fired on every run: a specification documenting retention,
# access control, versioning and audit produced the SAME five gaps as one
# documenting none of them.

from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.service import EVIDENCE_SERVICE

_MINIMISATION_SENSITIVE = {"personal_information", "demographic"}

# The live review threshold comes from config/config.yaml ->
# assessment.retention_review_days, seeded into inner state by the inner graph's
# initial-state hook. This constant is the fallback for a deployment where the
# config file cannot be read.
#
# It is deliberately STRICTER than the shipped configuration (365 days against
# 730). A fallback set to the same number as the config is indistinguishable
# from the config never arriving: the behaviour is identical either way, so
# nothing can tell a live configuration from a dead one — which is the exact
# failure this migration exists to close, reintroduced one level down. Making
# the fallback stricter means an unreadable config flags MORE, not less, and a
# test can tell the two apart.
_RETENTION_REVIEW_THRESHOLD_DAYS = 365.0


def _evidenced(evidence: Dict[str, Any], control: str) -> bool:
    return bool(evidence.get(control, {}).get("present"))


def _flag_gaps(
    spec: Dict[str, Any],
    obligations: Dict[str, Any],
    checklist: Dict[str, Any],
    evidence: Dict[str, Any],
    retention_days: Any,
    retention_review_days: float,
) -> List[Dict[str, Any]]:
    """Return the list of flagged data governance gaps."""
    uses_personal = bool(obligations.get("uses_personal_data", False))
    consent_required = bool(obligations.get("consent_required", False))
    data_cats = set(spec.get("data_categories", []))
    third_party = "third_party" in data_cats
    gaps: List[Dict[str, Any]] = []

    # Gap 1: data retention
    if uses_personal and not _evidenced(evidence, "data_retention"):
        gaps.append(
            {
                "gap_type": "data_retention",
                "severity": "high",
                "description": (
                    "Personal data used as features but no data retention policy found in spec. "
                    "APPI Art.19 requires retention period to be documented."
                ),
                "remediation": (
                    "Add a data retention policy section: specify retention period, "
                    "deletion schedule, and data lifecycle management."
                ),
            }
        )

    # Gap 2: consent mechanism
    if consent_required and not _evidenced(evidence, "consent_mechanism"):
        gaps.append(
            {
                "gap_type": "consent_mechanism",
                "severity": "high",
                "description": (
                    "Automated high-impact decisions require prior consent (APPI Art.26-ter) "
                    "but no consent mechanism is described in the spec."
                ),
                "remediation": (
                    "Document the consent collection flow: opt-in UI, consent record storage, "
                    "withdrawal path, and how recommendations are suppressed post-withdrawal."
                ),
            }
        )

    # Gap 3: data minimisation
    if _MINIMISATION_SENSITIVE & data_cats:
        sensitive_used = sorted(_MINIMISATION_SENSITIVE & data_cats)
        gaps.append(
            {
                "gap_type": "data_minimisation",
                "severity": "medium",
                "description": (
                    f"Sensitive data categories ({', '.join(sensitive_used)}) used. "
                    "APPI Art.16 requires use limited to stated purpose."
                ),
                "remediation": (
                    "Confirm each sensitive data category is strictly necessary; "
                    "remove or anonymise fields not required for the recommendation outcome."
                ),
            }
        )

    # Gap 4: cross-border / third-party data
    if third_party:
        gaps.append(
            {
                "gap_type": "cross_border_third_party",
                "severity": "medium",
                "description": (
                    "Third-party data sources referenced. APPI Art.24 requires disclosure "
                    "when providing personal data to third parties."
                ),
                "remediation": (
                    "Document the third-party data providers, the legal basis for transfer, "
                    "and include in consumer disclosure if applicable."
                ),
            }
        )

    # Gap 5: access control
    if uses_personal and not _evidenced(evidence, "access_control"):
        gaps.append(
            {
                "gap_type": "access_control",
                "severity": "medium",
                "description": (
                    "No access control policy described for training data or model access. "
                    "Japan AI Act 2026 guidance requires access governance documentation."
                ),
                "remediation": (
                    "Document who has access to personal training data and the model, "
                    "including access roles and audit logging of access events."
                ),
            }
        )

    # Gap 6: model versioning
    if not _evidenced(evidence, "model_versioning"):
        gaps.append(
            {
                "gap_type": "model_versioning",
                "severity": "low",
                "description": (
                    "No model versioning or rollback strategy mentioned. "
                    "Japan AI Act guidance recommends version tracking for auditability."
                ),
                "remediation": (
                    "Add model registry details, version history policy, "
                    "and rollback procedure to the documentation."
                ),
            }
        )

    # Gap 7: internal or third-party audit plan
    if not _evidenced(evidence, "audit_plan"):
        gaps.append(
            {
                "gap_type": "audit_plan",
                "severity": "low",
                "description": (
                    "No internal or third-party audit plan described. "
                    "Japan AI Act 2026 guidance recommends periodic algorithm audits."
                ),
                "remediation": (
                    "Define an audit schedule (e.g., annual third-party review), "
                    "specify audit scope, and assign a responsible owner."
                ),
            }
        )

    # A declared retention period is evidence, but an excessive one is its own
    # finding: the operator has documented the control and documented that it
    # keeps personal data for longer than the purpose can justify.
    if retention_days is not None and uses_personal:
        if retention_days > retention_review_days:
            gaps.append(
                {
                    "gap_type": "retention_period_excessive",
                    "severity": "medium",
                    "description": (
                        f"Declared retention period of {retention_days:g} days exceeds the "
                        f"{retention_review_days:g}-day review threshold for personal "
                        "data used as recommendation features (APPI Art.19)."
                    ),
                    "remediation": (
                        "Justify the retention period against the stated purpose, or shorten it "
                        "and document the deletion schedule."
                    ),
                }
            )

    # A critical documentation gap on the input-data requirements raises the
    # retention finding to high severity where one was flagged.
    checklist_critical = set(checklist.get("critical_gaps", []))
    if {"AIA-DOC-02", "AIA-DOC-05"} & checklist_critical:
        for gap in gaps:
            if gap["gap_type"] == "data_retention":
                gap["severity"] = "high"

    return gaps


def _retention_review_days(state: Dict[str, Any]) -> float:
    """The live review threshold, from config/config.yaml via seeded state.

    Read here rather than at import time so a declared value actually reaches
    the decision it governs. A non-finite or non-numeric configured value falls
    back to the module constant instead of poisoning the comparison: every
    comparison against NaN is False, so an unchecked one would silently disable
    the finding rather than raise.
    """
    configured = (state.get("assessment") or {}).get("retention_review_days")
    if isinstance(configured, bool) or not isinstance(configured, (int, float)):
        return _RETENTION_REVIEW_THRESHOLD_DAYS
    value = float(configured)
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        return _RETENTION_REVIEW_THRESHOLD_DAYS
    return value


class DataGovGapFlagNode(FunctionNode):
    """Flag data governance gaps from the spec, obligations, checklist and evidence.

    Reads engine_spec_parsed, appi_obligations, ai_act_checklist,
    governance_evidence and caller_contract from state.
    Produces data_gov_gaps: list of {gap_type, severity, description, remediation}.

    Trust level ANONYMOUS: inner domain node.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        spec: Dict[str, Any] = state.get("engine_spec_parsed") or {}
        obligations: Dict[str, Any] = state.get("appi_obligations") or {}
        checklist: Dict[str, Any] = state.get("ai_act_checklist") or {}
        contract: Dict[str, Any] = state.get("caller_contract") or {}

        if not spec:
            emit_trace_event(
                "data_gov_gap_flag_failed",
                {"reason": "missing_engine_spec_parsed"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["DataGovGapFlagNode: engine_spec_parsed is missing"],
            }

        evidence = state.get("governance_evidence")
        if not isinstance(evidence, dict) or not evidence:
            # The checklist step publishes this; deriving it here as a fallback
            # keeps the node correct when it is exercised on its own.
            evidence = EVIDENCE_SERVICE.evidence(
                str(state.get("engine_spec_raw") or state.get("validated_input") or ""),
                contract.get("governance"),
            )

        retention_days = EVIDENCE_SERVICE.retention_days(contract.get("governance"))
        review_days = _retention_review_days(state)
        gaps = _flag_gaps(spec, obligations, checklist, evidence, retention_days, review_days)

        high_count = sum(1 for g in gaps if g["severity"] == "high")
        medium_count = sum(1 for g in gaps if g["severity"] == "medium")
        low_count = sum(1 for g in gaps if g["severity"] == "low")

        emit_trace_event(
            "data_gov_gaps_flagged",
            {
                "total_gaps": len(gaps),
                "high_severity": high_count,
                "medium_severity": medium_count,
                "low_severity": low_count,
                "retention_review_days": review_days,
            },
            state,
        )

        return {
            "data_gov_gaps": gaps,
            "governance_evidence": evidence,
            "status": AgentStatus.SUCCESS,
        }
