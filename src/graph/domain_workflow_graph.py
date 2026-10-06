"""AgentCore Platform v1.0"""

# DomainWorkflowGraph — inner graph for RET-C2-342 Cat-2 nested pattern.
# Inherits BaseGraph (fully custom topology — no AgentBaseGraph backbone).
# Called by DisclosureWorkflowGraphNode.get_subgraph() in graph.py.
#
# Pipeline (linear):
#   START -> engine_spec_parse -> appi_obligation_classify
#         -> disclosure_language_gen -> ai_act_doc_checklist
#         -> data_gov_gap_flag -> attestation_format -> END
#
# All domain nodes run at TrustLevel.ANONYMOUS (inner nodes never see the
# outer caller's trust level directly — InvocationContext passes through
# unchanged from the outer backbone via GraphNode.execute()).

from typing import Any, Dict

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from src.graph.context_bridge import get_caller_request
from src.nodes.ai_act_doc_checklist_node import AIActDocChecklistNode
from src.nodes.appi_obligation_classify_node import APPIObligationClassifyNode
from src.nodes.attestation_format_node import AttestationFormatNode
from src.nodes.data_gov_gap_flag_node import DataGovGapFlagNode
from src.nodes.disclosure_language_gen_node import DisclosureLanguageGenNode
from src.nodes.engine_spec_parse_node import EngineSpecParseNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow graph: recommendation algorithm disclosure pipeline.

    Runs the 6-node disclosure generation pipeline:
      engine_spec_parse -> appi_obligation_classify -> disclosure_language_gen
      -> ai_act_doc_checklist -> data_gov_gap_flag -> attestation_format

    Inherits BaseGraph for a fully custom node topology (no forced backbone).
    Returned by DisclosureWorkflowGraphNode.get_subgraph() in graph.py.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "recommendation_algorithm_disclosure_workflow"

    @property
    def state_schema(self) -> type:
        return State

    # ── Config validation ─────────────────────────────────────────────────────

    def _validate_config(self) -> None:
        """No mandatory config for the rule-based disclosure workflow."""
        pass

    # ── Initial state ─────────────────────────────────────────────────────────

    def _extra_initial_state(self) -> Dict[str, Any]:
        """Seed the validated caller request and the live tuning into inner state.

        The framework passes only the request STRING across the subgraph
        boundary, so without this hook the domain nodes see neither the
        specification under the key they read nor the operator's structured
        declaration. That gap made four checklist requirements and five
        governance gap checks return the same verdict for every input.

        `assessment` is republished from the constructor config because node
        execute() methods take no config argument — state seeding is the only
        route a configured value can reach a domain node.
        """
        specification, contract = get_caller_request()
        seeded: Dict[str, Any] = {
            "assessment": dict(self.config.get("configurable", {}).get("assessment", {})),
        }
        if specification:
            seeded["engine_spec_raw"] = specification
            seeded["validated_input"] = specification
        if contract:
            seeded["caller_contract"] = contract
        return seeded

    # ── Node registration ─────────────────────────────────────────────────────

    def register_nodes(self) -> None:
        """Register all 6 domain nodes.

        No super() call — BaseGraph.register_nodes() is abstract.
        Do NOT register initialize / finalize; those are outer backbone concerns.
        All nodes are instantiated with NO constructor arguments (SDK-v1 contract).
        """
        self._nodes["engine_spec_parse"] = EngineSpecParseNode()
        self._nodes["appi_obligation_classify"] = APPIObligationClassifyNode()
        self._nodes["disclosure_language_gen"] = DisclosureLanguageGenNode()
        self._nodes["ai_act_doc_checklist"] = AIActDocChecklistNode()
        self._nodes["data_gov_gap_flag"] = DataGovGapFlagNode()
        self._nodes["attestation_format"] = AttestationFormatNode()

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def add_edges(self) -> None:
        """Wire the linear domain workflow topology."""
        self._sg.add_edge(START, "engine_spec_parse")
        self._sg.add_edge("engine_spec_parse", "appi_obligation_classify")
        self._sg.add_edge("appi_obligation_classify", "disclosure_language_gen")
        self._sg.add_edge("disclosure_language_gen", "ai_act_doc_checklist")
        self._sg.add_edge("ai_act_doc_checklist", "data_gov_gap_flag")
        self._sg.add_edge("data_gov_gap_flag", "attestation_format")
        self._sg.add_edge("attestation_format", END)

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, state: State) -> str:
        """Required by the BaseGraph contract. Linear topology — never called.

        Annotated with this graph's OWN State rather than the framework's
        AgentState: LangGraph reads a path callable's annotation as its input
        schema and projects away every field the annotation does not carry, so
        an AgentState annotation would hide the domain fields from any future
        conditional edge wired through here.
        """
        return END

    # ── Output shape ──────────────────────────────────────────────────────────

    def get_output(self, state: AgentState) -> Dict[str, Any]:
        """Shape sub_result for DisclosureWorkflowGraphNode.merge_output().

        Returns all domain output fields plus status/trace metadata.
        merge_output() in graph.py extracts the fields it needs from this dict.
        """
        return {
            "output": state.get("formatted_output") or state.get("attestation_doc"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            # Domain-specific fields passed to outer state via merge_output
            "attestation_doc": state.get("attestation_doc"),
            "disclosure_language_ja": state.get("disclosure_language_ja"),
            "disclosure_language_en": state.get("disclosure_language_en"),
            "ai_act_checklist": state.get("ai_act_checklist"),
            "data_gov_gaps": state.get("data_gov_gaps"),
            "appi_obligations": state.get("appi_obligations"),
            "engine_spec_parsed": state.get("engine_spec_parsed"),
        }
