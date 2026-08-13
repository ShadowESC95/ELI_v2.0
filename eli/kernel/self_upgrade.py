"""
ELI Self-Upgrade Orchestrator
==============================
Called by executor_enhanced.py SELF_UPGRADE action.
Gives ELI the ability to:
  - Pull latest code from git
  - Reinstall/update Python packages
  - Apply generated patches
  - Rebuild indexes (FAISS, KG)
  - Run self-tests and report health
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from eli.core.paths import project_root as _project_root
PROJECT_ROOT = _project_root()
_DEFAULT_RELEASE_REPO = os.environ.get("ELI_RELEASE_REPO", "ShadowESC95/ELI_v2.0")
_DEFAULT_RELEASE_TAG = os.environ.get("ELI_RELEASE_TAG", "v2.1.78")


def _ver_tuple(v: str) -> Tuple[int, ...]:
    """'2.1.47' -> (2, 1, 47), for ordered comparison. Unparseable -> (0,)."""
    parts = re.findall(r"\d+", str(v or ""))
    return tuple(int(p) for p in parts[:4]) if parts else (0,)


def _install_kind() -> str:
    """How this ELI was installed — decides which upgrade mechanisms can work.

    ``appimage``  running from an AppImage; its runtime exports APPIMAGE as the
                  absolute path of the .AppImage file. Upgrading means fetching
                  a new AppImage — there is no git checkout and no pip.
    ``frozen``    another PyInstaller bundle (Windows .exe, macOS .app).
    ``source``    a git/pip checkout — the only case this module was originally
                  written for, which is why an AppImage install used to run
                  `git pull` and `pip install` and fail both by construction.
    """
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if getattr(sys, "frozen", False):
        return "frozen"
    return "source"


def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> Dict[str, Any]:
    """Run a subprocess command, return dict with ok/stdout/stderr."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Command timed out after {timeout}s", "returncode": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}


class SelfUpgrader:
    """ELI self-upgrade agent — upgrades packages, code, and rebuilds indexes."""

    def __init__(self):
        self.log: List[str] = []
        # "upgraded" | "current" | "failed" — read by the SELF_UPGRADE executor
        # branch so a no-op cannot be reported to the user as a success.
        self.upgrade_state: str = "failed"
        self.upgraded: bool = False

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.log.append(entry)
        print(entry)

    # ── Public API (called by executor) ──────────────────────────────────────

    def upgrade(self, request: str = "") -> str:
        """Upgrade this install by whatever mechanism its packaging actually supports.

        The step list is chosen from the install kind. An AppImage has no git
        checkout and no pip, so running `git pull` / `pip install` there only
        produced two guaranteed failures — and the index rebuilds that followed
        still succeeded, which let the old summary announce "Upgrade complete.
        4 / 7 steps succeeded" to a user who was still on the previous build.
        """
        self.log.clear()
        self.upgrade_state = "failed"
        self.upgraded = False
        kind = _install_kind()
        self._log(f"Starting ELI self-upgrade… (install kind: {kind})")

        maintenance = [
            ("Rebuild FAISS index", self._rebuild_faiss),
            ("Rebuild knowledge graph", self._rebuild_kg),
            ("Update capability manifest", self._update_manifest),
            ("Refresh system index", self._refresh_system_index),
        ]
        if kind == "appimage":
            steps = [("AppImage upgrade", self._appimage_upgrade)] + maintenance
        elif kind == "frozen":
            steps = [("Packaged-build upgrade", self._frozen_upgrade)] + maintenance
        else:
            steps = [
                ("Release upgrade", self._release_upgrade),
                ("Git pull (ff-only)", self._git_pull),
                ("Pip upgrade", self._pip_upgrade),
            ] + maintenance

        upgrade_step = steps[0][0]
        results: List[str] = []
        succeeded = 0
        for name, fn in steps:
            self._log(f"  → {name}…")
            try:
                ok, detail = fn()
            except Exception as e:
                ok, detail = False, str(e)
            # Tri-state: None means "does not apply to this install", which is
            # not a failure and must not be reported as one.
            if ok is None:
                mark = "—"
            elif ok:
                mark = "✅"
                succeeded += 1
            else:
                mark = "⚠️"
            if name == upgrade_step:
                self.upgrade_state = "upgraded" if ok else ("current" if ok is None else "failed")
            self._log(f"  {mark} {name}: {detail}")
            results.append(f"{mark} {name}: {detail}")

        self.upgraded = self.upgrade_state == "upgraded"
        if self.upgrade_state == "upgraded":
            summary = ("New build installed — restart ELI to run it. "
                       f"({succeeded}/{len(results)} steps succeeded.)")
        elif self.upgrade_state == "current":
            summary = f"Already on the latest version ({self._local_version()}); nothing to install."
        else:
            summary = (f"NOT upgraded — still running {self._local_version()}. The maintenance "
                       "steps below do not change the installed version.")
        self._log(summary)
        return "\n".join(results) + f"\n\n{summary}"

    def run(self, request: str = "") -> str:
        """Alias for upgrade(); called when executor tries multiple methods."""
        return self.upgrade(request)

    def generate_patch(self, request: str = "") -> str:
        """Ask the self-improvement engine for proposals and format as a report."""
        try:
            from eli.runtime.self_improvement import get_self_improvement
            engine = get_self_improvement()
            result = engine.analyze_and_improve()
            imps = result.get("improvements", [])
            if not imps:
                return "No improvement proposals generated. System appears healthy."
            lines = [f"Generated {len(imps)} improvement proposal(s):"]
            for i, imp in enumerate(imps, 1):
                lines.append(f"  {i}. [{imp.get('category','?')}] {imp.get('description','')}")
            return "\n".join(lines)
        except Exception as e:
            return f"Patch generation failed: {e}"

    def apply_patch(self, patch_path: str = "") -> str:
        """Apply a .patch file to the project."""
        if not patch_path:
            return "No patch path provided."
        p = Path(patch_path).expanduser().resolve()
        if not p.exists():
            return f"Patch file not found: {p}"
        r = _run(["git", "apply", "--check", str(p)])
        if not r["ok"]:
            return f"Patch check failed:\n{r['stderr']}"
        r2 = _run(["git", "apply", str(p)])
        if r2["ok"]:
            return f"Patch applied successfully: {p.name}"
        return f"Patch apply failed:\n{r2['stderr']}"

    def self_test(self) -> str:
        """Run the project test suite and return a summary."""
        self._log("Running self-tests…")
        r = _run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q",
             "--tb=short", "--no-header"],
            timeout=180,
        )
        if r["ok"]:
            return f"✅ All tests passed.\n{r['stdout'][:1500]}"
        return f"❌ Tests failed.\n{r['stdout'][:800]}\n{r['stderr'][:400]}"

    # ── Private step implementations ──────────────────────────────────────────

    def _local_version(self) -> str:
        """The version actually running.

        pyproject.toml is consulted FIRST. Installed dist metadata goes stale the
        moment the project is bumped without reinstalling — this checkout reports
        2.1.29 from a months-old egg-info while pyproject says 2.1.48 — and a
        wrong local version makes the upgrade comparison meaningless. pyproject is
        bundled into the frozen builds too (ELI.spec ships it as data), so it is
        the more reliable source in both cases.
        """
        try:
            text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
            m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
            if m:
                return m.group(1)
        except Exception:
            pass
        try:
            import importlib.metadata as im
            return str(im.version("eli-v2.0"))
        except Exception:
            pass
        return "0.0.0"

    # ── AppImage / frozen-build upgrade ──────────────────────────────────────

    def _release_url(self, filename: str, tag: Optional[str] = None) -> str:
        return (f"https://github.com/{_DEFAULT_RELEASE_REPO}/releases/download/"
                f"{tag or _DEFAULT_RELEASE_TAG}/{filename}")

    def _latest_tag(self) -> str:
        """The newest published release tag, falling back to the pinned default.

        _DEFAULT_RELEASE_TAG is bumped to the version of the build it ships
        inside, so comparing against it would make every build conclude it is
        already current and never upgrade anything. Ask the API what the latest
        release actually is.
        """
        from eli.core import netguard
        url = f"https://api.github.com/repos/{_DEFAULT_RELEASE_REPO}/releases/latest"
        try:
            with netguard.allow_network("self-upgrade"):
                data = netguard.http_get_json(url, timeout=30)
            tag = str((data or {}).get("tag_name") or "").strip()
            if tag:
                return tag
        except Exception as e:
            self._log(f"     could not query the latest release ({str(e)[:80]}); "
                      f"falling back to {_DEFAULT_RELEASE_TAG}")
        return _DEFAULT_RELEASE_TAG

    def _fetch_bytes(self, url: str, timeout: int = 60) -> bytes:
        """Small GET through the network choke point."""
        from eli.core import netguard
        with netguard.allow_network("self-upgrade"):
            with netguard.guarded_urlopen(url, timeout=timeout) as resp:
                return resp.read()

    def _download_verified(self, url: str, dest: Path, expected_sha: str,
                           timeout: int = 900) -> Tuple[bool, str]:
        """Stream `url` to `dest`, hashing as it goes; keep the file ONLY if the
        digest matches.

        Everything goes through netguard rather than a `gh release download`
        subprocess: a subprocess drives libcurl underneath Python's sockets and
        slips past the process-wide offline failsafe — the same hole that had to
        be closed once already for web search. This also puts the transfer in
        the egress ledger.
        """
        from eli.core import netguard
        digest = hashlib.sha256()
        total = 0
        try:
            with netguard.allow_network("self-upgrade"):
                with netguard.guarded_urlopen(url, timeout=timeout) as resp:
                    with dest.open("wb") as fh:
                        while True:
                            chunk = resp.read(1 << 20)
                            if not chunk:
                                break
                            digest.update(chunk)
                            fh.write(chunk)
                            total += len(chunk)
        except Exception as e:
            dest.unlink(missing_ok=True)
            return False, f"download failed: {str(e)[:140]}"

        if total == 0:
            dest.unlink(missing_ok=True)
            return False, "download was empty."
        got = digest.hexdigest()
        if expected_sha and got != expected_sha.lower():
            dest.unlink(missing_ok=True)
            return False, (f"checksum mismatch (expected {expected_sha[:12]}…, got {got[:12]}…) "
                           "— refusing to install an unverified build.")
        return True, got

    def _expected_sha(self, asset: str, tag: Optional[str] = None) -> Tuple[str, str]:
        """(sha, error) for `asset` from the release's SHA256SUMS.txt."""
        try:
            text = self._fetch_bytes(self._release_url("SHA256SUMS.txt", tag)).decode("utf-8", "replace")
        except Exception as e:
            return "", f"could not fetch SHA256SUMS.txt: {str(e)[:140]}"
        for line in text.splitlines():
            parts = line.split()
            # "<sha256>  <filename>" — the '*' marks binary mode in some writers.
            if len(parts) >= 2 and parts[-1].lstrip("*") == asset:
                return parts[0].strip().lower(), ""
        return "", f"{asset} has no entry in SHA256SUMS.txt — refusing to install unverified."

    def _appimage_upgrade(self) -> Tuple[Optional[bool], str]:
        """Fetch, verify and place the released AppImage.

        Returns None (not a failure) when already current.
        """
        tag = self._latest_tag()
        want = tag.lstrip("v")
        asset = f"ELI_v2-{want}-x86_64.AppImage"
        running = os.environ.get("APPIMAGE") or ""
        if not running:
            return False, ("this is a frozen build but APPIMAGE is unset, so I cannot locate the "
                           f"running AppImage to replace. Download it yourself: "
                           f"{self._release_url(asset, tag)}")

        current = Path(running)
        have = self._local_version()
        # Never move backwards: a mis-tagged or yanked release must not be able
        # to talk a newer install into downgrading itself.
        if _ver_tuple(want) <= _ver_tuple(have):
            return None, f"already on {have} (latest published is {want}) — nothing to fetch."

        expected, err = self._expected_sha(asset, tag)
        if err:
            return False, err

        target = current.with_name(asset)
        tmp = current.with_name(asset + ".part")
        self._log(f"     downloading {asset} (~1.4 GB) → {tmp.parent}")
        ok, detail = self._download_verified(self._release_url(asset, tag), tmp, expected)
        if not ok:
            return False, detail
        try:
            tmp.chmod(0o755)
        except Exception as e:
            self._log(f"     could not set the executable bit: {e}")

        try:
            if target.name == current.name:
                # Stable filename (e.g. plain ELI.AppImage): swap in place. Safe
                # while running — the live process keeps its old inode — and the
                # previous build stays recoverable.
                backup = current.with_name(current.name + ".bak")
                backup.unlink(missing_ok=True)
                os.replace(current, backup)
                os.replace(tmp, target)
                return True, (f"{have} → {want}. Replaced {target.name}; previous build kept as "
                              f"{backup.name}. Restart ELI to run it.")
            # Versioned filename: place the new build alongside and leave the
            # running one alone. Overwriting a file NAMED …2.1.46… with 2.1.47
            # content would be a lie on disk, and an upgrade must not be able to
            # cost the user their only working ELI.
            os.replace(tmp, target)
            return True, (f"{have} → {want}. Verified and saved {target}. Restart ELI from that "
                          f"file — your {have} build is untouched at {current.name}.")
        except Exception as e:
            tmp.unlink(missing_ok=True)
            return False, f"could not place the new build: {str(e)[:140]}"

    def _frozen_upgrade(self) -> Tuple[Optional[bool], str]:
        """Windows .exe / macOS .app — no in-place swap; point at the installer."""
        tag = self._latest_tag()
        want = tag.lstrip("v")
        have = self._local_version()
        if _ver_tuple(want) <= _ver_tuple(have):
            return None, f"already on {have} (latest published is {want}) — nothing to fetch."
        url = f"https://github.com/{_DEFAULT_RELEASE_REPO}/releases/tag/{tag}"
        return False, (f"this packaged build cannot replace itself in place. Download {want} "
                       f"and run the installer: {url}")

    def _release_upgrade(self) -> Tuple[Optional[bool], str]:
        """Install/upgrade from the published GitHub release wheel (not stale git)."""
        repo = _DEFAULT_RELEASE_REPO
        tag = _DEFAULT_RELEASE_TAG
        work = Path(tempfile.mkdtemp(prefix="eli_release_upgrade_"))
        try:
            dl = _run(
                ["gh", "release", "download", tag, "--repo", repo,
                 "--pattern", "eli_v2_0-*.whl", "--dir", str(work), "--clobber"],
                timeout=180,
            )
            # The release pipeline publishes installers (.AppImage/.exe/.dmg/.zip/
            # .tar.gz), never a wheel — so this is a permanent structural absence,
            # not a failure of this run. Report it as not-applicable so it stops
            # showing up as a broken step on every upgrade.
            if not dl["ok"]:
                return None, f"release {tag} publishes no wheel — not applicable to this install."
            wheels = sorted(work.glob("eli_v2_0-*.whl"))
            if not wheels:
                return None, f"release {tag} publishes no wheel — not applicable to this install."
            wheel = wheels[-1]
            before = self._local_version()
            ins = _run(
                [sys.executable, "-m", "pip", "install", "-q", "--upgrade", str(wheel)],
                timeout=300,
            )
            if not ins["ok"]:
                return False, ins["stderr"][:120]
            after = self._local_version()
            return True, f"Release wheel {wheel.name} ({before} → {after})"
        finally:
            try:
                for p in work.glob("*"):
                    p.unlink(missing_ok=True)
                work.rmdir()
            except Exception:
                pass

    def _git_pull(self):
        """Pull only when origin is strictly ahead (ff-only — never force, never downgrade)."""
        git = _run(["git", "rev-parse", "--is-inside-work-tree"])
        if not git["ok"]:
            return False, "Not a git repository — skipped."
        fetch = _run(["git", "fetch", "--quiet", "origin"], timeout=120)
        if not fetch["ok"]:
            return False, f"fetch failed: {fetch['stderr'][:80]}"
        upstream = _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        if not upstream["ok"]:
            return False, "No upstream branch — skipped pull."
        local = _run(["git", "rev-parse", "HEAD"])
        remote = _run(["git", "rev-parse", upstream["stdout"]])
        if not local["ok"] or not remote["ok"]:
            return False, "Could not compare local/remote revisions."
        if local["stdout"] == remote["stdout"]:
            return True, "Already up to date with origin."
        # Local is ahead — do not pull (avoids replacing newer local work with older remote).
        ancestor = _run(["git", "merge-base", "--is-ancestor", remote["stdout"], "HEAD"])
        if ancestor["ok"] and ancestor["returncode"] == 0:
            return True, "Local checkout is ahead of origin — skipped pull."
        r = _run(["git", "pull", "--ff-only"])
        if r["ok"]:
            detail = r["stdout"].splitlines()[0] if r["stdout"] else "Fast-forwarded."
            return True, detail
        return False, r["stderr"][:120]

    def _pip_upgrade(self):
        """Reinstall ELI package in editable mode to pick up any new deps."""
        # Prefer pyproject.toml editable install; fall back to requirements.txt.
        pyproject = PROJECT_ROOT / "pyproject.toml"
        req = PROJECT_ROOT / "requirements.txt"
        if pyproject.exists():
            r = _run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "-e", str(PROJECT_ROOT)], timeout=180)
        elif req.exists():
            r = _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], timeout=180)
        else:
            r = _run([sys.executable, "-m", "pip", "install", "-q", "-e", str(PROJECT_ROOT)], timeout=180)
        if r["ok"]:
            return True, "Dependencies up to date."
        return False, r["stderr"][:120]

    def _rebuild_faiss(self):
        """Rebuild the FAISS vector index by re-embedding all stored memories."""
        try:
            from eli.memory import rebuild_vector_index_from_search_db
            result = rebuild_vector_index_from_search_db()
            if not result.get("ok"):
                return False, str(result.get("error", result))[:120]
            return True, (
                "FAISS index rebuilt "
                f"({result.get('indexed', 0)}/{result.get('source_count', 0)} vectors)."
            )
        except Exception as e:
            # Primary import failed; try the canonical rebuild script path.
            script = PROJECT_ROOT / "eli" / "scripts" / "rebuild_vector_index.py"
            if script.exists():
                r = _run([sys.executable, str(script)], timeout=120)
                return r["ok"], r["stdout"][:80] or r["stderr"][:80]
            return False, str(e)[:120]

    def _rebuild_kg(self):
        """Rebuild the knowledge graph by re-extracting triples from stored memories."""
        try:
            from eli.memory.knowledge_graph import get_knowledge_graph
            from eli.memory import get_search_memory
            kg = get_knowledge_graph()
            mem = get_search_memory()
            conn = mem._get_connection()
            try:
                rows = conn.execute(
                    "SELECT COALESCE(text, content, ''), COALESCE(source, 'user') "
                    "FROM memories ORDER BY id"
                ).fetchall()
            finally:
                conn.close()
            count = 0
            for text, source in rows:
                t = (text or "").strip()
                if t:
                    kg.extract_from_memory(t, source=source)
                    count += 1
            return True, f"Knowledge graph rebuilt from {count} memories."
        except Exception as e:
            return False, str(e)[:120]

    def _update_manifest(self):
        """Update the capability manifest."""
        try:
            from eli.tools.registry.capability_updater import update_capability_manifest
            update_capability_manifest()
            return True, "Manifest updated."
        except Exception as e:
            script = PROJECT_ROOT / "canonical_capability_inventory.py"
            if script.exists():
                r = _run([sys.executable, str(script)], timeout=60)
                return r["ok"], "Manifest updated via script." if r["ok"] else r["stderr"][:80]
            return False, str(e)[:120]

    def _refresh_system_index(self):
        """Refresh the system app/executable index after an upgrade."""
        try:
            from eli.memory.system_index import refresh_index
            refresh_index()
            return True, "System index refreshed."
        except Exception as e:
            return False, str(e)[:120]
