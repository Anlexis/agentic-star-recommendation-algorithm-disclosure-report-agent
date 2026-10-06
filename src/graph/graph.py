"""AgentCore Platform v1.0"""

# RET-C2-342 — RecommendationAlgorithmDisclosureAgent
# Cat 2 — multi-step domain workflow (document-generation pattern).
#
# Architecture: Cat 2 nested (AgentBaseGraph outer + GraphNode in main slot).
#
# Outer backbone (fixed, inherited from AgentBaseGraph):
#   START -> initialize -> pre_process -> main -> {route} -> post_process -> finalize -> END
#                                              (RETRY -> pre_process, max_retry)
#
# Inner domain workflow (encapsulated by DisclosureWorkflowGraphNode):
#   engine_spec_parse -> appi_obligation_classify -> disclosure_language_gen
#   -> ai_act_doc_checklist -> data_gov_gap_flag -> attestation_format
#
# Trust levels:
#   pre_process  : VERIFIED_EXTERNAL  (external caller gate)
#   main         : GraphNode (pass-through — no independent trust check)
#   post_process : ANONYMOUS
#   all inner domain nodes: ANONYMOUS
#
# Directory layout:
#   src/graph/graph.py                 <- outer graph (this file)
#   src/graph/domain_workflow_graph.py <- inner graph (disclosure topology)
#   src/graph/context_bridge.py        <- validated caller request across the boundary
#
# Class name MUST match config/agent.yaml `class:` and src/api/server.py import.

from pathlib import Path
from typing import Any, ClassVar, Dict

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.utils.config_loader import load_agent_config
from src.graph.context_bridge import set_caller_request
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State

# Repo root: src/graph/graph.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The assessment tuning to forward when config/config.yaml cannot be read.
# Deliberately STRICTER than the shipped configuration rather than a copy of it:
# a fallback equal to the config makes a live configuration and a dead one
# behave identically, so nothing — no test, no operator — can tell them apart.
_FALLBACK_ASSESSMENT: Dict[str, Any] = {
    "retention_review_days": 365.0,
    "high_severity_gap_ceiling": 0,
    "critical_gap_ceiling": 0,
}


def runtime_config() -> Dict[str, Any]:
    """Load config/config.yaml — the live runtime parameters.

    The registry loads this file and passes it to the graph constructor; the
    standalone HTTP entry point does the same, so `max_retry` and the assessment
    tuning are live in both deployments rather than declared and ignored.

    Reading the static manifest (config/agent.yaml) here instead would return
    nothing: the flat manifest carries identity and compile-time requirements
    only, and a reader pointed at it degrades silently to defaults — the failure
    mode this file exists to close.
    """
    loaded = load_agent_config(_REPO_ROOT)
    return dict(loaded) if isinstance(loaded, dict) else {}


class DisclosureWorkflowGraphNode(GraphNode):
    """Wraps DomainWorkflowGraph; assigned to the `main` slot of the backbone.

    GraphNode contract:
      get_subgraph()  -- instantiate the inner DomainWorkflowGraph
      extract_input() -- hand the validated specification to the inner graph and
                         stash the validated caller contract on the bridge
      merge_output()  -- map inner sub_result fields back to outer state delta

    error_strategy "propagate": inner errors re-raised as SubgraphError (fail-fast).
    """

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def _parent_config(self) -> Dict[str, Any]:
        """Forward the live assessment tuning to the inner graph.

        Returns the tuning under config["configurable"] — never an empty dict.
        The inner graph republishes it into inner state
        (DomainWorkflowGraph._extra_initial_state()) so the attestation step
        reads live values: node execute() methods take no config parameter, so
        state seeding is the only route a configured value can travel into a
        domain node.
        """
        assessment = runtime_config().get("assessment")
        if not isinstance(assessment, dict) or not assessment:
            assessment = dict(_FALLBACK_ASSESSMENT)
        return {"configurable": {"assessment": assessment}}

    def get_subgraph(self) -> Any:
        """Instantiate and return the inner DomainWorkflowGraph.

        Imported inside the method to keep module import order free of a cycle.
        The inner graph receives the runtime-derived config through its
        constructor; its domain nodes still take no constructor arguments.
        """
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        return DomainWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        """Return the validated specification, and bridge the caller contract.

        The framework hands only a string to the inner graph, so the structured
        half of the request travels on the bridge instead — set here, one step
        before the inner invoke, and read by the inner graph's initial-state
        hook. Only what pre_process already validated crosses.
        """
        # Only fields a SUCCESSFUL pre_process wrote are read here. There is no
        # fallback to the raw request: the framework already short-circuits
        # every node downstream of a refusal, and a raw fallback would mean that
        # if it ever stopped doing so, a refused specification would be
        # processed anyway.
        specification = str(state.get("validated_input") or state.get("engine_spec_raw") or "")
        contract = state.get("caller_contract")
        set_caller_request(specification, contract if isinstance(contract, dict) else {})
        return specification

    def merge_output(self, state: AgentState, sub_result: Dict[str, Any]) -> Dict[str, Any]:
        """Map the inner result into the outer state delta (changed keys only).

        Key coupling, designed together with DomainWorkflowGraph.get_output().

        A non-success inner status never reaches here — error_strategy is
        "propagate", so the inner error is re-raised first — but the guard stays
        so a future strategy change cannot start publishing an un-gated document
        through this path.
        """
        status = sub_result.get("status")
        if status not in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value):
            return {
                "result": None,
                "attestation_doc": None,
                "formatted_output": None,
                "status": status,
            }
        return {
            "result": sub_result.get("output"),
            "status": status,
            # Domain fields needed by PostProcessNode
            "attestation_doc": sub_result.get("attestation_doc"),
            "disclosure_language_ja": sub_result.get("disclosure_language_ja"),
            "disclosure_language_en": sub_result.get("disclosure_language_en"),
            "ai_act_checklist": sub_result.get("ai_act_checklist"),
            "data_gov_gaps": sub_result.get("data_gov_gaps"),
            "appi_obligations": sub_result.get("appi_obligations"),
            "engine_spec_parsed": sub_result.get("engine_spec_parsed"),
        }


class RecommendationAlgorithmDisclosureAgent(AgentBaseGraph):
    """Outer AgentBaseGraph for RET-C2-342.

    Fixed 5-node backbone (initialize -> pre_process -> main -> post_process ->
    finalize). Domain complexity is encapsulated inside
    DisclosureWorkflowGraphNode.

    Class name matches:
      - config/agent.yaml  class: "src.graph.graph.RecommendationAlgorithmDisclosureAgent"
      - src/api/server.py  from src.graph.graph import RecommendationAlgorithmDisclosureAgent
    """

    @property
    def name(self) -> str:
        return "RecommendationAlgorithmDisclosureAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        """Wire the 5-node backbone.

        super() injects InitializeNode (sets schema_version, session_id,
        trust_level) and FinalizeNode (builds response_metadata, total_time_ms).
        add_edges() is NOT overridden — backbone wiring is the framework's
        concern.
        """
        super().register_nodes()  # fills: initialize, finalize
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = DisclosureWorkflowGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    def get_output(self, state: AgentState) -> Dict[str, Any]:
        """Shape the caller-facing envelope.

        The framework resolves the output as ``formatted_output or result`` with
        NO status check, so an error path that left ``result`` in place ships the
        un-gated document inside the error envelope. That is not hypothetical
        here: the main slot writes ``result`` on every successful run, and when
        the output boundary rejects the assembled report the framework wrapper
        DISCARDS the whole node delta — the clearing included — leaving
        ``result`` untouched in state. Measured on the shipped code, the caller
        received the un-gated document with the offending value still in it.

        So on any non-success status the output resolves to the boundary's own
        withheld notice, or to None. It never falls back to ``result``.

        No third layer re-scans the success path here. One would contain a leak
        on its own and thereby make the post_process scan unfalsifiable — more
        defence buying less assurance. post_process is the single place the
        success path is checked, and the mutant that removes its clearing must
        be able to fail.
        """
        output: Dict[str, Any] = dict(super().get_output(state))
        if state.get("status") not in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value):
            output["output"] = state.get("formatted_output") or None
        return output
