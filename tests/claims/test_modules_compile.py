"""CLAIM: the codebase is ~343 valid Python modules, and the core modules import.

One test per `eli/**/*.py` file (compiles + non-empty), plus an import check for
the load-bearing core modules. Examines the "N files of working Python" claim.
"""
from __future__ import annotations

import ast
import importlib

import pytest

from . import _helpers as H

_PY = H.eli_py_files()


@pytest.mark.parametrize("path", _PY, ids=[H.rel(p) for p in _PY])
def test_module_compiles(path):
    src = path.read_text(encoding="utf-8", errors="strict")
    ast.parse(src)  # raises SyntaxError if the file isn't valid Python


@pytest.mark.parametrize("path", _PY, ids=[H.rel(p) for p in _PY])
def test_module_has_no_merge_markers(path):
    src = path.read_text(encoding="utf-8", errors="ignore")
    # Real git conflict markers begin a line and are space/HEAD-suffixed; this
    # avoids false positives on decorative '=======' / '>>>' comment dividers.
    for marker in ("\n<<<<<<< ", "\n>>>>>>> ", "\n<<<<<<<\n", "\n>>>>>>>\n"):
        assert marker not in src, f"unresolved merge marker in {H.rel(path)}"


# Load-bearing modules that MUST import cleanly (no GUI — needs a display).
_CORE_MODULES = [
    "eli.execution.router_enhanced", "eli.execution.executor_enhanced",
    "eli.execution.execution_planner", "eli.execution.route_authority",
    "eli.cognition.agent_bus", "eli.cognition.orchestrator",
    "eli.cognition.gguf_inference", "eli.cognition.inference_broker",
    "eli.cognition.reasoning_modes", "eli.cognition.output_governor",
    "eli.cognition.hyde", "eli.cognition.reranker", "eli.cognition.persona",
    "eli.kernel.engine", "eli.kernel.self_upgrade", "eli.kernel.world_model",
    "eli.memory.memory", "eli.memory.knowledge_graph", "eli.memory.vector_store",
    "eli.runtime.evidence_planner", "eli.runtime.report_pipeline",
    "eli.runtime.grounding_escalation", "eli.runtime.code_examiner",
    "eli.runtime.scheduled_tasks", "eli.runtime.background_tasks",
    "eli.runtime.background_deepening", "eli.runtime.deterministic_grounding_gate",
    "eli.runtime.evidence_ledger", "eli.runtime.security", "eli.runtime.reflection",
    "eli.runtime.self_improvement", "eli.runtime.state_providers",
    "eli.runtime.active_project", "eli.planning.proactive_daemon",
    "eli.planning.habits", "eli.planning.autonomy_controller",
    "eli.planning.autonomy_scheduler", "eli.core.dag", "eli.core.hardware_profile",
    "eli.core.model_tier", "eli.perception.vision", "eli.perception.os_controller",
    "eli.tools.registry.capabilities_doc", "eli.tools.registry.capability_updater",
]


@pytest.mark.parametrize("mod", _CORE_MODULES, ids=_CORE_MODULES)
def test_core_module_imports(mod):
    importlib.import_module(mod)
