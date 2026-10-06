"""The committed deployment payload must satisfy the entry contract.

The deployment smoke step posts `deploy/invoke_payload.json` verbatim. That step
tolerates a failure, so a payload the agent refuses leaves a green pipeline:
the request is well-formed HTTP, the response is valid JSON, and the only record
of the refusal is `status: error` inside a body nothing asserts on. A payload
that has drifted away from the entry contract is therefore invisible until
someone opens the job by hand.

So the payload is driven through the real application here, and its request
string is held to the suite's own fixture rather than re-typed — the two cannot
drift apart if they are the same value.
"""

import json
import os
from pathlib import Path

import pytest

from tests.integration.asgi import Client
from tests.integration.test_invoke_end_to_end import BARE_SPEC

TOKEN = "payload-suite-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_PAYLOAD_PATH = Path(__file__).resolve().parents[2] / "deploy" / "invoke_payload.json"


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


@pytest.fixture(scope="module")
def payload():
    return json.loads(_PAYLOAD_PATH.read_text())


def test_the_payload_exists_and_is_valid_json(payload):
    assert payload["input"]


def test_the_payload_request_string_is_the_suite_fixture(payload):
    """Payload and tests assert the same contract, or they assert nothing."""
    assert payload["input"] == BARE_SPEC


def test_the_payload_is_accepted_and_produces_a_report(client, payload):
    response = client.post("/invoke", json=payload, headers=AUTH)
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["status"] == "success", "the deployment payload is refused by the agent"
    assert "AI Recommendation Algorithm Disclosure" in str(envelope["output"])


def test_a_payload_the_entry_contract_refuses_would_fail_this_check(client):
    """The other direction — without it, a check that always passed would look identical.

    An empty request string is the shape a placeholder payload takes, and it is
    refused. That the assertion above passes therefore says something.
    """
    response = client.post("/invoke", json={"input": "   ", "session_id": "x"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "error"
