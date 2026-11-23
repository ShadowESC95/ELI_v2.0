"""Settings model swap must update ELI_GGUF_MODEL_PATH, not reload the old GGUF."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def settings_home(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    old_model = models / "old-model.gguf"
    new_model = models / "new-model.gguf"
    old_model.write_bytes(b"GGUF")
    new_model.write_bytes(b"GGUF")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        '{"provider":"custom_gguf","model_path":"models/old-model.gguf",'
        '"custom_model_path":"models/old-model.gguf","n_ctx":2048,"n_gpu_layers":0,'
        '"batch_size":64,"n_threads":4}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS", "1")
    # Relative env pin (same shape the GUI/apply_env write) so the portability
    # guard does not treat it as a foreign-machine absolute path.
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", "models/old-model.gguf")

    from eli.core import runtime_settings as rs
    monkeypatch.setattr(rs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rs, "_eli_runtime_physical_project_root", lambda: tmp_path)
    monkeypatch.setattr(rs, "_eli_final_project_root", lambda: tmp_path)
    return tmp_path, old_model, new_model, settings_file


def test_save_settings_updates_gguf_model_path_env(settings_home):
    _tmp_path, _old_model, new_model, _settings_file = settings_home
    from eli.core import runtime_settings as rs
    from eli.core.paths import resolve_runtime_path

    rs.save_settings({
        "model_path": "models/new-model.gguf",
        "custom_model_path": "models/new-model.gguf",
        "provider": "custom_gguf",
    })
    env_raw = os.environ.get("ELI_GGUF_MODEL_PATH", "")
    assert "new-model.gguf" in env_raw.replace("\\", "/")
    # Prefer basename check — resolve may map through install root depending
    # on path helpers, but apply_env must have flipped away from old-model.
    assert "old-model.gguf" not in env_raw.replace("\\", "/")
    assert new_model.name in Path(env_raw).name


def test_load_settings_from_disk_ignores_stale_env(settings_home, monkeypatch):
    _tmp_path, _old_model, _new_model, settings_file = settings_home
    from eli.core import runtime_settings as rs

    settings_file.write_text(
        '{"provider":"custom_gguf","model_path":"models/new-model.gguf",'
        '"custom_model_path":"models/new-model.gguf"}\n',
        encoding="utf-8",
    )
    # Env still points at the old model (GUI pin).
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", "models/old-model.gguf")
    poisoned = rs.load_settings()
    assert "old-model" in str(poisoned.get("model_path") or "")
    disk = rs.load_settings_from_disk()
    assert "new-model" in str(disk.get("model_path") or "")


def test_phatic_how_are_you_this_evening():
    from eli.kernel.engine import _is_brief_phatic_prompt

    assert _is_brief_phatic_prompt("hey eli, how are you this evening?")
    assert _is_brief_phatic_prompt("how are you today")
    assert _is_brief_phatic_prompt("how are you this morning")


def test_phatic_speaking_in_tongues_meta():
    from eli.kernel.engine import _is_brief_phatic_prompt

    assert _is_brief_phatic_prompt("hey buddy, you still speaking in tounges?")
    assert _is_brief_phatic_prompt("you still speaking in tongues?")
    assert not _is_brief_phatic_prompt(
        "search for why the model is speaking in tongues and fix the router"
    )


def test_draft_only_gguf_preflight(tmp_path):
    from eli.cognition.model_load_diagnostics import (
        draft_only_load_message,
        is_draft_only_gguf,
        preflight_gguf_model,
    )

    p = tmp_path / "Kimi-K3-DSpark-Q8_0.gguf"
    p.write_bytes(b"GGUF")
    assert is_draft_only_gguf(p, "dflash-draft")
    msg = draft_only_load_message(p, "dflash-draft")
    assert "draft" in msg.lower()
    assert "chat" in msg.lower()
    # preflight needs a real readable header for arch; filename markers still work
    assert is_draft_only_gguf(p)


def test_a_model_outside_elis_folder_that_exists_is_kept(tmp_path, monkeypatch):
    """A browsed-to model (~/Downloads, another drive) was wiped from the settings at the next load:
    two guards each cleared a full path outside the install folder. Only a path that no longer exists
    is stale. Read through load_settings(), as the app reads it."""
    import json
    from eli.core import runtime_settings as rs
    for name in ("ELI_ALLOW_EXTERNAL_MODEL_PATHS", "ELI_SETTINGS_FILE", "ELI_SETTINGS_PATH", "ELI_GGUF_MODEL_PATH",
                 "ELI_MODEL_PATH", "ELI_CUSTOM_MODEL_PATH", "ELI_BUNDLED_MODEL_PATH", "ELI_GGUF_MODEL"):
        monkeypatch.delenv(name, raising=False)
    root, downloads = tmp_path / "ELI_v2", tmp_path / "Downloads"
    (root / "config").mkdir(parents=True)
    downloads.mkdir()
    model = downloads / "chosen.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setenv("ELI_CONFIG_DIR", str(root / "config"))
    for fn in ("_eli_runtime_physical_project_root", "_eli_final_project_root"):
        monkeypatch.setattr(rs, fn, lambda: root)
    (root / "config" / "settings.json").write_text(json.dumps(
        {"provider": "custom_gguf", "model_path": str(model), "custom_model_path": str(downloads / "gone.gguf"),
         "gguf_model_path": "../elsewhere.gguf"}), encoding="utf-8")
    loaded = rs.load_settings()
    assert loaded["model_path"] == str(model.resolve())
    assert loaded["custom_model_path"] == "" and loaded["gguf_model_path"] == ""


def test_a_path_set_while_running_stays_through_later_settings_reads(tmp_path, monkeypatch):
    """A test pointed ELI_CONFIG_DIR at its own folder, another thread read the settings, and the
    check for paths a copied install inherits took the variable away: the writes went to the project."""
    from eli.core import runtime_settings as rs
    rs.load_settings()
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    reader = threading.Thread(target=rs.load_settings)
    reader.start()
    reader.join()
    assert os.environ["ELI_CONFIG_DIR"] == str(tmp_path / "cfg")


def test_a_path_inherited_from_another_install_is_dropped_at_start(tmp_path, monkeypatch, caplog):
    """Another ELI install's folders are its own (every ELI product keeps its own): a config folder
    inside one is dropped, and the log says which and why."""
    import logging
    from eli.core import runtime_settings as rs
    other = tmp_path / "another-install"
    for folder in ("eli/cognition", "eli/gui", "config"):
        (other / folder).mkdir(parents=True)
    monkeypatch.setattr(rs, "_STALE_ENV_CHECKED", False)
    monkeypatch.setenv("ELI_CONFIG_DIR", str(other / "config"))
    with caplog.at_level(logging.WARNING, logger="eli.core.runtime_settings"):
        rs.load_settings()
    assert "ELI_CONFIG_DIR" not in os.environ
    assert "ELI_CONFIG_DIR" in caplog.text and str(other) in caplog.text


def test_a_config_folder_the_user_set_outside_the_install_is_kept_and_read(tmp_path, monkeypatch):
    """The check dropped every folder variable outside the checkout when the process started, so an
    ELI_CONFIG_DIR the user had set was taken away without a word and the checkout's own
    config/settings.json was read in its place."""
    import json
    from eli.core import runtime_settings as rs
    mine = tmp_path / "my-eli-settings"          # the user's own folder, in no ELI install
    mine.mkdir()
    (mine / "settings.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    for name in ("ELI_SETTINGS_FILE", "ELI_SETTINGS_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(rs, "_STALE_ENV_CHECKED", False)
    monkeypatch.setenv("ELI_CONFIG_DIR", str(mine))
    assert rs.load_settings()["theme"] == "light"
    assert os.environ["ELI_CONFIG_DIR"] == str(mine)
    assert rs.inherited_from_another_install(mine / "not-made-yet") is None


# ── The environment and the saved settings: which value governs (runtime_settings, above apply_env) ──
_LOAD_VARS = ("ELI_N_CTX", "ELI_GGUF_N_CTX", "ELI_GGUF_N_BATCH", "ELI_BATCH_SIZE", "ELI_SETTINGS_PUBLISHED")


@pytest.fixture()
def saved_auto_ctx(tmp_path, monkeypatch):
    for name in _LOAD_VARS:
        monkeypatch.delenv(name, raising=False)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"n_ctx": 0, "batch_size": 512}\n', encoding="utf-8")
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_file))
    return settings_file


def test_a_save_keeps_the_context_and_batch_the_operator_exported(saved_auto_ctx, monkeypatch):
    """Every save wrote the file's values over the load variables: with the saved context on auto
    an exported ELI_N_CTX=16384 was removed, and ELI_GGUF_N_BATCH=1024 became the saved 512."""
    from eli.core import runtime_settings as rs
    monkeypatch.setenv("ELI_N_CTX", "16384")
    monkeypatch.setenv("ELI_GGUF_N_BATCH", "1024")
    rs.save_settings({"theme": "light"})
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "16384"   # the loader's name too
    assert os.environ["ELI_GGUF_N_BATCH"] == os.environ["ELI_BATCH_SIZE"] == "1024"
    rs.apply_env(rs.load_settings_from_disk())              # what a reload does
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "16384"
    assert os.environ["ELI_GGUF_N_BATCH"] == "1024"
    loaded = rs.load_settings()
    assert (loaded["n_ctx"], loaded["batch_size"]) == (16384, 1024)


def test_the_user_changing_a_setting_in_the_app_takes_over_from_the_export(saved_auto_ctx, monkeypatch):
    from eli.core import runtime_settings as rs
    monkeypatch.setenv("ELI_N_CTX", "16384")
    monkeypatch.setenv("ELI_GGUF_N_BATCH", "1024")
    rs.save_settings({"n_ctx": 16384, "batch_size": 1024})     # what was in force, saved back: no change
    assert os.environ["ELI_N_CTX"] == "16384" and os.environ["ELI_GGUF_N_BATCH"] == "1024"
    rs.save_settings({"n_ctx": 8192})
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "8192"
    assert os.environ["ELI_GGUF_N_BATCH"] == "1024"             # not changed, still the export
    rs.save_settings({"n_ctx": 0})                               # auto
    assert "ELI_N_CTX" not in os.environ and "ELI_GGUF_N_CTX" not in os.environ
    rs.save_settings({"theme": "dark"})
    assert "ELI_N_CTX" not in os.environ and rs.load_settings()["n_ctx"] == 0


def test_an_exported_model_outlasts_saves_until_a_model_is_picked_in_the_app(settings_home, monkeypatch):
    """The fixture exports ELI_GGUF_MODEL_PATH (old-model). Saves of other settings and a reload
    wrote the file's model over it; picking a model in the app is what replaces it."""
    _tmp_path, _old_model, new_model, settings_file = settings_home
    from eli.core import runtime_settings as rs
    monkeypatch.delenv("ELI_SETTINGS_PUBLISHED", raising=False)
    settings_file.write_text('{"provider":"custom_gguf","model_path":"models/new-model.gguf"}\n', encoding="utf-8")
    rs.save_settings({"theme": "light"})
    assert os.environ["ELI_GGUF_MODEL_PATH"] == "models/old-model.gguf"     # the export, not the file
    rs.apply_env(rs.load_settings_from_disk())
    assert os.environ["ELI_GGUF_MODEL_PATH"] == "models/old-model.gguf"
    rs.save_settings({"model_path": "models/new-model.gguf"})              # picked in the app
    assert Path(os.environ["ELI_GGUF_MODEL_PATH"]).name == new_model.name
    rs.save_settings({"theme": "dark"})
    assert Path(os.environ["ELI_GGUF_MODEL_PATH"]).name == new_model.name


def test_the_window_shows_an_exported_model_as_the_one_in_force(settings_home, monkeypatch):
    """The Settings model box showed the saved custom model while an exported one was in force, and
    the window saves every box at once: the next save of any setting wrote the saved model over the
    export. The box is filled from the export when there is one."""
    from eli.core import runtime_settings as rs
    monkeypatch.delenv("ELI_SETTINGS_PUBLISHED", raising=False)
    assert rs.exported_setting("model_path") == "models/old-model.gguf"       # the fixture's export
    src = (Path(__file__).resolve().parents[1] / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    fill = src[src.index("    def load_settings(self):"):src.index("    def save_settings(self, silent")]
    assert '_rs_exported_model("model_path")' in fill
    assert fill.index('_rs_exported_model("model_path")') < fill.index("self.model_path_input.setText(model_path")


# ── the window's Settings tab, built offscreen in a child process (tests/_gui_runtime_checks.py) ──
@pytest.fixture(scope="module")
def window_saves(tmp_path_factory):
    """What the real window's saves leave behind, case by case (_gui_runtime_checks.settings_saves)."""
    import json
    import subprocess
    import sys
    tmp = tmp_path_factory.mktemp("window_saves")
    env = dict(os.environ)
    for key in ("HOME", "USERPROFILE", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        env[key] = str(tmp / "home")
    env.update(ELI_DATA_DIR=str(tmp / "data"), ELI_CONFIG_DIR=str(tmp / "config"),
               ELI_SETTINGS_FILE=str(tmp / "settings.json"), ELI_MODELS_DIR=str(tmp / "cases" / "models"),
               ELI_TEST_SETTINGS_CASES=str(tmp / "cases"), ELI_PERSONA_AUTO_PATH=str(tmp / "persona.auto.txt"),
               ELI_WORLD_DIR=str(tmp / "world"), ELI_NOTEBOOK_DIR=str(tmp / "notebook"),
               ELI_OFFLINE="1", ELI_FORCE_CPU="1", QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, "-m", "tests._gui_runtime_checks", "settings",
                           "eli.gui.eli_pro_audio_gui_v2_0"], cwd=Path(__file__).resolve().parents[1],
                          env=env, capture_output=True, text=True, timeout=600)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, f"exit {proc.returncode}\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    result = json.loads(lines[-1][len("RESULT "):])
    if "skip" in result:
        pytest.skip(result["skip"])
    return result


def test_a_window_save_keeps_an_exported_context_out_of_the_settings_file(window_saves):
    """The window saved every box at once: a save of any setting wrote the context and batch the
    operator had exported into settings.json, where they stayed once the export was gone."""
    case = window_saves["exported_context"]
    assert case["env"] == {"ELI_N_CTX": "16384", "ELI_GGUF_N_BATCH": "1024"}     # still in force
    assert (case["file"]["n_ctx"], case["file"]["batch_size"]) == (0, 512)
    assert case["file"]["temperature"] == pytest.approx(0.6)                    # what was changed
    assert (case["loaded"]["n_ctx"], case["loaded"]["batch_size"]) == (0, 512)
    assert case["loaded"]["temperature"] == pytest.approx(0.6)


def test_the_window_shows_every_layer_and_a_save_keeps_an_exported_one(window_saves):
    """The GPU-layer box started at 0, so an exported (or saved) -1, every layer, showed as auto
    and the next save of any setting wrote 0 over it."""
    case = window_saves["exported_every_layer"]
    assert (case["shown"]["layers"], case["shown"]["layers_text"]) == (-1, "every layer")
    assert case["env"]["ELI_N_GPU_LAYERS"] == "-1"
    assert case["file"]["n_gpu_layers"] == 0


def test_with_the_bundled_provider_an_exported_model_is_shown_and_kept(window_saves):
    """With bundled_gguf the model box showed the saved bundled model, so the next save of any
    setting wrote it over the exported model; one kept outside the models folder is listed too."""
    models = window_saves["models"]
    for name, model in (("bundled_exported", models["beta"]), ("bundled_exported_elsewhere", models["gamma"])):
        case = window_saves[name]
        assert case["shown"]["bundled"] == model, name
        assert case["env"]["ELI_GGUF_MODEL_PATH"] == model, name
        assert case["file"]["model_path"] == case["file"]["bundled_model_path"] == models["alpha"], name
        assert case["loaded"]["model_path"] == models["alpha"], name


def test_the_windows_tuner_saves_its_own_values_and_no_export(window_saves):
    """The tuner saved the whole loaded settings back: the exported context and batch went into the
    file, the legacy gpu_layers copy in them wrote the old layer count over the tuner's, and the
    recommendation it then applied put its provider and temperature over the user's."""
    case = window_saves["tuner"]
    saved = case["file"]
    assert (saved["n_gpu_layers"], saved["n_gpu_layers_source"]) == (-1, "tuner")
    assert case["shown_after"]["layers_text"] == "every layer"
    assert saved.get("n_ctx", 0) == 0 and saved["batch_size"] == 512
    assert (saved["temperature"], saved["provider"]) == (0.3, "bundled_gguf")
    assert (case["loaded"]["n_ctx"], case["loaded"]["batch_size"]) == (0, 512)


def test_applying_a_hardware_recommendation_keeps_the_users_settings_and_no_export(tmp_path, monkeypatch):
    """apply_recommendation saved the whole loaded settings back (an exported context went into the
    file) and put temperature 0.7, max_tokens -1 and its provider over the user's."""
    import json
    from eli.core import hardware_profile as hp
    from eli.core import runtime_settings as rs
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"provider": "bundled_gguf", "temperature": 0.3, "max_tokens": 900, "n_ctx": 0}),
                 encoding="utf-8")
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(f))
    for var in set(rs._PUBLISHED_VARS + ("ELI_SETTINGS_PUBLISHED", "ELI_N_CTX", "ELI_MODEL_PATH")):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    monkeypatch.setenv("ELI_N_CTX", "16384")
    assert hp.apply_recommendation(hp.ModelRecommendation(model_path="/m/a.gguf", n_ctx=8192))["ok"]
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["n_ctx"] == 0 and saved["hw_profile_n_ctx"] == 8192 and saved["model_path"] == "/m/a.gguf"
    assert (saved["temperature"], saved["max_tokens"], saved["provider"]) == (0.3, 900, "bundled_gguf")
    f.write_text(json.dumps({"provider": "ollama"}), encoding="utf-8")
    hp.apply_recommendation(hp.ModelRecommendation(model_path="/m/a.gguf"))
    assert json.loads(f.read_text(encoding="utf-8"))["provider"] == "custom_gguf"   # Ollama loads no GGUF



def test_the_first_run_hardware_profile_saves_no_export_and_wipes_no_model(tmp_path, monkeypatch):
    """On a new user's first run the hardware profile saved the whole loaded settings back: a value
    exported for that one run (ELI_USER_NAME, ELI_N_CTX) became a saved setting. With no model in any
    folder its empty choice was written over the model the user had picked (a drive not plugged in)."""
    import json
    from eli.core import hardware_profile as hp
    f = tmp_path / "settings.json"
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(f))
    monkeypatch.setenv("ELI_USER_NAME", "Visitor")
    monkeypatch.setenv("ELI_N_CTX", "1234")
    monkeypatch.setattr(hp, "detect_hardware", lambda *, force=False: hp.HardwareProfile(cpu_threads=4))
    monkeypatch.setattr(hp, "discover_models", lambda *a, **k: [])
    assert hp.enforce_hardware_authority()["rewritten"]
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert "user_name" not in saved and "n_ctx" not in saved and saved["hardware_fingerprint"]
    chosen = str(tmp_path / "unplugged_drive" / "chosen.gguf")
    f.write_text(json.dumps({"model_path": chosen}), encoding="utf-8")
    hp.enforce_hardware_authority()
    assert json.loads(f.read_text(encoding="utf-8"))["model_path"] == chosen
    hp.apply_recommendation(hp.ModelRecommendation(model_path=""))
    assert json.loads(f.read_text(encoding="utf-8"))["model_path"] == chosen

def test_the_think_switch_follows_a_change_made_through_the_settings(saved_auto_ctx, monkeypatch):
    """ELI_MODEL_THINK was written once and then never again: turning deep thinking off through the
    settings (the API, the dashboard) had no effect until a restart."""
    from eli.core import runtime_settings as rs
    monkeypatch.delenv("ELI_MODEL_THINK", raising=False)
    rs.save_settings({"model_thinking": True})
    assert os.environ["ELI_MODEL_THINK"] == "1"
    rs.save_settings({"model_thinking": False})
    assert os.environ["ELI_MODEL_THINK"] == "0"


# ── the legacy bin/elix launcher ──────────────────────────────────────────────────────────────────
# find and readlink as a Mac has them: BSD find has no -printf, and the readlink of macOS 12.2 and
# older has no -f (GNU options); each refuses those as macOS does and otherwise is the real tool.
_BSD_TOOLS = {
    "find": ('for a in "$@"; do case "$a" in -printf|-fprintf|-regextype)\n'
             '  echo "find: $a: unknown primary or operator" >&2; exit 1;; esac; done\n'),
    "readlink": ('case "${1:-}" in -f|-e|-m|--*) echo "readlink: illegal option -- ${1#-}" >&2\n'
                 '  echo "usage: readlink [-n] [file ...]" >&2; exit 1;; esac\n'),
}


def _elix_install(tmp_path, userland="gnu"):
    """A copy of bin/elix and bin/elix.real in a folder of their own, two models, a saved choice, and
    a stand-in for the venv's python that records what the app would be started with. `userland`
    "bsd" puts find and readlink as macOS has them first on PATH."""
    import json
    import shutil
    import sys
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path / "install"
    (root / "bin").mkdir(parents=True)
    for name in ("elix", "elix.real"):
        shutil.copy2(repo / "bin" / name, root / "bin" / name)
    models = root / "models"
    models.mkdir()
    alpha, beta = models / "alpha.gguf", models / "beta.gguf"
    for model in (alpha, beta):
        model.write_bytes(b"GGUF")
    (root / "config").mkdir()
    (root / "config" / "settings.json").write_text(
        json.dumps({"provider": "custom_gguf", "model_path": str(beta)}), encoding="utf-8")
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text('#!/usr/bin/env bash\n'
                      'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "eli.gui.app" ]; then\n'
                      '  printf "%s" "${ELI_GGUF_MODEL_PATH:-}" > "$ELIX_TEST_RECORD"; exit 0\n'
                      'fi\n'
                      'exec "$ELIX_TEST_PYTHON" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    home = tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELI_") and k != "GGUF_MODEL_PATH"}
    env.update(PYTHONPATH=str(repo), ELIX_TEST_PYTHON=sys.executable, ELIX_TEST_RECORD=str(tmp_path / "started"),
               ELI_TEST_MODE="1", HOME=str(home), XDG_DATA_HOME=str(home / "data"),
               XDG_CONFIG_HOME=str(home / "config"))
    if userland == "bsd":
        tools = tmp_path / "bsd-tools"
        tools.mkdir()
        for name, refuse in _BSD_TOOLS.items():
            (tools / name).write_text(f'#!/bin/sh\n{refuse}exec {shutil.which(name)} "$@"\n', encoding="utf-8")
            (tools / name).chmod(0o755)
        env["PATH"] = f"{tools}{os.pathsep}{env.get('PATH', '')}"
    return root, alpha, beta, env


def _run_elix(root, env, answer=None):
    """bin/elix, with `answer` typed at its model question (it asks only on a terminal)."""
    import pty
    import subprocess
    if answer is None:
        return subprocess.run(["bash", str(root / "bin" / "elix")], stdin=subprocess.DEVNULL, env=env,
                              cwd=str(root), capture_output=True, text=True, timeout=300)
    master, terminal = pty.openpty()
    try:
        proc = subprocess.Popen(["bash", str(root / "bin" / "elix")], stdin=terminal, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, cwd=str(root), text=True)
        os.write(master, answer.encode() + b"\n")
        out, _ = proc.communicate(timeout=300)
    finally:
        os.close(terminal)
        os.close(master)
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, "")


@pytest.mark.skipif(__import__("sys").platform == "win32" or not __import__("shutil").which("bash"),
                    reason="runs the bash launcher in a terminal (pty)")
@pytest.mark.parametrize("userland", ["gnu", "bsd"])
def test_the_legacy_elix_launcher_keeps_its_model_choice_in_the_apps_settings(tmp_path, userland):
    """bin/elix saved its choice in .env.eli_v2_0 as ELI_GGUF_MODEL_PATH, bin/elix.real loaded that
    file on every start, and the variable comes before the settings: a model picked in the app was
    ignored at the next elix start. Its choice is now the app's own model setting. With find and
    readlink as a Mac has them it stopped at its first line (readlink -f) and listed no model
    (find -printf)."""
    import json
    root, alpha, beta, env = _elix_install(tmp_path, userland)
    settings = root / "config" / "settings.json"
    started = tmp_path / "started"
    old_choice = "".join(f"export {name}={alpha}\n" for name in
                         ("ELI_GGUF_MODEL_PATH", "ELI_MODEL_PATH", "ELI_MODEL", "GGUF_MODEL_PATH"))
    (root / ".env.eli_v2_0").write_text(
        f"export ELIX_TEST_FLAG=1\n\n# Selected by bin/elix model picker\n{old_choice}", encoding="utf-8")

    ran = _run_elix(root, env)                                   # no terminal: no question
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert started.read_text() == ""                             # the app's own choice decides
    left = (root / ".env.eli_v2_0").read_text(encoding="utf-8")
    assert "ELIX_TEST_FLAG=1" in left and "ELI_GGUF_MODEL_PATH" not in left and "bin/elix" not in left

    ran = _run_elix(root, env, answer="1")                       # alpha
    assert ran.returncode == 0, ran.stdout
    assert f"Current: {beta}" in ran.stdout
    assert json.loads(settings.read_text())["model_path"] == str(alpha)
    assert started.read_text() == ""

    saved = json.loads(settings.read_text())                     # the app picks beta
    saved.update(model_path=str(beta), custom_model_path=str(beta))
    settings.write_text(json.dumps(saved), encoding="utf-8")
    ran = _run_elix(root, env, answer="")                        # Enter: the current model
    assert f"Current: {beta}" in ran.stdout
    assert json.loads(settings.read_text())["model_path"] == str(beta)
    assert started.read_text() == ""
