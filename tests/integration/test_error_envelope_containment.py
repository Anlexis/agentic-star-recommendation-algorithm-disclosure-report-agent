"""When the output boundary refuses, the caller must not receive what it refused.

The framework resolves a caller's output as ``formatted_output or result`` with
no status check, and the node wrapper discards the ENTIRE return value of a node
that raises. So an output gate that merely raised — which is what this template
shipped — left ``result`` untouched in state and the envelope surfaced the
un-gated document with the offending value still in it. Measured on the shipped
code before this change.

Two properties are asserted here, and they are different properties:

  * the document that failed the boundary is not published;
  * the error channel the caller sees carries closed-set labels only. Clearing
    the answer and bounding the error channel are separate; a template can do
    the first and still publish node-authored text on the second.
"""

import os

import pytest

from tests.integration.asgi import Client

TOKEN = "containment-suite-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# A specification whose extracted output actions carry a credential-shaped
# string, so the assembled report fails the boundary. The assignment form is
# used deliberately: the platform's own patterns do not match it, so the refusal
# under test is the template's, not the platform's.
LEAKY_SPEC = (
    "Our recommendation engine uses collaborative filtering. "
    "Input features: purchase history. "
    "Outputs: ranking with password=hunter2hunter2, dynamic pricing. "
    "The system is fully automated."
)
CLEAN_SPEC = (
    "Our recommendation engine uses collaborative filtering. "
    "Input features: purchase history. "
    "Outputs: personalised product ranking. "
    "The system is fully automated."
)


@pytest.fixture(scope="module", autouse=True)
def _auth_env():
    previous = os.environ.get("INVOKE_AUTH_TOKEN")
    os.environ["INVOKE_AUTH_TOKEN"] = TOKEN
    yield
    if previous is None:
        os.environ.pop("INVOKE_AUTH_TOKEN", None)
    else:
        os.environ["INVOKE_AUTH_TOKEN"] = previous


@pytest.fixture(scope="module")
def client():
    from src.api.server import app

    return Client(app)


def _values(obj):
    """Every leaf value in a JSON-like structure, as strings."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from _values(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _values(item)
    else:
        yield str(obj)


class TestTheRefusedDocumentIsNotPublished:
    def test_the_caller_receives_a_refusal_not_the_document(self, client):
        envelope = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH).json()
        assert envelope["status"] == "error"
        assert "OUTPUT WITHHELD" in str(envelope["output"])

    def test_the_offending_value_appears_nowhere_in_the_envelope(self, client):
        response = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH)
        assert "hunter2hunter2" not in response.text

    def test_the_document_itself_appears_nowhere_in_the_envelope(self, client):
        """The fallback channel, closed.

        "AI RECOMMENDATION ALGORITHM COMPLIANCE ATTESTATION" is the first line of
        the document the boundary refused. Its absence is what proves the
        framework's fallback to ``result`` cannot reach it.
        """
        response = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH)
        assert "COMPLIANCE ATTESTATION" not in response.text
        assert "APPI 2026 Disclosure Language" not in response.text

    def test_the_envelope_carries_no_traceback_and_no_source_path(self, client):
        response = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH)
        for marker in ("Traceback", "src/nodes", "src/graph", ".py", 'File "'):
            assert marker not in response.text, marker

    def test_the_replacement_notice_is_truthy(self, client):
        """A falsy formatted_output re-opens the very fallback the clearing closes."""
        envelope = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH).json()
        assert envelope["output"]

    def test_a_clean_request_is_still_published(self, client):
        """The control.

        Without it, a boundary that withheld EVERYTHING would pass every
        assertion above.
        """
        envelope = client.post("/invoke", json={"input": CLEAN_SPEC}, headers=AUTH).json()
        assert envelope["status"] == "success"
        assert "COMPLIANCE ATTESTATION" in str(envelope["output"])


class TestTheErrorChannelIsClosedSet:
    """Every caller-visible value on an error path comes from this module's constants.

    `error_log` carries node-authored text and, wherever a node interpolates a
    caught exception, upstream message text. Clearing the answer is a different
    property from bounding the error channel, so it is asserted separately.
    """

    def test_the_boundary_error_publishes_only_declared_constants(self, client):
        from src.nodes.post_process_node import (
            REASON_OUTPUT_WITHHELD,
            REASON_WORKFLOW_FAILED,
            WITHHELD_NOTICE,
            NO_REPORT_NOTICE,
        )

        envelope = client.post("/invoke", json={"input": LEAKY_SPEC}, headers=AUTH).json()
        declared = {WITHHELD_NOTICE, NO_REPORT_NOTICE, REASON_OUTPUT_WITHHELD, REASON_WORKFLOW_FAILED}
        assert str(envelope["output"]) in declared

    def test_a_sentinel_seeded_into_the_error_log_reaches_no_caller_field(self, client):
        """Drive a refusal with a recognisable string in the internal channel.

        The refusal path below writes to error_log; the assertion walks every
        leaf of the response, so a projection added later — at any nesting depth
        — fails here rather than shipping.
        """
        sentinel = "upstream said {'customer':'A. Tanaka'}"
        from src.nodes.post_process_node import PostProcessNode

        delta = PostProcessNode().execute(
            {
                "user_input": "x",
                "error_log": [sentinel],
                "attestation_doc": "",
                "node_history": [],
                "correlation_id": "c",
                "session_id": "s",
            }
        )
        assert sentinel not in str(delta)
        assert all(sentinel not in value for value in _values(delta))

    def test_the_violation_label_is_a_pattern_name_not_the_matched_text(self, client):
        from src.nodes.post_process_node import PostProcessNode

        delta = PostProcessNode().execute(
            {
                "user_input": "x",
                "error_log": [],
                "attestation_doc": "token: abcdefghijkl",
                "ai_act_checklist": {},
                "data_gov_gaps": [],
                "node_history": [],
                "correlation_id": "c",
                "session_id": "s",
            }
        )
        assert delta["error_log"] == ["output_withheld_at_boundary:credential_assignment"]
        assert "abcdefghijkl" not in str(delta)

    def test_every_output_bearing_field_is_cleared(self, client):
        from src.nodes.post_process_node import OUTPUT_BEARING_FIELDS, PostProcessNode, WITHHELD_NOTICE

        delta = PostProcessNode().execute(
            {
                "user_input": "x",
                "error_log": [],
                "attestation_doc": "AKIA1234567890ABCDEF",
                "disclosure_language_ja": "JA",
                "disclosure_language_en": "EN",
                "ai_act_checklist": {},
                "data_gov_gaps": [],
                "node_history": [],
                "correlation_id": "c",
                "session_id": "s",
            }
        )
        for field in OUTPUT_BEARING_FIELDS:
            assert field in delta, field
        assert delta["formatted_output"] == WITHHELD_NOTICE
        assert delta["result"] == WITHHELD_NOTICE
        assert delta["attestation_doc"] is None
        assert delta["disclosure_language_ja"] is None
        assert delta["disclosure_language_en"] is None


class TestTheEnvelopeNeverFallsBackOnFailure:
    """The other half of the containment, in the graph rather than in the node.

    Not every failing path reaches the output boundary: the backbone routes a
    non-success main straight to finalize, past it. Those paths are contained by
    the graph's own envelope, which never resolves a non-success status onto
    ``result``.
    """

    def test_a_non_success_status_never_surfaces_result(self):
        from framework.schemas.agent_status import AgentStatus
        from src.graph.graph import RecommendationAlgorithmDisclosureAgent

        agent = RecommendationAlgorithmDisclosureAgent()
        leaked = "INNER DOCUMENT THAT MUST NOT SHIP"
        envelope = agent.get_output(
            {
                "status": AgentStatus.ERROR.value,
                "result": leaked,
                "formatted_output": None,
                "node_history": [],
            }
        )
        assert envelope["output"] is None
        assert leaked not in str(envelope)

    def test_a_success_status_still_surfaces_the_report(self):
        from framework.schemas.agent_status import AgentStatus
        from src.graph.graph import RecommendationAlgorithmDisclosureAgent

        agent = RecommendationAlgorithmDisclosureAgent()
        envelope = agent.get_output(
            {
                "status": AgentStatus.SUCCESS.value,
                "result": "REPORT",
                "formatted_output": "REPORT",
                "node_history": [],
            }
        )
        assert envelope["output"] == "REPORT"
