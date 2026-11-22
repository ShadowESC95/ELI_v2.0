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

# Each run starts as a fresh install: what an earlier run left in the throwaway sandbox (its databases,
# a user profile, an interview in progress, the vector index) is gone before anything below writes or
# reads it. It used to persist, and the same test passed or failed by the run before it.
# A run still going in this checkout holds the sandbox (a shared lock beside it, kept for the session):
# then the sandbox is left as it is, rather than pulled from under that run's open databases.
SANDBOX = ROOT / "artifacts" / "_pytest"


def _fresh_sandbox() -> None:
    import shutil
    SANDBOX.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:                 # Windows: a file another run has open is not deleted anyway
        shutil.rmtree(SANDBOX, ignore_errors=True)
        return
    global _SANDBOX_HOLD
    _SANDBOX_HOLD = open(SANDBOX.parent / "_pytest.lock", "a+")
    try:
        fcntl.flock(_SANDBOX_HOLD, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fcntl.flock(_SANDBOX_HOLD, fcntl.LOCK_SH)         # another run is using it
        return
    shutil.rmtree(SANDBOX, ignore_errors=True)
    fcntl.flock(_SANDBOX_HOLD, fcntl.LOCK_SH)             # this run's, until it ends


_SANDBOX_HOLD = None
_fresh_sandbox()

# Tests never reach this machine's desktop, as on a CI runner: no session bus (media players,
# notifications) and no display for an app a test launches. A test run once started the real
# Spotify and played a song.
for _desktop_var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
    os.environ.pop(_desktop_var, None)
os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(SANDBOX / "no-session-bus")
# Nor is a file opened on it: with no display xdg-open still started LibreOffice on a summary and it
# stayed running after the tests. These launchers do nothing here; a test of one stubs its own.
_no_launchers = SANDBOX / "no-launchers"
_no_launchers.mkdir(parents=True, exist_ok=True)
for _launcher in ("xdg-open", "gio", "gtk-launch", "open"):
    (_no_launchers / _launcher).write_text("#!/bin/sh\nexit 0\n")
    (_no_launchers / _launcher).chmod(0o755)
os.environ["PATH"] = str(_no_launchers) + os.pathsep + os.environ.get("PATH", "")
# Nor its sound or mixer: the real audio libraries load in tests, so the sound servers are out of
# reach and ALSA knows only a null device (as on a CI runner, PortAudio then does not start). Nor the internet: a request that is not stubbed fails at once.
(SANDBOX / "asound.conf").write_text("pcm.!default { type null }\n")
os.environ["ALSA_CONFIG_PATH"] = str(SANDBOX / "asound.conf")
os.environ["PULSE_SERVER"] = "unix:" + str(SANDBOX / "no-sound-server")
os.environ["PIPEWIRE_REMOTE"] = str(SANDBOX / "no-sound-server")
os.environ["JACK_NO_START_SERVER"] = "1"
for _proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[_proxy] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Every place ELI keeps state is a throwaway IN-PROJECT dir for the whole session (in-project, so
# runtime_settings does not strip it as a stale path): the data folder (conversations, proactive and
# runtime state with the per-user profiles, documents, databases), the config folder (settings, the
# owner's id, the small settings files), training runs, caches, downloaded plugins, and each store
# with a variable of its own. Which variable puts which store there is tests/_state_env.py's. Only
# some stores used to be moved, one variable at a time: the config folder stayed this checkout's, so
# a test that told an engine "my name is Sam" wrote it into the owner's config/settings.json, and the
# data folder stayed its artifacts/, where a run rewrote the owner's user profile.
from tests._state_env import outside as _stores_outside, seed_identity as _seed_identity  # noqa: E402
from tests._state_env import state_env as _state_env  # noqa: E402
os.environ.update(_state_env(SANDBOX))


def _fresh_config() -> None:
    """The config folder starts each run as a fresh install has it: the tracked files and nothing else."""
    import shutil
    import subprocess
    target = SANDBOX / "config"
    shutil.rmtree(target, ignore_errors=True)
    try:
        tracked = subprocess.run(["git", "ls-files", "-z", "config"], cwd=ROOT, capture_output=True,
                                 check=True).stdout.decode("utf-8").split("\0")
    except (OSError, subprocess.CalledProcessError):
        tracked = []                    # not a git checkout: start with none, as an empty install would
    for name in filter(None, tracked):
        dest = target / Path(name).relative_to("config")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
    target.mkdir(parents=True, exist_ok=True)


_fresh_config()
_seed_identity(SANDBOX / "config")      # the run's own owner, never this machine's ~/.eli_user_id
os.environ.setdefault("ELI_CPU_PREFLIGHT", "0")  # no smoke subprocess in tests
Path(os.environ["ELI_USER_DB"]).parent.mkdir(parents=True, exist_ok=True)
# The document index stores whatever a turn reads and embeds it on a worker thread. Off by
# default here; the tests for it build their own on a tmp path.
os.environ.setdefault("ELI_DOCUMENT_INDEX", "0")
# Each run starts with no settings file, as a fresh install and CI do: tests read the developer's own
# settings (Net toggle, Full Control, model paths) and some wrote to them; with Full Control on, a
# test's "offline" connect went out to the network.
_PYTEST_SETTINGS = Path(os.environ["ELI_SETTINGS_FILE"])
_PYTEST_SETTINGS.unlink(missing_ok=True)


# Hard isolation guard: fail LOUDLY at collection if any store still resolves outside the sandbox
# (tests/_state_env.stores: the data, config, training and cache folders, the DBs, the persona overlay
# and persona.py's own constant for it, the notebook and notes, the settings, the plugin state, the
# world folder (fixed when its module is imported) and the vector index). This makes "no test can
# change this machine's records" an enforced invariant, not just configuration a refactor could break.
def _assert_db_isolated() -> None:
    escaped = _stores_outside(SANDBOX)
    if escaped:
        raise RuntimeError(
            "TEST ISOLATION BREACH: " + "; ".join(f"{name} resolves to {path}" for name, path in escaped.items())
            + f", outside the throwaway {SANDBOX}. A test could change this machine's own records. "
            "Check tests/_state_env.py.")


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
def known_user_no_interview(monkeypatch, tmp_path):
    """A user ELI already knows, with no first-run interview in progress. On a blank slate "what do
    you know about me" starts the interview instead (eli/onboarding/interview.py, by design), so a
    test of the answer that relied on what earlier runs had left in the stores, a profile or an
    interview begun, passed or failed by the run before it."""
    from eli.onboarding import interview
    monkeypatch.setattr(interview, "_profile_missing", lambda db_path=None: False)
    monkeypatch.setattr(interview, "_state_file", lambda: tmp_path / "onboarding_state.json")


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


# Whatever escapes the sandbox anyway (a path built by hand, a new store) is caught: this
# checkout's own state is listed before the session and compared after it, and every file
# created or changed there, and every folder made there, is named, with the test that made the
# folder. It fails the run in CI and with ELI_TEST_STRICT_ISOLATION=1; otherwise it is only
# reported, since a copy of ELI running from this checkout (ELI's own RUN_TESTS) writes its state
# while the tests run. (ELI v3's guard.) The persona overlay's own default place is in the source
# tree, so it is watched as a file.
_OWN_STATE = [ROOT / name for name in ("artifacts", "config", "training", "runtime", "voices", "plugins",
                                       "models", "cache")]
_OWN_FILES = [ROOT / "eli" / "cognition" / "persona.auto.txt"]
FOLDER = "folder"


def _own_state() -> dict:
    seen = {}
    for top in _OWN_STATE:
        for path in top.rglob("*") if top.is_dir() else ():
            if path == SANDBOX or SANDBOX in path.parents or "__pycache__" in path.parts:
                continue
            if path == SANDBOX.parent / "_pytest.lock":
                continue                 # the lock that holds the sandbox for a run
            try:
                if path.is_file():
                    info = path.stat()
                    seen[path] = (info.st_mtime_ns, info.st_size)
                elif path.is_dir():
                    seen[path] = FOLDER
            except OSError:
                continue
    for path in _OWN_FILES:
        try:
            info = path.stat()
            seen[path] = (info.st_mtime_ns, info.st_size)
        except OSError:
            continue
    return seen


def _written_since(before: dict, asked: Path = ROOT / "-") -> list:
    """What in this checkout's own state was written or made since `before` (_own_state), each a
    path relative to the checkout, a folder with the test that made it."""
    out = []
    for path, was in _own_state().items():
        if before.get(path) == was or path.resolve() == asked:
            continue
        rel = str(path.relative_to(ROOT))
        made_by = _FOLDERS_MADE.get(str(path.resolve())) if was == FOLDER else None
        out.append(f"{rel}/ (made by {made_by})" if made_by else (rel + "/" if was == FOLDER else rel))
    return sorted(out)


# Which test made each folder under this checkout's own state, outside the sandbox (an audit hook:
# os.mkdir), so the report names it.
_FOLDERS_MADE: dict = {}
_WATCHED_ROOTS = tuple(str(top.resolve()) for top in _OWN_STATE)


def _note_folder_made(event, args) -> None:
    if event != "os.mkdir" or not args:
        return
    try:
        path = os.path.realpath(os.fsdecode(args[0]))
    except (TypeError, ValueError):
        return
    sandbox = str(SANDBOX.resolve())
    if path == sandbox or path.startswith(sandbox + os.sep):
        return
    if any(path == top or path.startswith(top + os.sep) for top in _WATCHED_ROOTS):
        _FOLDERS_MADE.setdefault(path, os.environ.get("PYTEST_CURRENT_TEST", "collection").split(" ")[0])


sys.addaudithook(_note_folder_made)
_STATE_BEFORE = _own_state()


# ── Auto-updating test-results document ──────────────────────────────────────
# Every pytest run (re)writes artifacts/test_report.md with the live results, so
# the report is dynamic — never stale. ELI's RUN_TESTS action reads/summarises it.
def pytest_sessionfinish(session, exitstatus):
    asked = Path(session.config.getoption("xmlpath", None) or ROOT / "-").resolve()   # --junitxml
    escaped = _written_since(_STATE_BEFORE, asked)
    if escaped:
        print(f"\n[conftest] TEST ISOLATION BREACH: {len(escaped)} files or folders in this checkout's own "
              "state were written or made during the run:", *escaped, sep="\n  ")
        if os.environ.get("CI") or os.environ.get("ELI_TEST_STRICT_ISOLATION"):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
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
