"""The output boundary, probed in both directions.

The stated invariant of this template's released report: nothing
credential-shaped and no direct personal identifier leaves the agent.

Both directions are asserted, because only one of them is about security. The
block list proves the gate sees what it must; the pass list proves it does not
refuse the agent's own ordinary output — a gate that withholds every legitimate
compliance report is not a strict gate, it is an outage.
"""

import pytest

from src.nodes.post_process_node import security_gate_output

# Values that must never leave the agent. The first six are the platform's own
# credential formats; the next five are assignment forms the platform's patterns
# do not match, which is why the local set is kept alongside rather than
# replaced by it. The rest are direct personal identifiers.
#
# Every secret below announces itself as synthetic — "example", an alphabet run,
# a digit run. That is not decoration: the committed-credential gate reports a
# credential embedded in a URL even in test code, and it is right to, because
# "it is only a fixture" is exactly the reasoning that once kept a real token
# invisible in a test file. A fixture whose value is unmistakably fake satisfies
# the gate on the evidence of the value itself rather than on a claim about it.
MUST_BLOCK = [
    ("aws key", "AKIA1234567890ABCDEF"),
    ("openai key", "sk-abcdefghijklmnopqrstuvwx"),
    ("stripe key", "sk_live_abcdefghijklmnop12"),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.sig"),
    ("connection string", "postgresql://user:example0123456789secret@host/db"),
    ("bearer header", "Authorization: Bearer abcdef0123456789abcdef"),
    ("password assignment", "password=hunter2hunter2"),
    ("passwd colon form", "passwd: hunter2hunter2"),
    ("compound stem", "secret_token=xyzxyzxyz"),
    ("underscore-prefixed name", "x_api_key=abcdefghijkl"),
    ("client secret", "client_secret=abcdefghijkl"),
    ("private key block", "-----BEGIN RSA PRIVATE KEY-----"),
    ("email", "operator contact alice@example.com"),
    ("japanese phone", "phone 090-1234-5678"),
    ("resident number, spaced", "My Number 1234-5678-9012"),
    ("resident number, unspaced japanese", "個人番号1234-5678-9012を確認"),
    ("resident number, no separators", "個人番号123456789012を確認"),
    ("card number", "card 4111 1111 1111 1111"),
]

# Text the agent's own report actually contains, plus specification prose an
# operator legitimately sends. Every one of these must survive.
MUST_PASS = [
    ("attestation status line", "Overall Compliance Status: COMPLIANT"),
    ("percentage", "Compliance Rate:        60%"),
    ("iso date", "Date of Assessment:     2026-09-14"),
    ("count", "Total Gaps Identified:  7"),
    ("requirement id", "  - AIA-DOC-01"),
    ("fraction", "Requirements Met:       6/10"),
    ("tokenization prose", "tokenization: sentencepiece is used for the text encoder"),
    ("access control prose", "Access control is RBAC restricted to the data science role."),
    ("rationale line", "Rationale: Specification references personal data categories (purchase_history)."),
    ("statute heading", "APPI 2026 (Art. 24-bis) + Japan AI Act (enacted 2025, operationalised 2026)"),
    ("the word secret in prose", "The secret sauce of the ranking model is documented internally"),
    ("grouped number", "100,000,000 impressions per month"),
    ("ratio", "a score of 0.15 across the evaluation set"),
    ("section mark", "§3 of the operator's privacy policy"),
    ("future date", "annual third-party review scheduled for 2027-01-01"),
]


@pytest.mark.parametrize("label,value", MUST_BLOCK, ids=[label for label, _ in MUST_BLOCK])
def test_the_boundary_refuses(label, value):
    assert security_gate_output(value) is not None


@pytest.mark.parametrize("label,value", MUST_PASS, ids=[label for label, _ in MUST_PASS])
def test_the_boundary_releases_legitimate_output(label, value):
    assert security_gate_output(value) is None


def test_the_scan_walks_nested_structures():
    """Caller-derived text rides inside nested mappings and lists.

    A gate that looked only at top-level strings reports zero findings on a
    payload whose leak sits one level down, and reads as clean. The top-level
    control alongside it is what distinguishes "the gate is blind" from "the
    probe is wrong".
    """
    assert security_gate_output({"data_gov_gaps": [{"description": "AKIA1234567890ABCDEF"}]}) is not None
    assert security_gate_output("AKIA1234567890ABCDEF") is not None
    assert security_gate_output({"data_gov_gaps": [{"description": "no retention policy found"}]}) is None


def test_non_text_leaves_are_not_scanned_as_text():
    """Counts and flags are structural, not content."""
    assert security_gate_output({"compliant_count": 6, "critical": True, "rate": 0.6}) is None


def test_the_finding_never_carries_the_matched_text():
    """A violation report that quoted the value would be the leak."""
    finding = security_gate_output("password=hunter2hunter2")
    assert finding is not None
    assert "hunter2" not in finding


def test_the_personal_name_heuristic_is_not_used_on_the_report():
    """Deliberate exclusion, with a measured reason.

    The platform's personal-data detector reads any two consecutive title-case
    words as a personal name: on this template's own clean report it returns 26
    findings — "Compliance Report", "Privacy Policy", "Total Gaps Identified".
    Feeding the report through that class would refuse every legitimate
    response. The structured identifier types are used instead; this test pins
    the decision so a later "tighten the gate" change has to face it explicitly.
    """
    from framework.security.pii_detector import detect_pii

    heading = "Total Gaps Identified:  7"
    assert any(f["type"] == "name" for f in detect_pii(heading))
    assert security_gate_output(heading) is None
