"""AgentCore Platform v1.0"""

# RET-C2-342 — PostProcessNode: the single output boundary of this agent.
#
# The stated output invariant: nothing credential-shaped and no direct personal
# identifier leaves this agent, and when the boundary refuses, the caller
# receives a refusal rather than the document that failed it.
#
# ── Why the scan is here and nowhere else ────────────────────────────────────
#
# Three inner nodes used to carry their own five-token credential list. All
# three were removed and the check moved here, to the assembled report — a
# superset of every field they covered — with a strictly wider detector. Two
# reasons:
#
#   * those lists were NARROWER than the platform's own. A value the platform
#     catches and the template misses makes the platform raise INSIDE the node,
#     and the wrapper then discards that node's entire return value — the
#     clearing included. A narrower local gate is not a weaker gate; it is a
#     containment bypass;
#   * a second gate that contains the same leak on its own makes this one
#     unfalsifiable. Removing the clearing below would leave the end-to-end
#     containment test green. More defence, less assurance.
#
# ── Why the detector is a UNION, not a delegation ────────────────────────────
#
# The platform's patterns describe credential FORMATS — `AKIA…`, `sk-…`,
# `eyJ…`, `Bearer …`, connection strings. They match none of the assignment
# forms (`password=…`, `api_key: …`) the template's own list caught. Replacing
# the local list with the platform detector would look like a tightening and be
# a narrowing. Both sets run. Wider is safe; narrower is a bypass.
#
# ── Why the identifier layer does NOT use the platform's `name` class ────────
#
# The platform's personal-data detector reads any two consecutive title-case
# words as a personal name. Measured on this template's own clean report: 26
# findings — "Compliance Report", "Privacy Policy", "Total Gaps Identified",
# "Overall Compliance Status". Routing the report through that class would
# refuse every legitimate response. The structured identifier types are used
# instead, and the gap they leave — the platform's word boundaries are computed
# over a class that includes Kana and Kanji, so an unspaced Japanese
# `個人番号1234-5678-9012` returns nothing while the ASCII-spaced form is caught
# — is closed by an explicit pattern in src/services/caller_contract.py.
#
# ── Containment ──────────────────────────────────────────────────────────────
#
# Returning an error is not containment. The framework resolves the caller's
# output as `formatted_output or result` with no status check, so a boundary
# that merely raised still shipped the un-gated document. Measured on the
# shipped code: the node raised, the wrapper discarded its delta, and the caller
# received the document with the offending value in it. This node therefore
# CLEARS every output-bearing field as it blocks and replaces formatted_output
# with a TRUTHY notice — a falsy replacement re-opens the very fallback the
# clearing exists to close. src/graph/graph.py closes the same door from the
# other side for the paths that never reach this node at all.
#
# ── The error channel is caller-visible ──────────────────────────────────────
#
# `error_log` carries node-authored text and, wherever a node interpolates a
# caught exception, upstream message text. It is the internal channel and the
# audit trail needs it, but nothing read from it is ever published to the
# caller. What the caller sees is drawn only from the closed set of constants
# declared in this module: a reason code, a violation LABEL (the name of the
# pattern that matched, never the text it matched) and counts.

import logging
from typing import Any, ClassVar, Dict, Optional, Tuple

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.credential_detector import detect_credentials
from framework.security.pii_detector import detect_pii
from shared.utils.audit_logger import emit_trace_event
from src.services.caller_contract import (
    EXTRA_CREDENTIAL_PATTERNS,
    EXTRA_IDENTIFIER_PATTERNS,
    PLATFORM_IDENTIFIER_TYPES,
)

logger = logging.getLogger(__name__)

# The caller-visible reason codes. Every value the caller can see on an error
# path is one of these constants or a violation label produced by the scan
# below — never a string read out of state.
REASON_OUTPUT_WITHHELD = "output_withheld_at_boundary"
REASON_WORKFLOW_FAILED = "workflow_did_not_produce_a_report"

# The replacement is TRUTHY on purpose: the framework's envelope falls back to
# state["result"] whenever formatted_output is falsy, so an empty value here
# would re-open the exact channel the clearing closes.
WITHHELD_NOTICE = (
    "[OUTPUT WITHHELD — the assembled compliance report did not pass the output "
    "boundary. Resend the specification without credential-like strings or direct "
    "personal identifiers.]"
)
NO_REPORT_NOTICE = "[NO REPORT — the workflow did not produce a compliance report for this request.]"

# Every state field at this level that can carry released text. On a violation
# each one is overwritten, so no path out of the graph — including the
# framework's own fallback to state["result"] — can reach the un-gated document,
# and a checkpoint or a downstream reader cannot pick it up either.
OUTPUT_BEARING_FIELDS: Tuple[str, ...] = (
    "result",
    "formatted_output",
    "attestation_doc",
    "disclosure_language_ja",
    "disclosure_language_en",
)


def security_gate_output(content: Any, _depth: int = 0) -> Optional[str]:
    """Scan released content and name the first violation, or None if clean.

    Walks nested mappings and sequences, scanning every leaf: caller-derived
    text rides inside nested structures, and a gate that looked only at
    top-level strings reports zero findings on a payload whose leak sits one
    level down.

    Returns the pattern NAME, never the matched text — a violation report that
    quoted the value would be the leak.
    """
    if content is None or _depth > 8:
        return None
    if isinstance(content, dict):
        for value in content.values():
            hit = security_gate_output(value, _depth + 1)
            if hit:
                return hit
        return None
    if isinstance(content, (list, tuple)):
        for item in content:
            hit = security_gate_output(item, _depth + 1)
            if hit:
                return hit
        return None
    if isinstance(content, (bool, int, float)):
        return None

    text = str(content)
    findings = detect_credentials(text)
    if findings:
        return str(findings[0]["type"])
    for name, pattern in EXTRA_CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return name
    for finding in detect_pii(text):
        if str(finding["type"]) in PLATFORM_IDENTIFIER_TYPES:
            return str(finding["type"])
    for name, pattern in EXTRA_IDENTIFIER_PATTERNS:
        if pattern.search(text):
            return name
    return None


class PostProcessNode(FunctionNode):
    """Assemble the compliance report and enforce the output boundary.

    Input state keys (written into outer state by the main slot's merge_output,
    so all are present on every real invocation):
        attestation_doc, disclosure_language_ja, disclosure_language_en,
        ai_act_checklist, data_gov_gaps, result

    Output state keys (partial dict):
        formatted_output: the report when clean; a truthy withheld notice on a
                          violation — never an empty value, which would re-open
                          the envelope's fallback
        result:           gated alongside formatted_output
        status:           AgentStatus.SUCCESS or AgentStatus.ERROR
        error_log:        (on a violation) one closed-set reason label
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        # No "upstream already errored" branch here, deliberately. The framework
        # short-circuits every node whose incoming state already carries an
        # error status — execute() is not called at all — and the backbone
        # routes a non-success main straight to finalize, past this node. A
        # branch for that case would be a layer that can never fire, and a
        # never-firing layer reads as containment while proving nothing.
        # src/graph/graph.py's get_output() is where those paths are actually
        # contained, and it is falsifiable there.
        attestation_doc = state.get("attestation_doc") or ""
        disclosure_ja = state.get("disclosure_language_ja") or ""
        disclosure_en = state.get("disclosure_language_en") or ""
        ai_act_checklist: Dict[str, Any] = state.get("ai_act_checklist") or {}
        data_gov_gaps = state.get("data_gov_gaps") or []

        if not str(attestation_doc).strip():
            emit_trace_event(
                "post_process_no_report",
                {"reason": REASON_WORKFLOW_FAILED},
                state,
            )
            return self._contain(REASON_WORKFLOW_FAILED, NO_REPORT_NOTICE)

        total = ai_act_checklist.get("total_count", 0)
        compliant = ai_act_checklist.get("compliant_count", 0)
        critical_gaps = ai_act_checklist.get("critical_gaps", [])
        gap_count = len(data_gov_gaps)
        high_severity_gaps = [g for g in data_gov_gaps if g.get("severity") == "high"]

        sections = [
            "# AI Recommendation Algorithm Disclosure & Compliance Report",
            "",
            "## 1. APPI 2026 Disclosure Language",
            "",
            "### Japanese (消費者向け開示文)",
            disclosure_ja or "(not generated)",
            "",
            "### English (Consumer-facing Disclosure)",
            disclosure_en or "(not generated)",
            "",
            "## 2. Japan AI Act Compliance Checklist",
            f"Compliant: {compliant}/{total} requirements",
        ]

        if critical_gaps:
            sections.append(f"Critical gaps: {', '.join(critical_gaps)}")

        sections += [
            "",
            "## 3. Data Governance Gap Analysis",
            f"Total gaps identified: {gap_count}",
        ]

        if high_severity_gaps:
            sections.append(f"High-severity gaps: {len(high_severity_gaps)}")
            for gap in high_severity_gaps:
                sections.append(f"  - {gap.get('description', '')}")

        sections += [
            "",
            "## 4. Compliance Attestation",
            attestation_doc,
        ]

        formatted = "\n".join(sections)

        # The structured fields are released alongside the rendered report, so
        # they are scanned with it: blocking here rather than dropping them
        # later means the caller is told the report was withheld instead of
        # receiving a success envelope quietly missing half its content.
        released = {
            "formatted_output": formatted,
            "attestation_doc": attestation_doc,
            "disclosure_language_ja": disclosure_ja,
            "disclosure_language_en": disclosure_en,
            "ai_act_checklist": ai_act_checklist,
            "data_gov_gaps": data_gov_gaps,
        }
        violation = security_gate_output(released)
        if violation:
            logger.error("PostProcessNode: output withheld — violation type: %s", violation)
            emit_trace_event(
                "post_process_output_withheld",
                {"reason": REASON_OUTPUT_WITHHELD, "violation": violation},
                state,
            )
            return self._contain(REASON_OUTPUT_WITHHELD, WITHHELD_NOTICE, violation)

        emit_trace_event(
            "post_process_report_assembled",
            {
                "output_length": len(formatted),
                "checklist_compliant": compliant,
                "checklist_total": total,
                "data_gov_gap_count": gap_count,
                "high_severity_gap_count": len(high_severity_gaps),
            },
            state,
        )

        return {
            "formatted_output": formatted,
            "result": formatted,
            "status": AgentStatus.SUCCESS,
        }

    @staticmethod
    def _contain(reason: str, notice: str, violation: Optional[str] = None) -> Dict[str, Any]:
        """Return an ERROR delta carrying no released text.

        Every output-bearing field is cleared and formatted_output is replaced
        by a truthy notice. `error_log` receives a closed-set label only: the
        reason code and, when the boundary itself refused, the NAME of the
        pattern that matched. Nothing is read out of state, so no node-authored
        text and no upstream message can travel on this path.
        """
        contained: Dict[str, Any] = {field: None for field in OUTPUT_BEARING_FIELDS}
        contained["formatted_output"] = notice
        contained["result"] = notice
        contained["status"] = AgentStatus.ERROR
        contained["error_log"] = [reason if violation is None else f"{reason}:{violation}"]
        return contained
