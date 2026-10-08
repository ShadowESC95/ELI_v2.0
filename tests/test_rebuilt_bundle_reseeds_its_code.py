"""A frozen build copies its eli/ source into the user's data folder and runs it from there. The copy
was keyed on the version alone, so a second build under the same number (a dry run, a release
rebuilt under its tag) found the first one's copy and ran the old code."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hook():
    spec = importlib.util.spec_from_file_location("rthook_eli_frozen_paths",
                                                  ROOT / "packaging" / "pyinstaller" / "rthook_eli_frozen_paths.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _bundle(path: Path, stamp: str, code: str) -> Path:
    (path / "eli" / "core").mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (path / "build_stamp.txt").write_text(stamp + "\n", encoding="utf-8")
    (path / "eli" / "core" / "mod.py").write_text(code, encoding="utf-8")
    return path


def test_a_rebuild_under_the_same_version_replaces_the_copy(tmp_path):
    hook, user = _hook(), tmp_path / "user"
    hook._seed(_bundle(tmp_path / "first", "aaaa", "OLD = 1\n"), user)
    hook._seed(_bundle(tmp_path / "second", "bbbb", "NEW = 1\n"), user)
    assert (user / "eli" / "core" / "mod.py").read_text(encoding="utf-8") == "NEW = 1\n"


def test_the_same_build_does_not_copy_again(tmp_path):
    hook, user = _hook(), tmp_path / "user"
    bundle = _bundle(tmp_path / "b", "aaaa", "X = 1\n")
    hook._seed(bundle, user)
    (user / "eli" / "core" / "mod.py").write_text("PATCHED = 1\n", encoding="utf-8")   # self-improvement's edit
    hook._seed(bundle, user)
    assert (user / "eli" / "core" / "mod.py").read_text(encoding="utf-8") == "PATCHED = 1\n"


def test_the_build_records_its_source():
    spec = (ROOT / "ELI.spec").read_text(encoding="utf-8")
    assert "build_stamp.txt" in spec and '"rev-parse", "HEAD"' in spec
