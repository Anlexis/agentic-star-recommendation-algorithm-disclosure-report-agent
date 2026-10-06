# The identity the entry point provisions secrets under, against the identity
# the manifest declares.
#
# The manifest is the source of truth for who this agent is. The secret provider
# is scoped by that identity: it reads `env/namespaces/{namespace}/.env.{env}`
# and `env/agents/{namespace}/{agent_name}/.env.{env}`. Under the registry the
# scope comes from `config/agent.yaml`; standalone it comes from whatever
# `src/api/server.py` passes to the factory. When those two disagree, one
# agent's secrets live in two stores and a key provisioned for the registry
# deployment is simply absent in the standalone one — with no error at boot,
# because a missing tier file is ignored by design. Nothing fails until a secret
# is declared, and then it fails in only one of the two deployments.
#
# This repository had exactly that drift: the entry point passed the lowercased
# template id while the manifest declares the industry code.
#
# Both sides are READ here, never restated: the manifest is parsed from
# config/agent.yaml, and the entry point's identity is taken from the provider
# the module actually provisioned on the agent. A test that spelled the expected
# namespace out twice would keep passing through exactly the drift it exists to
# catch.
#
# The direction of the alignment is pinned too. `namespace:` is
# `lower(industry_code)` — the manifest's own `industry` field, lowercased. Both
# facts are checked, so re-aligning the wrong way (moving the manifest onto the
# entry point's value instead of the reverse) fails here rather than passing as
# a fix.
#
# Deterministic — no model, no network, no filesystem beyond the manifest.

from pathlib import Path

from framework.utils.config_loader import load_config

from src.api.server import agent

# tests/integration/<this file> -> parents[2] is the repository root.
_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "config" / "agent.yaml"
_MANIFEST = load_config(str(_MANIFEST_PATH))

# The provider the entry point bound at import time — the identity that is live
# in a standalone deployment, not a re-derivation of it.
_PROVISIONED = agent._secrets_provider


def test_manifest_declares_the_identity_fields() -> None:
    """The fields the comparisons below rest on must be present.

    Without this, a manifest that lost `namespace:` would make every comparison
    below `None == None` and the file would pass while asserting nothing.
    """
    assert _MANIFEST.get("namespace"), f"{_MANIFEST_PATH} declares no namespace"
    assert _MANIFEST.get("name"), f"{_MANIFEST_PATH} declares no name"
    assert _MANIFEST.get("industry"), f"{_MANIFEST_PATH} declares no industry"


def test_provisioned_namespace_matches_the_manifest() -> None:
    assert _PROVISIONED._namespace == _MANIFEST["namespace"], (
        "src/api/server.py provisions secrets under namespace "
        f"{_PROVISIONED._namespace!r}, but config/agent.yaml declares "
        f"{_MANIFEST['namespace']!r}. A secret would resolve from a different "
        "store standalone than under the registry."
    )


def test_provisioned_agent_name_matches_the_manifest() -> None:
    assert _PROVISIONED._agent_name == _MANIFEST["name"], (
        "src/api/server.py provisions secrets for agent name "
        f"{_PROVISIONED._agent_name!r}, but config/agent.yaml declares "
        f"{_MANIFEST['name']!r}."
    )


def test_manifest_namespace_is_lower_industry() -> None:
    """`namespace:` is `lower(industry_code)` — the fleet-wide convention.

    Checked against the manifest's own `industry` field, so this pins which of
    the two values is the correct one to align on without hard-coding either.
    """
    assert _MANIFEST["namespace"] == _MANIFEST["industry"].lower(), (
        f"config/agent.yaml declares namespace {_MANIFEST['namespace']!r}; the "
        f"convention is lower(industry) = {_MANIFEST['industry'].lower()!r}."
    )


def test_manifest_entry_point_resolves_to_the_class_the_entry_point_imports() -> None:
    """The dotted entry point must name the class actually served.

    A manifest that points at a class nobody instantiates fails only under the
    registry, which is the deployment this repository is least able to observe.
    """
    import importlib

    dotted = _MANIFEST["class"]
    module_path, _, class_name = dotted.rpartition(".")
    resolved = getattr(importlib.import_module(module_path), class_name)
    assert isinstance(agent, resolved), (
        f"config/agent.yaml resolves to {dotted}, which is not the class "
        f"src/api/server.py serves ({type(agent).__name__})."
    )
