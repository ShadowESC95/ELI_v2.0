"""Runtime enforcement — the gate that survives a plugin ignoring ELI's API.

Every other check in eli/plugins is defeated by one fact: an enabled plugin is
`exec_module`'d into ELI's own interpreter, so the permission API is *cooperative*.
A plugin that passed the manifest check, the hash, the signature and eleven scanners
can simply `import socket` and never call a gated helper at all.

`sys.addaudithook` fires below the Python API, on the operation itself, and raising
inside it aborts the operation. These tests pin that a plugin cannot reach the
network, the filesystem or a subprocess by going around ELI — and, equally
important, that ELI's own code is untouched.
"""
import json
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not hasattr(sys, "addaudithook"), reason="audit hooks need CPython 3.8+")


@pytest.fixture()
def plugin_tree(tmp_path, monkeypatch):
    """A plugin declaring only 'notifications' that tries to do rather more."""
    plugins = tmp_path / "plugins"
    pkg = plugins / "sneaky"
    pkg.mkdir(parents=True)
    (pkg / "eli_plugin.json").write_text(json.dumps({
        "id": "sneaky", "name": "Sneaky", "version": "1.0.0", "description": "d",
        "author": "x", "license": "MIT", "permissions": ["notifications"],
    }), encoding="utf-8")
    (pkg / "plugin.py").write_text(
        "import socket, subprocess\n"
        "def net():\n"
        "    s = socket.socket(); s.settimeout(1); s.connect(('1.1.1.1', 80))\n"
        "def read():\n"
        "    return open('/etc/hostname').read()\n"
        "def write(p):\n"
        "    return open(p, 'w').write('x')\n"
        "def run():\n"
        "    return subprocess.run(['echo', 'hi'], capture_output=True)\n",
        encoding="utf-8")
    monkeypatch.setenv("ELI_PLUGINS_DIR", str(plugins))
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    # Networking ON. Otherwise netguard's socket guard — installed process-wide by
    # whatever ran earlier in the suite — raises OfflineError first and we never
    # learn whether the sandbox would have stopped it. The point of these tests is
    # that capability enforcement holds INDEPENDENTLY of the offline switch.
    monkeypatch.setenv("ELI_OFFLINE", "0")
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    return pkg


@pytest.fixture()
def loaded(plugin_tree):
    """Install enforcement, then load the plugin the way the manager does."""
    import importlib.util
    from eli.plugins import sandbox
    sandbox.install_plugin_sandbox()
    sandbox.refresh()
    sandbox.reset_session_grants()

    # Precondition. The audit hook is process-wide and installed once, so if an
    # earlier test left stale plugin roots the hook simply does not recognise this
    # plugin and enforces nothing — which would show up as a confusing "not blocked"
    # rather than the setup failure it actually is.
    assert "sneaky" in sandbox.status()["declared"], (
        "sandbox did not pick up the test plugin; roots are stale: "
        f"{sandbox.status()['plugins']}")

    spec = importlib.util.spec_from_file_location(
        "plugins.sneaky.plugin", plugin_tree / "plugin.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)
    sandbox.reset_session_grants()


def test_undeclared_network_is_blocked_at_the_socket(loaded):
    """`import socket` directly — never touching ELI's gated helpers.

    Networking is deliberately enabled for this test: a plugin must be stopped by
    its own declared capabilities even when ELI is perfectly willing to go online.
    """
    with pytest.raises(PermissionError) as err:
        loaded.net()
    assert "network" in str(err.value) and "sneaky" in str(err.value)


def test_undeclared_file_read_is_blocked(loaded):
    with pytest.raises(PermissionError):
        loaded.read()


def test_undeclared_file_write_is_blocked(loaded, tmp_path):
    with pytest.raises(PermissionError):
        loaded.write(str(tmp_path / "out.txt"))


def test_undeclared_subprocess_is_blocked(loaded):
    with pytest.raises(PermissionError):
        loaded.run()


def test_elis_own_code_is_not_affected(loaded, tmp_path):
    """The hook attributes by stack frame; nothing outside a plugin directory can be
    attributed to a plugin, so ELI itself must run unchanged."""
    target = tmp_path / "eli_owned.txt"
    target.write_text("fine", encoding="utf-8")
    assert target.read_text() == "fine"


def test_the_hook_cannot_be_uninstalled(loaded):
    """CPython provides no removal API — that is the property being relied on."""
    import sys as _s
    assert not hasattr(_s, "removeaudithook")


def test_status_reports_what_is_enforced(loaded):
    from eli.plugins import sandbox
    st = sandbox.status()
    assert st["installed"] is True
    assert st["declared"]["sneaky"] == ["notifications"]


def test_bundled_plugins_without_a_manifest_are_not_broken(tmp_path, monkeypatch):
    """Plugins that shipped with ELI predate the marketplace and have no manifest.
    Breaking them to enforce a contract they never had would be a regression."""
    plugins = tmp_path / "plugins"
    (plugins / "legacy").mkdir(parents=True)
    (plugins / "legacy" / "plugin.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("ELI_PLUGINS_DIR", str(plugins))
    from eli.plugins import sandbox
    sandbox.install_plugin_sandbox()
    sandbox.refresh()
    assert sandbox.status()["declared"]["legacy"] == ["*"]
