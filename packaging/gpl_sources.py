"""The source of every GPL package a release bundle carries, at the version it carries.

GPL-3.0 lets a program be passed on as a binary when its Corresponding Source goes with it, or is
offered beside it. The frozen builds carry piper-tts (espeak-ng compiled into it) and PyAutoGUI's
helpers MouseInfo, PyMsgBox and, on Linux, python3-xlib, all under the GPL (THIRD_PARTY_NOTICES.md).
The release workflow runs this in the Linux build's environment, which holds every package the
Windows and macOS builds carry plus a few for Linux alone, and attaches what it fetched to the release:

    python packaging/gpl_sources.py OUT_DIR    # each one's source into OUT_DIR, listed in SOURCES.md
    python packaging/gpl_sources.py --list     # name them (no network)

Which packages: every installed distribution whose licence metadata names the GPL or AGPL and offers
no LGPL choice (Qt's packages are used under the LGPL and keep their own source offer). The source is
that version's sdist from PyPI, checked against PyPI's digest; without one, the project's repository
at the version's tag. When a package's build fetches more source (CMake ExternalProject or
FetchContent, as piper-tts does for espeak-ng), that is fetched too, at the commit the build names.
Anything that cannot be fetched stops the run: a release must not go out without it.

Standard library only: it runs before anything else is known to be installed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"

_GPL = re.compile(r"(?<![A-Za-z])A?GPL|GNU (?:AFFERO )?GENERAL PUBLIC LICEN[CS]E", re.I)
_LGPL = re.compile(r"(?<![A-Za-z])LGPL|GNU (?:LESSER|LIBRARY) (?:GENERAL )?PUBLIC LICEN[CS]E", re.I)


def licence_facts(dist: metadata.Distribution) -> List[str]:
    """What a distribution says about its licence: the SPDX expression, the first line of its
    License field (some carry the whole text there) and its licence classifiers."""
    meta = dist.metadata
    facts = [str(meta.get("License-Expression") or "")]
    facts += [line for line in str(meta.get("License") or "").splitlines() if line.strip()][:1]
    facts += [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    return [f.strip() for f in facts if f and f.strip()]


def is_gpl(facts: List[str]) -> bool:
    """Under the GPL or AGPL with no LGPL choice. Mixed metadata (a BSD text, a GPL classifier) counts
    as GPL: shipping a source that was not owed costs nothing."""
    text = "\n".join(facts)
    return bool(_GPL.search(text)) and not _LGPL.search(text)


def gpl_distributions() -> List[Dict[str, str]]:
    found: Dict[str, Dict[str, str]] = {}
    for dist in metadata.distributions():
        name = str(dist.metadata.get("Name") or "").strip()
        facts = licence_facts(dist)
        if name and is_gpl(facts):
            found[name.lower()] = {"name": name, "version": str(dist.version),
                                   "licence": "; ".join(facts), "home": _home_page(dist)}
    return [found[k] for k in sorted(found)]


def _home_page(dist: metadata.Distribution) -> str:
    urls = [str(dist.metadata.get("Home-page") or "")]
    urls += [u.split(",", 1)[-1].strip() for u in (dist.metadata.get_all("Project-URL") or [])]
    for url in urls:
        if "github.com/" in url:
            return url
    return next((u for u in urls if u), "")


def cmake_fetches(text: str) -> List[Tuple[str, str, str]]:
    """("git", repository, ref) for each git source a CMake file's ExternalProject_Add or
    FetchContent_Declare fetches (ref "" when it names none), and ("url", url, "") for each archive."""
    out: List[Tuple[str, str, str]] = []
    for block in re.findall(r"(?:ExternalProject_Add|FetchContent_Declare)\s*\((.*?)\)\s*(?:\n|$)", text, re.S | re.I):
        repo = re.search(r"\bGIT_REPOSITORY\s+\"?([^\s\")]+)", block)
        ref = re.search(r"\bGIT_TAG\s+\"?([^\s\")]+)", block)
        url = re.search(r"\bURL\s+\"?(https?://[^\s\")]+)", block)
        if repo:
            out.append(("git", repo.group(1), ref.group(1) if ref else ""))
        elif url:
            out.append(("url", url.group(1), ""))
    return out


def github_archive(repo: str, ref: str) -> Optional[str]:
    """The tarball GitHub serves of `repo` at `ref` (a tag or a commit)."""
    m = re.match(r"(?:https?://|git@)github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?/?$", repo.strip(), re.I)
    if not m or not ref:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}/archive/{ref}.tar.gz"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "eli-release-gpl-sources"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def pypi_sdist(name: str, version: str) -> Optional[Dict[str, str]]:
    data = json.loads(_get(PYPI_JSON.format(name=name, version=version)).decode("utf-8"))
    for item in data.get("urls") or []:
        if item.get("packagetype") == "sdist":
            return {"url": item["url"], "filename": item["filename"], "sha256": item["digests"]["sha256"]}
    return None


def _build_files(archive: bytes, filename: str) -> List[str]:
    """The CMake files inside a source archive."""
    texts = []
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for n in z.namelist():
                if n.endswith(("CMakeLists.txt", ".cmake")):
                    texts.append(z.read(n).decode("utf-8", "replace"))
    else:
        with tarfile.open(fileobj=io.BytesIO(archive)) as t:
            for m in t.getmembers():
                if m.isfile() and m.name.endswith(("CMakeLists.txt", ".cmake")):
                    texts.append(t.extractfile(m).read().decode("utf-8", "replace"))
    return texts


def fetch_all(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Source of the GPL components in this release's builds", "",
             "Each package under the GPL that the builds carry, at the version they carry, and the",
             "source file here with where it came from. See THIRD_PARTY_NOTICES.md for the licences.", ""]
    failed = []
    for pkg in gpl_distributions():
        name, version = pkg["name"], pkg["version"]
        try:
            sdist = pypi_sdist(name, version)
            if sdist:
                body = _get(sdist["url"])
                if hashlib.sha256(body).hexdigest() != sdist["sha256"]:
                    raise ValueError(f"{sdist['filename']} does not match PyPI's sha256")
                filename, origin = sdist["filename"], sdist["url"]
            else:
                tagged = [github_archive(pkg["home"], tag) for tag in (f"v{version}", version)]
                body = filename = origin = None
                for url in [u for u in tagged if u]:
                    try:
                        body, origin = _get(url), url
                        break
                    except Exception:
                        continue
                if body is None:
                    raise ValueError(f"no sdist on PyPI and no tag v{version} / {version} at {pkg['home'] or 'an unknown home page'}")
                filename = f"{name}-{version}.tar.gz"
            (out_dir / filename).write_bytes(body)
            lines.append(f"- {name} {version} ({pkg['licence']}): `{filename}`, from {origin}")
            for kind, source, ref in cmake_fetches("\n".join(_build_files(body, filename))):
                url = source if kind == "url" else github_archive(source, ref)
                if not url:
                    raise ValueError(f"its build fetches {source} {ref or '(no fixed commit)'}, which this cannot download")
                part = re.sub(r"[^A-Za-z0-9._-]+", "-", url.split("github.com/", 1)[-1].replace("/archive/", "-"))
                (out_dir / part).write_bytes(_get(url))
                lines.append(f"  - built into it: `{part}`, from {url} (fetched by its CMake build)")
        except Exception as exc:
            failed.append(f"{name} {version}: {exc}")
    (out_dir / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for problem in failed:
        print(f"::error::GPL source not fetched: {problem}", file=sys.stderr)
    return 1 if failed else 0


def main(argv: List[str]) -> int:
    if argv[:1] == ["--list"]:
        for pkg in gpl_distributions():
            print(f"{pkg['name']}=={pkg['version']}  ({pkg['licence']})")
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    return fetch_all(Path(argv[0]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
