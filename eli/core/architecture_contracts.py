"""Authoritative ownership map for the live ELI runtime."""

TURN_FACADE_MODULE = "eli.kernel.engine"
TURN_ORCHESTRATOR_MODULE = "eli.cognition.orchestrator"
ACTION_EXECUTOR_MODULE = "eli.execution.executor_enhanced"
REPAIR_OWNER_MODULE = "eli.runtime.grounded_remediation"
MEMORY_OWNER_MODULE = "eli.memory.memory"
GUI_PRIMARY_MODULE = "eli.gui.eli_pro_audio_gui_MKI"
GUI_OPTIONAL_MODULES = ()

PROPOSAL_ONLY_MODULE_PREFIXES = (
    "eli.brain.awareness",
    "eli.brain.proactive",
    "eli.brain.reflection",
)

SOURCE_MUTATION_OWNER_MODULES = {
    REPAIR_OWNER_MODULE,
}
