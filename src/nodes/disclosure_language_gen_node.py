"""AgentCore Platform v1.0"""

# DisclosureLanguageGenNode — inner domain node (ANONYMOUS trust level).
# Generates consumer-facing disclosure language in Japanese and English
# based on the parsed engine specification and classified APPI obligations.
#
# Output is rule-based template expansion (no LLM required): the obligation
# level, data categories, and model type are mapped to disclosure templates
# defined in-module (encoding the 消費者庁 FY2026 disclosure guidelines).

from typing import Any, ClassVar, Dict

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# ── Japanese disclosure templates (消費者向け開示文) ─────────────────────────

_JA_TEMPLATE_FULL = """\
【AIレコメンデーションアルゴリズム開示 (APPI 2026 第24条の2)】

当サービスのレコメンデーション機能は、AIを活用した自動化システムにより提供されています。

■ 使用するデータ
お客様の{data_categories_ja}を入力として使用しています。

■ アルゴリズムの概要
{model_type_ja}を用いて、お客様に最適な商品・コンテンツをご提案します。

■ 自動化による意思決定
本システムは自動化された意思決定を行います。お客様は、この自動化された意思決定に\
対して異議を申し立てる権利を有します (APPI 第28条)。

■ データ主体の権利
個人情報の開示・訂正・削除については、プライバシーポリシーに記載の窓口にお問い合わせください。

■ 同意の取得
高影響度の自動化意思決定 (価格・信用・雇用等) については、事前の同意を取得します (APPI 第26条の3)。
"""

_JA_TEMPLATE_PARTIAL = """\
【AIレコメンデーションアルゴリズム開示 (APPI 2026 第24条の2)】

当サービスのレコメンデーション機能は、AIを活用したシステムにより提供されています。

■ 使用するデータ
{data_categories_ja}を参照してレコメンデーションを生成します。

■ アルゴリズムの概要
{model_type_ja}を用いて、お客様の嗜好に合わせた提案を行います。

■ データ主体の権利
個人情報の開示・訂正・削除については、プライバシーポリシーに記載の窓口にお問い合わせください。
"""

_JA_TEMPLATE_NONE = """\
【AIレコメンデーション機能について】

当サービスのレコメンデーション機能は、個人を特定しない集計データおよびコンテンツ属性\
をもとにした提案を行います。個人情報を特定・使用した自動化意思決定は行っておりません。
"""

# ── English disclosure templates ─────────────────────────────────────────────

_EN_TEMPLATE_FULL = """\
[AI Recommendation Algorithm Disclosure (APPI 2026, Art. 24-bis)]

Our recommendation feature is powered by an automated AI system.

Data Used: We use your {data_categories_en} as inputs to the recommendation engine.

Algorithm: We employ {model_type_en} to suggest products and content personalised to you.

Automated Decision-Making: This system makes automated decisions. You have the right to
contest automated decisions that significantly affect you (APPI Art. 28).

Your Rights: To request access, correction or deletion of your personal data, please
contact us via the details in our Privacy Policy.

Consent: For automated decisions with high-impact outcomes (pricing, credit, employment),
we will obtain your prior consent (APPI Art. 26-ter).
"""

_EN_TEMPLATE_PARTIAL = """\
[AI Recommendation Algorithm Disclosure (APPI 2026, Art. 24-bis)]

Our recommendation feature is powered by an AI system.

Data Used: We reference {data_categories_en} to generate recommendations.

Algorithm: We use {model_type_en} to tailor suggestions to your preferences.

Your Rights: To request access, correction or deletion of your personal data, please
contact us via the details in our Privacy Policy.
"""

_EN_TEMPLATE_NONE = """\
[About Our Recommendation Feature]

Our recommendation feature is based on aggregated, non-identifying data and content
attributes. We do not use personal data for automated individual decision-making.
"""

# ── Model type localisation ───────────────────────────────────────────────────

_MODEL_TYPE_JA: dict[str, str] = {
    "collaborative_filtering": "協調フィルタリング",
    "content_based": "コンテンツベースフィルタリング",
    "deep_learning": "深層学習モデル",
    "hybrid": "ハイブリッドアルゴリズム",
    "rule_based": "ルールベースロジック",
    "matrix_factorization": "行列分解モデル",
    "unspecified": "AIレコメンデーションアルゴリズム",
}

_MODEL_TYPE_EN: dict[str, str] = {
    "collaborative_filtering": "collaborative filtering",
    "content_based": "content-based filtering",
    "deep_learning": "deep learning models",
    "hybrid": "a hybrid recommendation algorithm",
    "rule_based": "rule-based logic",
    "matrix_factorization": "matrix factorization",
    "unspecified": "an AI recommendation algorithm",
}

_DATA_CATEGORY_JA: dict[str, str] = {
    "purchase_history": "購買履歴",
    "browsing_behavior": "閲覧行動・クリック履歴",
    "demographic": "年齢・性別・居住地等の属性情報",
    "personal_information": "お客様の個人情報",
    "behavioral_signals": "評価・レビュー・エンゲージメントデータ",
    "third_party": "第三者提供データ",
}

_DATA_CATEGORY_EN: dict[str, str] = {
    "purchase_history": "purchase history",
    "browsing_behavior": "browsing behaviour and click history",
    "demographic": "demographic attributes (age, gender, location)",
    "personal_information": "personal information",
    "behavioral_signals": "ratings, reviews, and engagement signals",
    "third_party": "third-party provided data",
}


# This node used to carry its own five-token credential scan over the two
# disclosure fields. It was removed, and the check it performed did not go with
# it — it moved OUTWARD, to the single output boundary in post_process_node.py,
# where the scan runs over the assembled report (a superset of these two fields)
# with a strictly WIDER detector: the platform's own credential patterns unioned
# with the assignment forms the platform does not carry.
#
# Two reasons, and the second is the one that is easy to get backwards:
#
#   * the local list missed `AKIA…`, `sk-…`, JWTs and connection strings, all
#     of which the platform detector catches — a narrower gate is not a weaker
#     gate, it is a containment bypass, because when the platform raises inside
#     this node the wrapper discards the node's whole return value;
#   * a second gate that contains the same leak on its own makes the boundary
#     gate UNFALSIFIABLE. Removing the boundary's clearing would leave the
#     end-to-end containment test green, and the test would look load-bearing
#     while proving nothing. More defence, less assurance.
#
# The platform's own mandatory scan still runs on this node's result on every
# call; it is the floor, and this node no longer has a narrower one in front
# of it.


class DisclosureLanguageGenNode(FunctionNode):
    """Generate consumer-facing disclosure language (Japanese + English).

    Reads engine_spec_parsed and appi_obligations from state.
    Produces disclosure_language_ja and disclosure_language_en using
    rule-based template expansion mapped to APPI 2026 disclosure guidelines.

    Trust level ANONYMOUS: inner domain node.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: AgentState) -> Dict[str, Any]:
        spec = state.get("engine_spec_parsed") or {}
        obligations = state.get("appi_obligations") or {}

        if not spec or not obligations:
            emit_trace_event(
                "disclosure_language_gen_failed",
                {"reason": "missing_spec_or_obligations"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["DisclosureLanguageGenNode: engine_spec_parsed or appi_obligations missing"],
            }

        obligation_level = obligations.get("obligation_level", "none")
        model_type = spec.get("model_type", "unspecified")
        data_cats = spec.get("data_categories", [])

        # Localise model type
        model_type_ja = _MODEL_TYPE_JA.get(model_type, "AIアルゴリズム")
        model_type_en = _MODEL_TYPE_EN.get(model_type, "an AI algorithm")

        # Localise data categories
        data_cats_ja = "、".join(_DATA_CATEGORY_JA.get(c, c) for c in data_cats) or "各種データ"
        data_cats_en = ", ".join(_DATA_CATEGORY_EN.get(c, c) for c in data_cats) or "various data signals"

        # Select template by obligation level
        if obligation_level == "full":
            ja_text = _JA_TEMPLATE_FULL.format(
                data_categories_ja=data_cats_ja,
                model_type_ja=model_type_ja,
            )
            en_text = _EN_TEMPLATE_FULL.format(
                data_categories_en=data_cats_en,
                model_type_en=model_type_en,
            )
        elif obligation_level == "partial":
            ja_text = _JA_TEMPLATE_PARTIAL.format(
                data_categories_ja=data_cats_ja,
                model_type_ja=model_type_ja,
            )
            en_text = _EN_TEMPLATE_PARTIAL.format(
                data_categories_en=data_cats_en,
                model_type_en=model_type_en,
            )
        else:
            ja_text = _JA_TEMPLATE_NONE
            en_text = _EN_TEMPLATE_NONE

        result = {
            "disclosure_language_ja": ja_text.strip(),
            "disclosure_language_en": en_text.strip(),
            "status": AgentStatus.SUCCESS,
        }

        emit_trace_event(
            "disclosure_language_generated",
            {
                "obligation_level": obligation_level,
                "model_type": model_type,
                "data_category_count": len(data_cats),
                "ja_length": len(ja_text),
                "en_length": len(en_text),
            },
            state,
        )

        return result
