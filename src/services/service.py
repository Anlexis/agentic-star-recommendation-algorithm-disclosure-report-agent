"""AgentCore Platform v1.0"""

# Service layer: domain queries, external API wrappers, data aggregation.
# Must NOT contain business logic, routing, or credentials.
#
# This template's service layer answers one question for the whole pipeline:
# **for each governance control, is there evidence that the operator has
# documented it, and where did that evidence come from?**
#
# It lives here rather than inside a node because three nodes need the same
# answer — the AI Act checklist, the data-governance gap analysis and the
# attestation. When each derived its own signals, they drifted: the checklist
# read a state key the inner graph never receives, so four of its ten
# requirements reported "not documented" for every specification ever sent, and
# the gap analysis reported the same five gaps whatever the operator wrote. One
# definition, read by all three, is what keeps the report a function of its
# input.
#
# Evidence has two sources and the attestation names which one applied:
#   "specification" — the wording of the engine specification itself;
#   "declared"      — the operator's structured declaration in the request.
# A declaration is an assertion by the operator, not a verification by this
# agent; saying so in the document is the difference between an assessment aid
# and a rubber stamp.

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.services.caller_contract import GOVERNANCE_FLAGS

# Keyword evidence, per control. Matched case-insensitively as substrings of the
# specification prose. Stems ("escalat", "authoris") are deliberate: they cover
# the inflections and both spellings without a word list per form.
_CONTROL_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "human_oversight": (
        "human review",
        "manual override",
        "human in the loop",
        "human oversight",
        "escalat",
        "review queue",
        "human check",
    ),
    "performance_metrics": (
        "precision",
        "recall",
        "accuracy",
        "auc",
        "ndcg",
        "map@",
        "click-through",
        "conversion",
        "benchmark",
        "metric",
        "rmse",
        "mse",
    ),
    "risk_mitigation": (
        "risk",
        "bias",
        "fairness",
        "mitigation",
        "safeguard",
        "fallback",
        "monitor",
        "alert",
        "threshold",
        "drift",
    ),
    "audit_plan": (
        "audit",
        "third-party review",
        "external review",
        "compliance review",
        "internal audit",
        "review cycle",
    ),
    "access_control": (
        "access control",
        "iam",
        "role",
        "permission",
        "rbac",
        "authoris",
        "authoriz",
        "restricted to",
        "only accessible",
    ),
    "model_versioning": (
        "version",
        "rollback",
        "model registry",
        "mlflow",
        "a/b test",
        "canary",
        "champion",
        "challenger",
    ),
    "consent_mechanism": (
        "consent",
        "opt-in",
        "opt-out",
        "agree",
        "permission",
        "authoriz",
    ),
    "data_retention": (
        "retention",
        "delete after",
        "expiry",
        "ttl",
        "purge",
        "data lifecycle",
    ),
}

# The platform rewrites personal-data shapes in the specification before any
# node reads it, leaving a sentinel in their place. A sentinel is a redaction,
# not a fact: counting it as documentation evidence would let a masked value be
# reported as a documented input feature.
_REDACTION_SENTINELS: Tuple[str, ...] = ("[MASKED]", "[REDACTED]", "[MASK]")


def contains_redaction_sentinel(text: str) -> bool:
    """True if the text carries a platform redaction marker."""
    upper = text.upper()
    return any(sentinel in upper for sentinel in _REDACTION_SENTINELS)


class DisclosureEvidenceService:
    """Derives, for each governance control, whether it is evidenced and how."""

    def evidence(
        self,
        specification: str,
        declared: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return ``{control: {"present": bool, "sources": [...]}}``.

        `specification` is the prose the operator sent. `declared` is the
        validated `governance` block of the caller contract, or None.

        Both sources are recorded when both apply, so the attestation can say
        that a control was found in the specification AND declared, rather than
        flattening the two into one unattributed boolean.
        """
        prose = (specification or "").lower()
        declarations = dict(declared or {})
        result: Dict[str, Dict[str, Any]] = {}
        for control in GOVERNANCE_FLAGS:
            sources: List[str] = []
            if any(keyword in prose for keyword in _CONTROL_KEYWORDS[control]):
                sources.append("specification")
            if declarations.get(control) is True:
                sources.append("declared")
            result[control] = {"present": bool(sources), "sources": sources}
        return result

    def retention_days(self, declared: Optional[Mapping[str, Any]] = None) -> Optional[float]:
        """The declared retention period in days, or None when not declared."""
        value = (declared or {}).get("retention_days")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# A single shared instance: the service holds no per-request state, and the
# nodes take no constructor arguments.
EVIDENCE_SERVICE = DisclosureEvidenceService()
