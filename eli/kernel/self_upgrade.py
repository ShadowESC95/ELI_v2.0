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
_DEFAULT_RELEASE_TAG = os.environ.get("ELI_RELEASE_TAG", "v2.0.23")


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

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.log.append(entry)
        print(entry)

    # ── Public API (called by executor) ──────────────────────────────────────

    def upgrade(self, request: str = "") -> str:
        """Upgrade: prefer GitHub release wheel, then safe git ff-only, then indexes."""
        self.log.clear()
        self._log("Starting ELI self-upgrade…")

        steps = [
            ("Release upgrade", self._release_upgrade),
            ("Git pull (ff-only)", self._git_pull),
            ("Pip upgrade", self._pip_upgrade),
            ("Rebuild FAISS index", self._rebuild_faiss),
            ("Rebuild knowledge graph", self._rebuild_kg),
            ("Update capability manifest", self._update_manifest),
            ("Refresh system index", self._refresh_system_index),
        ]

        results = []
        for name, fn in steps:
            self._log(f"  → {name}…")
            try:
                ok, detail = fn()
                status = "✅" if ok else "⚠️"
                self._log(f"  {status} {name}: {detail}")
                results.append(f"{status} {name}: {detail}")
            except Exception as e:
                self._log(f"  ❌ {name} failed: {e}")
                results.append(f"❌ {name}: {e}")

        summary = f"Upgrade complete. {len([r for r in results if r.startswith('✅')])} / {len(results)} steps succeeded."
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
        try:
            import importlib.metadata as im
            return str(im.version("eli-v2.0"))
        except Exception:
            pass
        try:
            text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
            m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
            if m:
                return m.group(1)
        except Exception:
            pass
        return "0.0.0"

    def _release_upgrade(self) -> Tuple[bool, str]:
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
            if not dl["ok"]:
                return False, f"No release wheel ({tag}) — using local checkout: {dl['stderr'][:80]}"
            wheels = sorted(work.glob("eli_v2_0-*.whl"))
            if not wheels:
                return False, f"Release {tag} has no eli_v2_0 wheel — skipped."
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
