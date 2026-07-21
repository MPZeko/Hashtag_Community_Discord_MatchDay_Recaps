from pathlib import Path


def test_actions_use_node_24_compatible_versions():
    workflows = [
        Path(".github/workflows/match-recap.yml").read_text(),
        Path(".github/workflows/tests.yml").read_text(),
    ]
    combined = "\n".join(workflows)
    assert "actions/checkout@v5" in combined
    assert "actions/setup-python@v6" in combined
    assert "actions/checkout@v4" not in combined
    assert "actions/setup-python@v5" not in combined
    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in combined
