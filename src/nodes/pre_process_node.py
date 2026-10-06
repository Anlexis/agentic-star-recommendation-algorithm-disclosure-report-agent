"""AgentCore Platform v1.0"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants -- never plain strings
#  - Read input_context via state.get("input_context", {}) -- read-only
#  - Never import from mediator/, api/, or other agents

from typing import Any, ClassVar, Dict

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.caller_contract import (
    ContractError,
    screen_injection_deep,
    validate_caller_contract,
    validate_specification,
)


class PreProcessNode(FunctionNode):
    """The request boundary: validate both caller channels before domain work.

    Input validation gate: VERIFIED_EXTERNAL -- the external caller boundary;
    only authenticated callers may invoke this agent. All inner domain nodes
    run at ANONYMOUS.

    The template owns these guarantees rather than leaning on the platform's
    gates. A refusal asserted only by the platform holds only where that gate is
    active; where it is absent or configured off, the payload reaches the answer
    path and the agent returns success. So the checks below run inside
    execute(), which is reachable by calling the node directly with no framework
    wrapper in front of it, and the tests drive it that way.

    A rejection names the FIELD and never the value.
    """

    # Pre-process is the external-facing trust gate for this agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: AgentState) -> Dict[str, Any]:
        raw_input = state.get("user_input", "")
        input_context = state.get("input_context", {})  # read-only

        # The structured channel is screened for instruction payloads before it
        # is validated, KEYS included: a hostile field name is caller data
        # exactly as a hostile value is, and a \u-escaped payload is ordinary
        # text once the JSON parser has run, so the scan runs on the parsed
        # object rather than on the request body.
        family = screen_injection_deep(input_context)
        if family is not None:
            emit_trace_event(
                "pre_process_injection_detected",
                {"field": "input_context", "family": family},
                state,
            )
            return self._refuse("input_context", f"contains a disallowed instruction pattern ({family})")

        try:
            specification = validate_specification(raw_input)
        except ContractError as exc:
            emit_trace_event(
                "pre_process_validation_failed",
                {"field": exc.field, "reason": exc.reason},
                state,
            )
            return self._refuse(exc.field, exc.reason)

        try:
            contract: Dict[str, Any] = validate_caller_contract(input_context)
        except ContractError as exc:
            emit_trace_event(
                "pre_process_validation_failed",
                {"field": exc.field, "reason": exc.reason},
                state,
            )
            return self._refuse(exc.field, exc.reason)

        emit_trace_event(
            "pre_process_validated",
            {
                "input_length": len(specification),
                "contract_fields": sorted(contract),
            },
            state,
        )

        return {
            "validated_input": specification,
            "engine_spec_raw": specification,
            "caller_contract": contract,
            "status": AgentStatus.SUCCESS,
        }

    @staticmethod
    def _refuse(field: str, reason: str) -> Dict[str, Any]:
        """Build the rejection delta.

        The message carries the field name and a closed-set reason phrase. The
        rejected value is never repeated back — an error that quoted the payload
        would put it into the record that reports it.
        """
        return {
            "status": AgentStatus.ERROR,
            "error_log": [f"PreProcessNode: {field} {reason}"],
        }
