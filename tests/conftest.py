import sys, os, pytest
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ELI_TEST_MODE"] = "1"
os.environ["ELI_FORCE_CPU"] = "1"
_MACHINE_CUDA_DEVICES = os.environ.get("CUDA_VISIBLE_DEVICES")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # the real GPU libraries load; the card stays the app's, as on CI

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Tests never reach this machine's desktop, as on a CI runner: no session bus (media players,
# notifications) and no display for an app a test launches. A test run once started the real
# Spotify and played a song.
for _desktop_var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
    os.environ.pop(_desktop_var, None)
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(ROOT / "artifacts" / "_pytest" / "no-session-bus")
# Nor its sound or mixer: the real audio libraries load in tests, so the sound servers are out of
# reach and ALSA knows only a null device (as on a CI runner, PortAudio then does not start). Nor the internet: a request that is not stubbed fails at once.
(ROOT / "artifacts" / "_pytest").mkdir(parents=True, exist_ok=True)
(ROOT / "artifacts" / "_pytest" / "asound.conf").write_text("pcm.!default { type null }\n")
os.environ["ALSA_CONFIG_PATH"] = str(ROOT / "artifacts" / "_pytest" / "asound.conf")
os.environ["PULSE_SERVER"] = "unix:" + str(ROOT / "artifacts" / "_pytest" / "no-sound-server")
os.environ["PIPEWIRE_REMOTE"] = str(ROOT / "artifacts" / "_pytest" / "no-sound-server")
os.environ["JACK_NO_START_SERVER"] = "1"
for _proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[_proxy] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Redirect ALL artifact writes (documents, runtime snapshots, the scheduled-task
# store) to a throwaway IN-PROJECT dir for the whole test session, so a test run can
# never pollute the real artifacts/ or wipe the user's standing scheduled jobs. This
# is plain config (an in-project path runtime_settings won't strip) — NOT a
# monkeypatch. _artifacts_dir() and _store_path() both honour ELI_ARTIFACTS_DIR.
os.environ["ELI_ARTIFACTS_DIR"] = str(ROOT / "artifacts" / "_pytest")
os.environ.setdefault("ELI_CPU_PREFLIGHT", "0")  # no smoke subprocess in tests
# ELI_ARTIFACTS_DIR alone did NOT isolate the SQLite stores — the user DB path is resolved
# by eli.core.paths.user_db_path(), which honours ELI_USER_DB/ELI_MEMORY_DB FIRST (before
# any dev-tree fallback). So tests that called store_memory()/awareness reflection were
# writing into the REAL artifacts/db/user.sqlite3 and injecting rows ("test store", auto
# reflections) into the user's memory. Pin the user + memory DB to the throwaway _pytest
# tree via the highest-priority override so NO test can pollute the real database — and
# without touching artifacts_dir()/data_dir() (ELI_DATA_DIR would, breaking path tests).
_PYTEST_DB = ROOT / "artifacts" / "_pytest" / "db" / "user.sqlite3"
_PYTEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["ELI_USER_DB"]   = str(_PYTEST_DB)
os.environ["ELI_MEMORY_DB"] = str(_PYTEST_DB)
os.environ["ELI_DB_DIR"]    = str(ROOT / "artifacts" / "_pytest" / "db")
# agent.sqlite3 resolves via ELI_AGENT_DB FIRST (paths.agent_db_path); without it,
# tests that touched the agent bus (dispatch/metrics/observations) were writing into
# the REAL artifacts/db/agent.sqlite3. Pin it to the throwaway tree too so NO test can
# change ANY of ELI's stores — the DB must stay a clean slate for a fresh download.
os.environ["ELI_AGENT_DB"]  = str(ROOT / "artifacts" / "_pytest" / "db" / "agent.sqlite3")

# persona_auto_path()/notebook_dir() had no override at all — a full test run once
# replaced the real persona.auto.txt with fixture content. Pin both to the sandbox.
os.environ["ELI_PERSONA_AUTO_PATH"] = str(ROOT / "artifacts" / "_pytest" / "persona.auto.txt")
os.environ["ELI_NOTEBOOK_DIR"]      = str(ROOT / "artifacts" / "_pytest" / "eli_notebook")

# storage.WORLD_DIR is frozen at import time, so this must be set before that module
# ever loads — a full-suite run once wrote real events into the actual world state.
os.environ["ELI_WORLD_DIR"] = str(ROOT / "artifacts" / "_pytest" / "world")
os.environ["ELI_LAST_TRACE_PATH"] = str(ROOT / "artifacts" / "_pytest" / "last_trace.json")

# Both resolve through db_dir() -> data_dir(), which ELI_DB_DIR doesn't touch, so every
# test turn was appending to the REAL audit chain (fixture rows from a dev run sat in it).
# The HMAC key likewise came from (or was created in) the real config dir.
os.environ["ELI_ORCHESTRATOR_AUDIT_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "orchestrator_audit.sqlite3")
os.environ["ELI_CAPABILITY_STATE_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "capability_state.sqlite3")
os.environ["ELI_AUDIT_HMAC_KEY"] = "eli-pytest-audit-key-not-a-real-secret"
# The document index stores whatever a turn reads and embeds it on a worker thread. Off by
# default here; the tests for it build their own on a tmp path.
os.environ["ELI_DOCUMENT_INDEX_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "documents.sqlite3")
os.environ.setdefault("ELI_DOCUMENT_INDEX", "0")
# The agenda (calendar and reminders) writes a DB and an .ics file and fires desktop notifications.
os.environ["ELI_AGENDA_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "agenda.sqlite3")
os.environ["ELI_CALENDAR_FILE"] = str(ROOT / "artifacts" / "_pytest" / "calendar.ics")
os.environ["ELI_AGENDA_NOTIFY"] = "0"
# Nor this machine's settings. Tests read the developer's own config/settings.json (Net toggle, Full
# Control, model paths) and some wrote to it; with Full Control on, a test's "offline" connect went
# out to the network. Each run starts with no settings file, as a fresh install and CI do.
_PYTEST_SETTINGS = ROOT / "artifacts" / "_pytest" / "settings.json"
_PYTEST_SETTINGS.unlink(missing_ok=True)
os.environ["ELI_SETTINGS_FILE"] = str(_PYTEST_SETTINGS)

# Hard isolation guard: fail LOUDLY at collection if any canonical store still resolves
# to the real artifacts/db tree. This makes "no test can change memory" an enforced
# invariant, not just configuration that a future refactor could silently break.
def _assert_db_isolated() -> None:
    from eli.core import paths as _p
    _safe = (ROOT / "artifacts" / "_pytest").resolve()
    for _name, _fn in (("user", _p.user_db_path), ("memory", _p.memory_db_path),
                       ("agent", _p.agent_db_path),
                       ("orchestrator audit", _p.orchestrator_audit_db_path),
                       ("capability state", _p.capability_state_db_path)):
        _resolved = Path(_fn()).resolve()
        if _safe not in _resolved.parents:
            raise RuntimeError(
                f"TEST ISOLATION BREACH: {_name} DB resolves to {_resolved}, "
                f"outside the throwaway {_safe}. A test could pollute the real "
                f"database. Check eli.core.paths overrides in conftest.")
    _persona_resolved = Path(_p.persona_auto_path()).resolve()
    if _safe not in _persona_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: persona_auto_path() resolves to "
            f"{_persona_resolved}, outside the throwaway {_safe}. A test could "
            f"overwrite the real persona overlay. Check eli.core.paths overrides "
            f"in conftest.")
    _notebook_resolved = Path(_p.notebook_dir()).resolve()
    if _safe not in _notebook_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: notebook_dir() resolves to "
            f"{_notebook_resolved}, outside the throwaway {_safe}. Check "
            f"eli.core.paths overrides in conftest.")
    # persona.py used to duplicate persona_auto_path()'s resolution, so the check above
    # passed while its own write constant still pointed at the real file. Check it directly.
    from eli.cognition import persona as _persona_mod
    _persona_file_resolved = Path(_persona_mod._PERSONA_AUTO_FILE).resolve()
    if _safe not in _persona_file_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: eli.cognition.persona._PERSONA_AUTO_FILE resolves to "
            f"{_persona_file_resolved}, outside the throwaway {_safe}. A test could "
            f"overwrite the real persona overlay. Check eli.cognition.persona / "
            f"eli.core.paths overrides in conftest.")
    # WORLD_DIR is frozen at import time — check the module constant, not a fresh call.
    from eli.world.persistence import storage as _world_storage_mod
    _world_dir_resolved = Path(_world_storage_mod.WORLD_DIR).resolve()
    if _safe not in _world_dir_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: eli.world.persistence.storage.WORLD_DIR resolves to "
            f"{_world_dir_resolved}, outside the throwaway {_safe}. A test could write real "
            f"autonomy-engine events into the actual world state. Check ELI_WORLD_DIR is set "
            f"before this module is first imported.")
_assert_db_isolated()

@pytest.fixture(autouse=True)
def _tests_never_launch_apps(monkeypatch, request):
    """A test that reached the real launcher started Spotify on the developer's machine and played
    a song, and an OPEN_APP test started Firefox; with no display they still spawn the process.
    Tests that need a launch stub the launcher they are about; a test of the launcher itself, which
    runs a harmless program, says so with the launches_apps marker."""
    if request.node.get_closest_marker("launches_apps"):
        return
    monkeypatch.setattr("eli.execution.media_runtime.open_spotify",
                        lambda: "Could not open Spotify: tests never launch it")
    monkeypatch.setattr("eli.execution.effectors.system_helpers.open_app_with_timeout",
                        lambda argv, timeout=30: {"ok": False, "error": "tests never launch apps", "argv": argv})
    monkeypatch.setattr("eli.system.portable_app_control._popen", lambda args: False)


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_user.sqlite3"
    yield db_path
    if db_path.exists():
        db_path.unlink()

@pytest.fixture
def memory_instance(temp_db):
    from eli.memory import Memory
    return Memory(db_path=temp_db)

@pytest.fixture
def quiet_gpu_sources(monkeypatch):
    """A machine whose every GPU source (nvidia-smi and the NVIDIA kernel driver, the Linux device
    scan, rocm-smi, DXGI, macOS's registry and system_profiler, llama.cpp's device list) reports
    nothing, with detection's cache cleared. A test then gives one source something to say."""
    import eli.core.hardware_profile as hp
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    monkeypatch.setattr(hp, "_nvidia_driver_loaded", lambda: False)
    monkeypatch.setattr(hp, "_linux_drm_gpus", lambda: [])
    monkeypatch.setattr(hp, "_windows_dxgi_adapters", lambda software=False: None)
    monkeypatch.setattr(hp, "_macos_gpus", lambda: [])
    monkeypatch.setattr(hp, "_macos_accelerators", lambda: None)
    monkeypatch.setattr(hp, "_llama_cpp_cards", lambda: None)
    monkeypatch.setattr(hp, "_lspci_name_for_pci_addr", lambda addr: "")
    monkeypatch.setattr(hp.shutil, "which", lambda name: None)
    monkeypatch.setattr(hp, "_DETECT_HW_CACHE", None)
    return hp

@pytest.fixture(scope="session")
def small_chat_model():
    """ELI_MODEL_PATH if set, else the smallest GGUF in models/ that carries a chat template (a chat
    model; projectors and embedders carry none, and a file's name is no guide). None when there is none."""
    import glob
    env = os.environ.get("ELI_MODEL_PATH")
    if env and os.path.exists(env):
        return env
    from eli.cognition.model_load_diagnostics import gguf_metadata
    found = sorted((os.path.getsize(g), g) for g in glob.glob(str(ROOT / "models" / "**" / "*.gguf"), recursive=True)
                   if (gguf_metadata(g) or {}).get("tokenizer.chat_template"))
    return found[0][1] if found else None


@pytest.fixture
def machine_gpu(monkeypatch):
    """This machine's own cards, for a test about them (the installed GPU pack): the run hides them."""
    if _MACHINE_CUDA_DEVICES is None:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", _MACHINE_CUDA_DEVICES)


@pytest.fixture
def gpu_offload_runtime(monkeypatch):
    """A llama.cpp that can offload to a GPU but gives no device list to plan with, so sizing takes the
    fit path. Real llama.cpp answers for the machine running the tests (none on CI, the developer's
    card here), so a sizing test names the runtime it is about."""
    import eli.core.hardware_profile as hp
    from eli.core import load_plan
    monkeypatch.setattr(hp, "_llama_gpu_offload_available", lambda: True)
    monkeypatch.setattr(load_plan, "devices", lambda: [])
    return hp

# FIX: Force persistence gate to allow all memory writes in tests
@pytest.fixture(autouse=True)
def allow_all_persistence():
    with patch("eli.runtime.persistence_gate.should_store_memory_text", return_value=True), \
         patch("eli.runtime.persistence_gate.should_store_conversation_turn", return_value=True):
        yield

# Force persistence gate to allow all memory writes during tests
@pytest.fixture(autouse=True, scope="function")
def force_persistence_gate():
    with patch("eli.memory.memory._eli_should_store_memory_text", None), \
         patch("eli.memory.memory._eli_should_store_conversation_turn", None):
        yield


# Production code writes ELI_* variables straight into os.environ (save_settings pins ELI_MODEL_PATH, for
# one), which monkeypatch cannot see, so they outlived the test that caused them and skewed later ones.
@pytest.fixture(autouse=True, scope="function")
def restore_eli_environment():
    before = {k: v for k, v in os.environ.items() if k.startswith("ELI_")}
    yield
    for k in [k for k in os.environ if k.startswith("ELI_") and k not in before]:
        os.environ.pop(k, None)
    for k, v in before.items():
        if os.environ.get(k) != v:
            os.environ[k] = v
    # Path resolvers are lru_cached; a test that pointed them at a temp tree must not decide for the next one.
    try:
        from eli.core import paths as _paths
        for _fn in vars(_paths).values():
            if hasattr(_fn, "cache_clear"):
                _fn.cache_clear()
    except Exception:
        pass


# gguf_inference keeps the loaded model in module globals; a test that runs the real
# load_model() leaves a Mock there for the whole session. Reset it after every test.
@pytest.fixture(autouse=True, scope="function")
def reset_gguf_inference_globals():
    yield
    try:
        import eli.cognition.gguf_inference as _ggi
        _ggi._llm = None
        _ggi._live_runtime_override = None
        _ggi._load_failed = False
        _ggi._last_error = None
        if "_live_runtime_params" in vars(_ggi):
            _ggi._live_runtime_params = None
    except Exception:
        pass


# A test that escapes ELI_ARTIFACTS_DIR can overwrite the real runtime snapshot with
# junk (a MagicMock loads as n_ctx=1), which later runs read as machine state. Restore
# it after the session and name any test that touches it.
_REAL_SNAPSHOT = ROOT / "artifacts" / "runtime_snapshot.json"
_SNAPSHOT_TOUCHED: list = []


def _snapshot_state():
    try:
        return _REAL_SNAPSHOT.read_bytes() if _REAL_SNAPSHOT.exists() else None
    except OSError:
        return None


@pytest.fixture(autouse=True, scope="function")
def guard_real_runtime_snapshot(request):
    before = _snapshot_state()
    yield
    if _snapshot_state() != before:
        _SNAPSHOT_TOUCHED.append(request.node.nodeid)
        try:
            if before is None:
                _REAL_SNAPSHOT.unlink(missing_ok=True)
            else:
                _REAL_SNAPSHOT.write_bytes(before)
        except OSError:
            pass


@pytest.fixture(autouse=True, scope="function")
def measurements_stay_on_this_machine(monkeypatch, tmp_path):
    """What ELI measured on this machine (GPU headroom, whisper's footprint) is never read or written
    by a test: a report test read this machine's 108 MB for Qwen3.6 once a real llama.cpp was loaded.
    Nor what one test measured for the next: a generation's decode speed is kept process-wide
    (model_tier), and a slow one recorded by an earlier test cut a later self-consistency test's
    samples from 3 to 2 in the full run, while the test passed on its own."""
    from eli.core import load_plan, model_tier
    from eli.perception import local_whisper_stt
    monkeypatch.setattr(load_plan, "_headroom_file", lambda: tmp_path / "gpu_headroom.json")
    monkeypatch.setattr(load_plan, "_watch", {})
    monkeypatch.setattr(local_whisper_stt, "_footprint_file", lambda: tmp_path / "whisper_gpu.json")
    monkeypatch.setattr(model_tier, "_speed_ema", 0.0)


# ── Auto-updating test-results document ──────────────────────────────────────
# Every pytest run (re)writes artifacts/test_report.md with the live results, so
# the report is dynamic — never stale. ELI's RUN_TESTS action reads/summarises it.
def pytest_sessionfinish(session, exitstatus):
    if _SNAPSHOT_TOUCHED:
        print("\n[conftest] tests that modified the REAL runtime_snapshot.json (restored):", *_SNAPSHOT_TOUCHED[:10], sep="\n  ")
    try:
        import datetime
        from collections import defaultdict
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is None:
            return
        stats = tr.stats
        order = ("passed", "failed", "error", "xfailed", "xpassed", "skipped")
        totals = {k: len(stats.get(k, [])) for k in order}
        total = sum(totals.values())
        per_file = defaultdict(lambda: defaultdict(int))
        failures = []
        for outcome in order:
            for rep in stats.get(outcome, []):
                nid = getattr(rep, "nodeid", "?")
                f = nid.split("::", 1)[0]
                per_file[f][outcome] += 1
                per_file[f]["total"] += 1
                if outcome in ("failed", "error"):
                    failures.append(nid)
        out = [
            "# ELI — Test Suite Report (auto-generated)",
            f"\n*Updated {datetime.datetime.now().isoformat(timespec='seconds')} "
            f"on every `pytest` run.*\n",
            "## Totals\n",
            f"- **Total:** {total}",
            f"- **Passed:** {totals['passed']}",
            f"- **Failed:** {totals['failed'] + totals['error']}",
            f"- **xfailed (known gaps):** {totals['xfailed']}",
            f"- **xpassed (gap fixed?):** {totals['xpassed']}",
            f"- **Skipped:** {totals['skipped']}",
            f"\n**Verdict:** {'✅ GREEN' if (totals['failed'] + totals['error']) == 0 else '❌ FAILURES'}\n",
            "## Per-file\n",
            "| Test file | Total | Pass | Fail | xfail | skip |",
            "|---|---|---|---|---|---|",
        ]
        for f in sorted(per_file):
            c = per_file[f]
            out.append(f"| `{f}` | {c['total']} | {c.get('passed',0)} | "
                       f"{c.get('failed',0)+c.get('error',0)} | {c.get('xfailed',0)} | "
                       f"{c.get('skipped',0)} |")
        if failures:
            out.append("\n## Failures\n")
            out += [f"- `{x}`" for x in failures[:200]]
        _adir = os.environ.get("ELI_ARTIFACTS_DIR")
        _base = Path(_adir).expanduser() if _adir else (ROOT / "artifacts")
        rep_path = _base / "test_report.md"
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        pass
