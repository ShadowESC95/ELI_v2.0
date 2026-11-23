"""Every place ELI keeps state, for a test run: one folder holds all of it.

The suite conftest puts it in the run's throwaway sandbox (outside the checkout) and checks it with
`outside()`. Only some stores used to be moved there, one variable at a time: ELI's config folder
stayed this checkout's own, so a test that said "my name is Sam" to an engine wrote that name into
the owner's config/settings.json, and data_dir() stayed the checkout's artifacts/, where the user
profile under runtime/users was rewritten. (The approach of ELI v3's tests/_state_env.py.)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict


def state_env(root: Path) -> Dict[str, str]:
    """The environment that puts every store under `root`."""
    root = Path(root)
    db = root / "db"
    return {
        # data_dir() holds the conversations, proactive and runtime state (runtime/users included),
        # documents, scripts and databases; config_dir() the settings, the owner's id and the small
        # settings files; learning_dir() training runs; cache_dir() caches.
        "ELI_ARTIFACTS_DIR": str(root),
        "ELI_DATA_DIR": str(root),
        "ELI_CONFIG_DIR": str(root / "config"),
        "ELI_LEARNING_DIR": str(root / "training"),
        "ELI_CACHE_DIR": str(root / "cache"),
        "ELI_PLUGINS_DIR": str(root / "plugins"),        # downloaded plugins (manager._plugins_dir)
        # the user DB is resolved by user_db_path(), which honours ELI_USER_DB/ELI_MEMORY_DB before
        # anything else; the agent DB by ELI_AGENT_DB first
        "ELI_USER_DB": str(db / "user.sqlite3"),
        "ELI_MEMORY_DB": str(db / "user.sqlite3"),
        "ELI_DB_DIR": str(db),
        "ELI_AGENT_DB": str(db / "agent.sqlite3"),
        # persona_auto_path(), notebook_dir() and notes_dir() have their own overrides
        "ELI_PERSONA_AUTO_PATH": str(root / "persona.auto.txt"),
        "ELI_NOTEBOOK_DIR": str(root / "eli_notebook"),
        "ELI_NOTES_DIR": str(root / "eli_notes"),
        # the world (storage.WORLD_DIR is fixed when that module is imported, so this comes first)
        "ELI_WORLD_DIR": str(root / "world"),
        "ELI_LAST_TRACE_PATH": str(root / "last_trace.json"),
        # the audit chain, the capability state and the HMAC key the chain is signed with
        "ELI_ORCHESTRATOR_AUDIT_DB": str(db / "orchestrator_audit.sqlite3"),
        "ELI_CAPABILITY_STATE_DB": str(db / "capability_state.sqlite3"),
        "ELI_AUDIT_HMAC_KEY": "eli-pytest-audit-key-not-a-real-secret",
        "ELI_DOCUMENT_INDEX_DB": str(db / "documents.sqlite3"),
        # the agenda (calendar and reminders): a DB, an .ics file, and no desktop notifications
        "ELI_AGENDA_DB": str(db / "agenda.sqlite3"),
        "ELI_CALENDAR_FILE": str(root / "calendar.ics"),
        "ELI_AGENDA_NOTIFY": "0",
        # nor this machine's settings (Net toggle, Full Control, model paths)
        "ELI_SETTINGS_FILE": str(root / "settings.json"),
    }


# The run's own owner. With none in its config folder, ELI brings the generic ~/.eli_user_id over
# (paths.adopt_legacy_file), so every test would run as this machine's real owner.
TEST_OWNER_ID = "a-test-owner"


def seed_identity(config_dir: Path) -> None:
    folder = Path(config_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "user_id").write_text(TEST_OWNER_ID, encoding="utf-8")


def stores() -> Dict[str, Path]:
    """Each store as ELI resolves it now."""
    from eli.cognition import persona
    from eli.core import paths
    from eli.core.runtime_settings import _settings_file
    from eli.memory.vector_store import _get_index_paths
    from eli.plugins.manager import _state_file as _plugin_state_file
    from eli.tools.image_engine.runtime_paths import image_engine_root
    from eli.world.persistence import storage

    found = {
        "data folder": paths.data_dir(), "config folder": paths.config_dir(),
        "training folder": paths.learning_dir(), "cache folder": paths.cache_dir(),
        "user DB": paths.user_db_path(), "memory DB": paths.memory_db_path(), "agent DB": paths.agent_db_path(),
        "orchestrator audit DB": paths.orchestrator_audit_db_path(),
        "capability state DB": paths.capability_state_db_path(), "document index DB": paths.document_index_db_path(),
        "agenda DB": paths.agenda_db_path(), "calendar": paths.calendar_ics_path(),
        "persona overlay": paths.persona_auto_path(), "persona overlay (persona module)": persona._PERSONA_AUTO_FILE,
        "notebook": paths.notebook_dir(), "notes": paths.notes_dir(), "settings": _settings_file(),
        "plugin state": _plugin_state_file(), "image engine": image_engine_root(),
        "world folder": storage.WORLD_DIR, "world folder (now)": storage.world_dir(),
    }
    found.update({f"vector index {Path(p).name}": p for p in _get_index_paths()})
    return {name: Path(p).expanduser().resolve() for name, p in found.items()}


def outside(root: Path) -> Dict[str, Path]:
    """The stores that resolve anywhere but under `root`."""
    safe = Path(root).resolve()
    return {name: p for name, p in stores().items() if p != safe and safe not in p.parents}
