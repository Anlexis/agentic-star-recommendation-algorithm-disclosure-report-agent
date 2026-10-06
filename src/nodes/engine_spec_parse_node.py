"""AgentCore Platform v1.0"""

# EngineSpecParseNode — inner domain node (ANONYMOUS trust level).
# Parses the recommendation engine specification into a structured dictionary
# capturing model type, input features, output actions, data categories and
# automated-decision flags, then folds in whatever the operator declared
# explicitly in the structured channel.
#
# Precedence: an explicit declaration wins over a keyword read out of prose.
# The operator knows what its system does; the keyword scan is the fallback for
# the common case where nobody has filled the structured fields in. Which of the
# two applied is recorded, because an attestation that cannot say where a fact
# came from is not evidence of anything.

import re
from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.caller_contract import (
    MAX_EXTRACTED_ITEM_CHARS,
    MAX_EXTRACTED_ITEMS,
)
from src.services.service import contains_redaction_sentinel

# Keyword sets for lightweight rule-based parsing
_MODEL_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "collaborative_filtering": ["collaborative filtering", "user-based", "item-based", "cf model"],
    "content_based": ["content-based", "content based", "tfidf", "embedding", "similarity"],
    "deep_learning": ["neural", "deep learning", "transformer", "bert", "lstm", "rnn"],
    "hybrid": ["hybrid", "ensemble", "combined", "blended"],
    "rule_based": ["rule-based", "rule based", "business rule", "manual", "heuristic"],
    "matrix_factorization": ["matrix factorization", "svd", "als", "factorization"],
}

_AUTOMATED_DECISION_KEYWORDS = [
    "fully automated",
    "no human review",
    "automatic",
    "autonomous decision",
    "without human",
    "real-time automatic",
]

_DATA_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "purchase_history": ["purchase history", "order history", "buying history", "past purchases"],
    "browsing_behavior": ["browsing", "click", "page view", "session", "visit history"],
    "demographic": ["age", "gender", "location", "demographic", "user profile"],
    "personal_information": ["personal", "pii", "name", "email", "phone", "address"],
    "behavioral_signals": ["behavior", "engagement", "rating", "review", "feedback"],
    "third_party": ["third party", "external", "partner data", "acquired data"],
}


def _detect_model_type(text: str) -> str:
    """Identify the dominant model type from free-text spec."""
    lower = text.lower()
    for model_type, keywords in _MODEL_TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return model_type
    return "unspecified"


def _clean_items(raw_items: List[str]) -> List[str]:
    """De-duplicate, bound and filter a list of phrases pulled out of the prose.

    Two bounds and one filter:

      * each phrase is truncated to MAX_EXTRACTED_ITEM_CHARS, so an operator
        cannot push an arbitrarily long run of its own text into a rendered
        line by writing one enormous sentence;
      * the list is capped at MAX_EXTRACTED_ITEMS;
      * a phrase carrying a platform redaction marker is DROPPED. The platform
        rewrites personal-data shapes in the specification before this node
        reads it, so a masked value arrives as an ordinary string; counting it
        as a documented input feature would report a redaction as evidence.

    The capture groups themselves exclude newlines, so no phrase can introduce a
    line break into a rendered document and manufacture a numbered step.
    """
    cleaned: List[str] = []
    for item in raw_items:
        phrase = item.strip()[:MAX_EXTRACTED_ITEM_CHARS].strip()
        if not phrase or contains_redaction_sentinel(phrase) or phrase in cleaned:
            continue
        cleaned.append(phrase)
        if len(cleaned) >= MAX_EXTRACTED_ITEMS:
            break
    return cleaned


def _extract_features(text: str) -> List[str]:
    """Extract mentions of input features from spec text."""
    patterns = [
        r"input features?[:\s]+([^\n.]+)",
        r"features?[:\s]+([^\n.]+)",
        r"uses?\s+([^\n.]+?)\s+as\s+input",
    ]
    features: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.group(1).strip()
            parts = re.split(r",\s*|\s+and\s+", raw)
            features.extend(p.strip() for p in parts if p.strip())
    return _clean_items(features)


def _detect_data_categories(text: str) -> List[str]:
    """Identify data categories referenced in the spec."""
    lower = text.lower()
    found: List[str] = []
    for category, keywords in _DATA_CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            found.append(category)
    return found


def _detect_automated_decision(text: str) -> bool:
    """Return True if spec indicates fully automated decisions."""
    lower = text.lower()
    return any(kw in lower for kw in _AUTOMATED_DECISION_KEYWORDS)


def _extract_output_actions(text: str) -> List[str]:
    """Extract described output actions from spec text."""
    patterns = [
        r"outputs?[:\s]+([^\n.]+)",
        r"recommends?[:\s]+([^\n.]+)",
        r"produces?[:\s]+([^\n.]+)",
    ]
    actions: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.group(1).strip()
            parts = re.split(r",\s*|\s+and\s+", raw)
            actions.extend(p.strip() for p in parts if p.strip())
    return _clean_items(actions)[:8]


class EngineSpecParseNode(FunctionNode):
    """Parse the recommendation engine specification into structured fields.

    Reads engine_spec_raw (seeded across the subgraph boundary by the inner
    graph's initial-state hook) and caller_contract, and produces
    engine_spec_parsed with:
      model_type, input_features, output_actions, data_categories,
      automated_decision_flag, declared_high_impact_outputs, field_sources,
      spec_completeness_score.

    Trust level ANONYMOUS: this is an inner domain node; the outer pre_process
    (VERIFIED_EXTERNAL) has already authenticated the caller.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        raw_spec = state.get("engine_spec_raw") or state.get("validated_input") or state.get("user_input", "")
        contract: Dict[str, Any] = state.get("caller_contract") or {}

        if not raw_spec:
            emit_trace_event(
                "engine_spec_parse_failed",
                {"reason": "empty_spec"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["EngineSpecParseNode: engine_spec_raw is empty"],
            }

        field_sources: Dict[str, str] = {}

        if "model_type" in contract:
            model_type = str(contract["model_type"])
            field_sources["model_type"] = "declared"
        else:
            model_type = _detect_model_type(raw_spec)
            field_sources["model_type"] = "specification"

        if "data_categories" in contract:
            data_categories = list(contract["data_categories"])
            field_sources["data_categories"] = "declared"
        else:
            data_categories = _detect_data_categories(raw_spec)
            field_sources["data_categories"] = "specification"

        if "automated_decision" in contract:
            automated_decision = bool(contract["automated_decision"])
            field_sources["automated_decision_flag"] = "declared"
        else:
            automated_decision = _detect_automated_decision(raw_spec)
            field_sources["automated_decision_flag"] = "specification"

        input_features = _extract_features(raw_spec)
        output_actions = _extract_output_actions(raw_spec)
        declared_high_impact = list(contract.get("high_impact_outputs", []))

        # Completeness heuristic: penalise missing fields
        completeness_flags = [
            bool(model_type != "unspecified"),
            bool(input_features),
            bool(output_actions or declared_high_impact),
            bool(data_categories),
        ]
        completeness_score = round(sum(completeness_flags) / len(completeness_flags), 2)

        parsed: Dict[str, Any] = {
            "model_type": model_type,
            "input_features": input_features,
            "output_actions": output_actions,
            "declared_high_impact_outputs": declared_high_impact,
            "data_categories": data_categories,
            "automated_decision_flag": automated_decision,
            "spec_completeness_score": completeness_score,
            "field_sources": field_sources,
            "raw_length": len(raw_spec),
        }

        emit_trace_event(
            "engine_spec_parsed",
            {
                "model_type": model_type,
                "feature_count": len(input_features),
                "data_category_count": len(data_categories),
                "automated_decision_flag": automated_decision,
                "completeness_score": completeness_score,
                "declared_fields": sorted(k for k, v in field_sources.items() if v == "declared"),
            },
            state,
        )

        return {
            "engine_spec_parsed": parsed,
            "status": AgentStatus.SUCCESS,
        }
