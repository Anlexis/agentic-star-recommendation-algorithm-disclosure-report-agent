"""AgentCore Platform v1.0"""

# Caller-request bridge across the outer/inner graph boundary.
#
# Why it exists: the framework invokes a nested graph as
# `subgraph.invoke(user_input, session_id=..., ctx=...)`. Only the request
# STRING crosses. Neither the outer state nor the caller's structured
# invocation parameters are forwarded, so anything the outer pre_process
# produced is invisible to the inner pipeline.
#
# That gap was not theoretical here. Four of the ten AI Act checklist items and
# five of the seven governance gap checks read their evidence from a state key
# the inner graph never receives, so they reported the SAME result for every
# specification: a run whose text documented human oversight, performance
# metrics, risk mitigation and an audit plan produced a byte-identical checklist
# to one that documented none of them.
#
# Two sanctioned subclass hooks bridge it:
#
#   DisclosureWorkflowGraphNode.extract_input(state)   [BEFORE subgraph.invoke]
#       -> set_caller_request(<validated specification>, <validated contract>)
#   DomainWorkflowGraph._extra_initial_state()         [INSIDE subgraph.invoke]
#       -> seeds both into the inner state
#
# What crosses is the VALIDATED request only: the specification has already
# passed its size bound and injection screen, and every contract field has
# already been checked against a closed set, an inert alphabet or a finite
# range. The raw request body never travels.
#
# A ContextVar keeps the hand-off correct per thread and per task, so concurrent
# invocations inside one process cannot see each other's request.

from contextvars import ContextVar
from typing import Any, Dict, Optional, Tuple

_CALLER_REQUEST: ContextVar[Optional[Tuple[str, Dict[str, Any]]]] = ContextVar(
    "ret_c2_342_caller_request", default=None
)


def set_caller_request(specification: str, contract: Optional[Dict[str, Any]]) -> None:
    """Stash the validated request for the imminent inner-graph invoke."""
    _CALLER_REQUEST.set((specification or "", dict(contract) if contract else {}))


def get_caller_request() -> Tuple[str, Dict[str, Any]]:
    """Read (without consuming) the stashed request; empty values when none."""
    stashed = _CALLER_REQUEST.get()
    if not stashed:
        return "", {}
    specification, contract = stashed
    return specification, dict(contract)


def clear_caller_request() -> None:
    """Drop the stashed request. Used by tests to prove the seeding is real."""
    _CALLER_REQUEST.set(None)
