"""ELI MKXI GUI panel components.

Re-exports all public panel classes so callers can do:
    from eli.gui.panels import HardwareTuningDock, FirstBootWizard, ...
"""
from eli.gui.panels.startup import HardwareTuningDock, StartupModelSelectionDialog, FirstBootWizard
from eli.gui.panels.agent_wizard import AgentEditDialog
from eli.gui.panels.settings import AdvancedSettingsDialog

__all__ = [
    "HardwareTuningDock",
    "StartupModelSelectionDialog",
    "FirstBootWizard",
    "AgentEditDialog",
    "AdvancedSettingsDialog",
]
