"""
test_00_imports.py
==================
Parametrised import test for EVERY Python module in the eli package.
If a module can't be imported its error is shown; the rest keep running.

Run:  pytest tests/test_00_imports.py -v
"""
import importlib
import pytest

# ── Complete module list derived from `tree` output ───────────────────────────
ALL_MODULES = [
    # ── cognition ──────────────────────────────────────────────────────────────
    "eli.cognition",
    "eli.cognition.agent_bus",
    "eli.cognition.chat_model",
    "eli.cognition.context_builder",
    "eli.cognition.context_synthesiser",
    "eli.cognition.engagement_tracker",
    "eli.cognition.gguf_inference",
    "eli.cognition.hyde",
    "eli.cognition.inference_broker",
    "eli.cognition.introspection_agent",
    "eli.cognition.llm_intent",
    "eli.cognition.orchestrator",
    "eli.cognition.output_governor",
    "eli.cognition.persona",
    "eli.cognition.persona_hygiene",
    "eli.cognition.persona_status",
    "eli.cognition.persona_updater",
    "eli.cognition.persona_values",
    "eli.cognition.reranker",
    "eli.cognition.response_governance",
    "eli.cognition.response_sanitizer",
    "eli.cognition.user_info_builder",
    # eli.cognition.working_memory — deleted module, removed from list
    # ── core ──────────────────────────────────────────────────────────────────
    "eli.core",
    "eli.core.architecture_contracts",
    "eli.core.compatibility",
    "eli.core.config",
    "eli.core.db_paths",
    "eli.core.first_run",
    "eli.core.first_run_wizard",
    "eli.core.hardware_profile",
    "eli.core.legacy_paths",
    "eli.core.paths",
    "eli.core.portable_paths",
    "eli.core.runtime_settings",
    # ── execution ─────────────────────────────────────────────────────────────
    "eli.execution",
    "eli.execution.execution_intent_packets",
    "eli.execution.execution_planner",
    "eli.execution.executor_enhanced",
    "eli.execution.executor_plugin_handlers",
    "eli.execution.operator_actions",
    "eli.execution.operator_policy",
    "eli.execution.route_authority",
    "eli.execution.router_enhanced",
    "eli.execution.router_plugin_intents",
    "eli.execution.tool_execution_authority",
    # ── gui ───────────────────────────────────────────────────────────────────
    "eli.gui",
    "eli.gui.app",
    "eli.gui.qt_compat",
    "eli.gui.docks",
    "eli.gui.docks.operator_console_dock",
    "eli.gui.docks.proactive_dock",
    "eli.gui.widgets",
    "eli.gui.widgets.ollama_model_selector",
    # ── integrations ──────────────────────────────────────────────────────────
    "eli.integrations",
    "eli.integrations.local_gguf",
    "eli.integrations.local_gguf.config",
    "eli.integrations.local_gguf.inference",
    "eli.integrations.local_gguf.paths",
    "eli.integrations.mpris",
    "eli.integrations.mpris.playerctl_backend",
    "eli.integrations.ollama",
    "eli.integrations.ollama.client",
    # ── kernel ────────────────────────────────────────────────────────────────
    "eli.kernel",
    "eli.kernel.engine",
    "eli.kernel.pipeline",
    "eli.kernel.scheduler",
    "eli.kernel.self_upgrade",
    "eli.kernel.state",
    "eli.kernel.task_bus",
    # eli.kernel.verify_dual_models — module does not exist (stale entry), removed 2026-06-01
    "eli.kernel.world_model",
    # ── memory ────────────────────────────────────────────────────────────────
    "eli.memory",
    # eli.memory.db_paths — module does not exist (stale entry; use eli.core.db_paths), removed 2026-06-01
    "eli.memory.habits_memory_db",
    "eli.memory.habits_memory_service",
    "eli.memory.knowledge_graph",
    "eli.memory.memory_adapter",
    "eli.memory.memory",
    "eli.memory.memory_service",
    "eli.memory.populate_memories",
    "eli.memory.sqlite_memory",
    "eli.memory.stores",
    "eli.memory.system_index",
    "eli.memory.vector_store",
    # eli.memory.working_memory — deleted module, removed from list
    # ── perception ────────────────────────────────────────────────────────────
    "eli.perception",
    "eli.perception.analyze_csv",
    "eli.perception.analyze_image",
    "eli.perception.analyze_mesh",
    "eli.perception.analyze_pdfs",
    "eli.perception.audio_stt",
    "eli.perception.eli_listen",
    "eli.perception.extract_equations",
    "eli.perception.log_rotation",
    "eli.perception.os_controller",
    "eli.perception.tts_router",
    "eli.perception.voice_worker",
    "eli.perception.voice_worker_streaming",
    # ── planning ──────────────────────────────────────────────────────────────
    "eli.planning",
    "eli.planning.agent_loop",
    "eli.planning.attention_queue",
    "eli.planning.autonomy_controller",
    "eli.planning.autonomy_scheduler",
    # eli.planning.db_paths — module does not exist (stale entry; use eli.core.db_paths), removed 2026-06-01
    "eli.planning.goal_models",
    "eli.planning.goal_store",
    "eli.planning.goal_tick",
    "eli.planning.habits",
    "eli.planning.habits_scheduler",
    "eli.planning.habits_state",
    "eli.planning.jobq",
    "eli.planning.jobqueue",
    "eli.planning.jobqueue_cli",
    "eli.planning.operator_goal_actions",
    "eli.planning.proactive_daemon",
    "eli.planning.proposal_adapters",
    "eli.planning.proposal_memory_bridge",
    "eli.planning.proposal_models",
    "eli.planning.proposal_queue",
    "eli.planning.task_planner",
    # ── plugins ───────────────────────────────────────────────────────────────
    "eli.plugins",
    "eli.plugins.base",
    "eli.plugins.base.base",
    "eli.plugins.manager",
    "eli.plugins.calendar",
    "eli.plugins.calendar.plugin",
    "eli.plugins.document_reader",
    "eli.plugins.document_reader.plugin",
    "eli.plugins.media",
    "eli.plugins.media.plugin",
    "eli.plugins.notes",
    "eli.plugins.notes.plugin",
    "eli.plugins.pomodoro",
    "eli.plugins.pomodoro.plugin",
    "eli.plugins.smart_home",
    "eli.plugins.smart_home.plugin",
    "eli.plugins.system_stats",
    "eli.plugins.system_stats.plugin",
    "eli.plugins.tts",
    "eli.plugins.tts.plugin",
    "eli.plugins.weather",
    "eli.plugins.weather.plugin",
    "eli.plugins.web",
    "eli.plugins.web.plugin",
    "eli.plugins.web_automation",
    "eli.plugins.web_automation.plugin",
    # ── runtime ───────────────────────────────────────────────────────────────
    "eli.runtime",
    "eli.runtime.approval_engine",
    "eli.runtime.authority_gate",
    "eli.runtime.authority_state",
    "eli.runtime.auth",
    "eli.runtime.awareness_boot",
    "eli.runtime.capability_sync",
    "eli.runtime.code_monitor",
    "eli.runtime.control_contracts",
    # eli.runtime.eli_agent — module does not exist (stale entry), removed 2026-06-01
    "eli.runtime.evidence_arbitration",
    "eli.runtime.evidence_store",
    "eli.runtime.fastpath_responder",
    "eli.runtime.final_response_assembly",
    "eli.runtime.final_response_provider",
    "eli.runtime.grounded_remediation",
    "eli.runtime.identity_guard",
    "eli.runtime.incident_log",
    "eli.runtime.last_trace",
    "eli.runtime.live_introspection",
    "eli.runtime.memory_evidence",
    "eli.runtime.operator_feed",
    "eli.runtime.operator_feed_normalized",
    "eli.runtime.operator_state",
    "eli.runtime.packet_native_downstream",
    "eli.runtime.persistence_gate",
    "eli.runtime.personal_memory_surface",
    "eli.runtime.pipeline_models",
    "eli.runtime.profile_extractor",
    "eli.runtime.reflection",
    "eli.runtime.repair_policy",
    "eli.runtime.response_contracts",
    "eli.runtime.response_packets",
    "eli.runtime.response_policy",
    "eli.runtime.retrieval_packets",
    "eli.runtime.route_authority",
    "eli.runtime.security",
    "eli.runtime.self_improvement",
    "eli.runtime.self_model_refresh",
    "eli.runtime.single_pass_authority",
    "eli.runtime.stage_packets",
    "eli.runtime.stage_packet_store",
    "eli.runtime.tool_result_models",
    "eli.runtime.tool_result_normalizer",
    "eli.runtime.tool_result_store",
    "eli.runtime.typed_stage_bridge",
    # ── tools ─────────────────────────────────────────────────────────────────
    "eli.tools",
    "eli.tools.image_engine",
    "eli.tools.media",
    "eli.tools.news",
    "eli.tools.news.news_fetcher",
    "eli.tools.registry",
    "eli.tools.registry.capabilities",
    "eli.tools.registry.capability_registry",
    "eli.tools.registry.capability_updater",
    # ── utils ─────────────────────────────────────────────────────────────────
    "eli.utils",
    "eli.utils.platform_compat",
    # ── top-level ─────────────────────────────────────────────────────────────
    "eli",
]


@pytest.mark.parametrize("module_path", ALL_MODULES, ids=ALL_MODULES)
def test_module_imports(module_path):
    """Every eli module must be importable without raising exceptions."""
    try:
        mod = importlib.import_module(module_path)
        assert mod is not None, f"{module_path} imported as None"
    except ImportError as exc:
        pytest.fail(f"ImportError in {module_path}: {exc}")
    except Exception as exc:
        pytest.fail(f"Unexpected error in {module_path}: {type(exc).__name__}: {exc}")


def test_import_count():
    """Sanity: we are testing the expected number of modules."""
    assert len(ALL_MODULES) >= 120, "Module list seems incomplete"
