"""
test_11_integration.py
======================
Cross-layer wiring smoke tests. Verifies that key modules can reference
each other without circular imports, attribute errors or missing symbols.
These do NOT start actual inference — they only validate the import graph
and public API surface.
"""
import importlib
import pytest


# ── Cross-layer connectivity checks ───────────────────────────────────────────

# (removed test_wire_cognition_to_memory — tested the deleted eli.memory.working_memory)


def test_wire_runtime_to_cognition():
    """Runtime entry and cognition orchestrator importable together."""
    # eli.runtime.eli_agent was removed; the runtime entry is now eli.cli.headless
    # (which drives CognitiveEngine). Verify it loads alongside the orchestrator.
    runtime = importlib.import_module("eli.cli.headless")
    orch  = importlib.import_module("eli.cognition.orchestrator")
    assert runtime and orch


def test_wire_planning_to_memory():
    """Proactive daemon and proposal memory bridge can load together."""
    daemon = importlib.import_module("eli.planning.proactive_daemon")
    bridge = importlib.import_module("eli.planning.proposal_memory_bridge")
    assert daemon and bridge


def test_wire_execution_to_runtime():
    """Route authority stubs in execution and runtime must coexist."""
    exec_ra    = importlib.import_module("eli.execution.route_authority")
    runtime_ra = importlib.import_module("eli.runtime.route_authority")
    assert exec_ra and runtime_ra


def test_wire_kernel_engine_to_pipeline():
    engine   = importlib.import_module("eli.kernel.engine")
    pipeline = importlib.import_module("eli.kernel.pipeline")
    assert engine and pipeline


def test_wire_plugins_to_manager():
    manager  = importlib.import_module("eli.plugins.manager")
    calendar = importlib.import_module("eli.plugins.calendar.plugin")
    weather  = importlib.import_module("eli.plugins.weather.plugin")
    assert manager and calendar and weather


def test_wire_capability_registry_json_parseable():
    """Capability manifest JSON must be valid."""
    import json, os
    manifest = os.path.join(
        os.path.dirname(importlib.import_module("eli").__file__),
        "capability_manifest.json",
    )
    if os.path.isfile(manifest):
        with open(manifest) as f:
            data = json.load(f)
        assert isinstance(data, (dict, list))
    else:
        pytest.skip("capability_manifest.json not found")


def test_wire_generated_capability_inventory_parseable():
    """Generated capability inventory JSON must be valid."""
    import json, os
    inv = os.path.join(
        os.path.dirname(importlib.import_module("eli").__file__),
        "capability_inventory.generated.json",
    )
    if os.path.isfile(inv):
        with open(inv) as f:
            data = json.load(f)
        assert isinstance(data, (dict, list))
    else:
        pytest.skip("capability_inventory.generated.json not found")


def test_wire_persona_txt_exists():
    """Persona definition text file must exist alongside persona.py."""
    import os
    persona_txt = os.path.join(
        os.path.dirname(importlib.import_module("eli.cognition.persona").__file__),
        "persona.txt",
    )
    assert os.path.isfile(persona_txt), f"persona.txt missing at {persona_txt}"


def test_wire_top_level_main_importable():
    """eli.__main__ must be importable."""
    main = importlib.import_module("eli.__main__")
    assert main is not None


def test_wire_all_layers_no_crash():
    """Import every layer package in one shot to surface any latent circular dep."""
    layers = [
        "eli", "eli.core", "eli.cognition", "eli.memory",
        "eli.execution", "eli.planning", "eli.runtime",
        "eli.kernel", "eli.perception", "eli.plugins",
        "eli.tools", "eli.utils", "eli.integrations",
    ]
    for layer in layers:
        mod = importlib.import_module(layer)
        assert mod is not None, f"{layer} returned None"
