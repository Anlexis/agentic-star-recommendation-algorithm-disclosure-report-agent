"""PB-6: Backbone invoke-order verification — RET-C2-342.

Verifies that a full Graph().invoke() over a SUCCESS-yielding payload
traverses the AgentBaseGraph backbone in the required order:
  InitializeNode -> PreProcessNode -> DisclosureWorkflowGraphNode
  -> PostProcessNode -> FinalizeNode

Rules:
  - Caller MUST be VERIFIED_EXTERNAL (real external-caller trust path).
    INTERNAL would mask the inner-node trust trap (inner ANONYMOUS nodes
    vs a real VERIFIED_EXTERNAL caller; INTERNAL silently passes where a
    real caller would hit the gate).
  - Payload MUST yield AgentStatus.SUCCESS; a non-SUCCESS result
    short-circuits main -> finalize and skips PostProcessNode.
  - node_history entries are read as class names (str) or types.
"""

from framework.nodes.defaults.finalize_node import FinalizeNode
from framework.nodes.defaults.initialize_node import InitializeNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import DisclosureWorkflowGraphNode, RecommendationAlgorithmDisclosureAgent
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode

# ── Template-specific constants ───────────────────────────────────────────────

_MAIN_SLOT_NODE = DisclosureWorkflowGraphNode

_VALID_PAYLOAD = (
    "Collaborative filtering recommendation engine using purchase history "
    "and browsing behavior data. Input features: user click history, "
    "purchase history, session data. Output actions: product recommendations. "
    "System uses automated decisions with no manual review. "
    "Training data sources: internal transaction logs."
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _node_class_name(entry) -> str:
    """Normalise a node_history entry to a class name string."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, type):
        return entry.__name__
    return type(entry).__name__


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPB6BackboneInvokeOrder:
    """PB-6: Graph().invoke() must traverse backbone nodes in the correct order.

    Uses a real VERIFIED_EXTERNAL InvocationContext — the same trust path
    as a production caller — so that the inner-node trust gate is exercised
    correctly (inner ANONYMOUS gates must admit VERIFIED_EXTERNAL >= ANONYMOUS).
    """

    def test_backbone_order_success_path(self):
        """TC-PB6-01: Backbone traversal order with a SUCCESS-yielding payload."""
        agent = RecommendationAlgorithmDisclosureAgent()
        agent.compile()

        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke(user_input=_VALID_PAYLOAD, ctx=ctx)

        # Result must be SUCCESS — otherwise backbone short-circuits and
        # PostProcessNode is skipped, making the order assertion meaningless.
        output_preview = (result.get("output") or "")[:200]
        assert result["status"] == AgentStatus.SUCCESS, (
            f"PB-6 requires a SUCCESS invoke to observe the full backbone. "
            f"Got status={result['status']!r}, output={output_preview!r}"
        )

        # Output must be non-empty
        assert result.get("output"), "PB-6: result['output'] is empty — check PostProcessNode.formatted_output"

        node_history = result.get("node_history", [])
        history_names = [_node_class_name(e) for e in node_history]

        expected_backbone = [
            InitializeNode.__name__,
            PreProcessNode.__name__,
            _MAIN_SLOT_NODE.__name__,
            PostProcessNode.__name__,
            FinalizeNode.__name__,
        ]

        # Every backbone node must appear
        missing = [n for n in expected_backbone if n not in history_names]
        assert not missing, (
            f"PB-6: backbone nodes missing from node_history: {missing}\n" f"Full node_history: {history_names}"
        )

        # Order must be correct
        positions = {n: history_names.index(n) for n in expected_backbone}
        in_order = sorted(expected_backbone, key=lambda n: positions[n])
        assert in_order == expected_backbone, (
            f"PB-6: backbone traversal order violation.\n"
            f"Expected: {expected_backbone}\n"
            f"Actual order from node_history: {in_order}\n"
            f"Full node_history: {history_names}"
        )

    def test_pre_process_trust_gate_enforced(self):
        """TC-PB6-02: ANONYMOUS caller must be denied by VERIFIED_EXTERNAL pre_process gate."""
        agent = RecommendationAlgorithmDisclosureAgent()
        agent.compile()

        ctx = InvocationContext(caller_trust_level=TrustLevel.ANONYMOUS)
        result = agent.invoke(user_input=_VALID_PAYLOAD, ctx=ctx)

        # ANONYMOUS caller < VERIFIED_EXTERNAL gate → backbone must return ERROR
        assert result["status"] == AgentStatus.ERROR, (
            f"PB-6: ANONYMOUS caller should be denied by VERIFIED_EXTERNAL gate. " f"Got status={result['status']!r}"
        )

    def test_empty_input_returns_error(self):
        """TC-PB6-03: Empty input yields ERROR without reaching the inner graph."""
        agent = RecommendationAlgorithmDisclosureAgent()
        agent.compile()

        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke(user_input="", ctx=ctx)

        assert (
            result["status"] == AgentStatus.ERROR
        ), f"PB-6: empty input must yield ERROR. Got status={result['status']!r}"
