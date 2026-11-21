"""The source of every GPL package a release bundle carries, at the version it carries, and where the
source of every LGPL one is.

GPL-3.0 lets a program be passed on as a binary when its Corresponding Source goes with it, or is
offered beside it. The frozen builds carry piper-tts (espeak-ng compiled into it) and PyAutoGUI's
helpers MouseInfo, PyMsgBox and, on Linux, python3-xlib, all under the GPL (THIRD_PARTY_NOTICES.md).
The release workflow runs this in the Linux build's environment, which holds every package the
Windows and macOS builds carry plus a few for Linux alone, and attaches what it fetched to the release:

    python packaging/gpl_sources.py OUT_DIR    # the GPL sources into OUT_DIR, listed in SOURCES.md,
                                               # and LGPL_SOURCES.md beside them
    python packaging/gpl_sources.py --list     # name them (no network)

GPL packages: every installed distribution whose licence metadata names the GPL or AGPL and offers no
LGPL choice. The source is that version's sdist from PyPI, checked against PyPI's digest; without one,
the project's repository at the version's tag. A package that carries compiled code whose build files
the sdist leaves out also gets the repository at the tag: piper-tts's sdist has neither its
CMakeLists.txt nor the C source of its espeak bridge. When a package's build fetches more source (CMake
ExternalProject or FetchContent, as piper-tts does for espeak-ng), that is fetched too, at the commit
the build names.

LGPL packages (Qt for Python and the Qt libraries inside its wheels, zeroconf, chardet, python-xlib and
whatever else the environment holds): every installed distribution whose licence metadata names the
LGPL. Their source is not attached; GPL-3.0 section 6(d), which LGPL-3.0 section 4 applies, lets it be
offered from another server when clear directions next to the object code say where. LGPL_SOURCES.md
is those directions: each package, its version and the address of that version's source: the sdist
PyPI lists for it, with its digest; for a project with none, the archive it publishes (SOURCE_ARCHIVES)
or its GitHub repository at the version's tag; for Qt, its source at the version the wheels carry
(QT_SOURCE). An address not read from PyPI is used only once it answers.

Anything that cannot be fetched or found stops the run: a release must not go out without it.

Standard library only: it runs before anything else is known to be installed.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
LGPL_LISTING = "LGPL_SOURCES.md"

# Projects that put no sdist on PyPI, by the repository their metadata names, with the archive of each
# version's source the project publishes, tried in order (the first that answers is listed). Qt for
# Python's wheels (PySide6, PySide6_Essentials, PySide6_Addons, shiboken6) come from one tree.
SOURCE_ARCHIVES: Dict[str, Tuple[str, ...]] = {
    "code.qt.io/cgit/pyside/pyside-setup.git": (
        "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/"
        "pyside-setup-everywhere-src-{version}.tar.xz",
        "https://code.qt.io/cgit/pyside/pyside-setup.git/snapshot/pyside-setup-v{version}.tar.gz",
    ),
}
# Qt itself, the C++ libraries inside those wheels, at the version they carry: the archive a release
# stays in first, then where a current release is published before it moves there.
QT_SOURCE: Tuple[str, ...] = (
    "https://download.qt.io/archive/qt/{minor}/{version}/single/qt-everywhere-src-{version}.tar.xz",
    "https://download.qt.io/official_releases/qt/{minor}/{version}/single/qt-everywhere-src-{version}.tar.xz",
)
# A distribution file that is a Qt library (libQt6Core.so.6, Qt6Core.dll, QtCore.framework/...), and
# the one that is Qt's core, whose package is asked which Qt it is.
_QT_LIBRARY = re.compile(r"(?:^|/)(?:lib)?Qt\d+\w*\.(?:so[.\d]*|dll|dylib)$|(?:^|/)Qt\w*\.framework/")
_QT_CORE = re.compile(r"(?:^|/)(?:lib)?Qt\d*Core(?:\.so[.\d]*|\.dll|\.dylib)?$|(?:^|/)QtCore\.framework/")

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
                                   "licence": "; ".join(facts), "home": _home_page(dist),
                                   "compiled": "yes" if _compiled(dist) else ""}
    return [found[k] for k in sorted(found)]


def _compiled(dist: metadata.Distribution) -> bool:
    """Whether the installed distribution carries compiled code: an extension module or a library."""
    return any(re.search(r"\.(?:so|pyd|dylib)(?:\.\d+)*$", str(f)) for f in (dist.files or []))


def is_lgpl(facts: List[str]) -> bool:
    """Under the LGPL, or with the LGPL among the licences offered (Qt for Python's wheels)."""
    return bool(_LGPL.search("\n".join(facts)))


def lgpl_distributions() -> List[Dict[str, object]]:
    """Each installed LGPL distribution, with the repositories its metadata names and the Qt
    libraries among its files (Qt for Python's wheels carry Qt's)."""
    found: Dict[str, Dict[str, object]] = {}
    for dist in metadata.distributions():
        name = str(dist.metadata.get("Name") or "").strip()
        facts = licence_facts(dist)
        if name and is_lgpl(facts):
            files = [str(f).replace("\\", "/") for f in (dist.files or [])]
            found[name.lower()] = {"name": name, "version": str(dist.version), "licence": "; ".join(facts),
                                   "home": _home_page(dist), "repos": _project_urls(dist),
                                   "qt_libraries": [f for f in files if _QT_LIBRARY.search(f)],
                                   "qt_core": next((f for f in files if _QT_CORE.search(f)), "")}
    return [found[k] for k in sorted(found)]


def _project_urls(dist: metadata.Distribution) -> List[str]:
    urls = [str(dist.metadata.get("Home-page") or "")]
    urls += [u.split(",", 1)[-1].strip() for u in (dist.metadata.get_all("Project-URL") or [])]
    return [u for u in urls if u]


def _home_page(dist: metadata.Distribution) -> str:
    urls = _project_urls(dist)
    for url in urls:
        if "github.com/" in url:
            return url
    return next((u for u in urls if u), "")


def _answers(url: str) -> bool:
    """Whether the server hands out this file: its first byte comes back."""
    request = urllib.request.Request(url, headers={"User-Agent": "eli-release-gpl-sources", "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return bool(response.read(1))
    except Exception as exc:  # an address that does not answer is reported by the caller, with the others tried
        print(f"[lgpl-sources] {url}: {exc}", file=sys.stderr)
        return False


def first_answering(urls: List[str]) -> Optional[str]:
    return next((url for url in urls if _answers(url)), None)


def qt_version(package: str) -> str:
    """The Qt a binding package carries, asked of its QtCore in a process of its own."""
    code = "import importlib, sys; print(importlib.import_module(sys.argv[1] + '.QtCore').qVersion())"
    ran = subprocess.run([sys.executable, "-c", code, package], capture_output=True, text=True, timeout=300)
    found = re.fullmatch(r"\d+\.\d+\.\d+", ran.stdout.strip())
    if ran.returncode != 0 or not found:
        raise ValueError(f"{package}.QtCore did not say which Qt it is: {(ran.stderr or ran.stdout).strip()[-300:]}")
    return found.group(0)


def lgpl_source(pkg: Dict[str, object]) -> str:
    """Where this version's source is: PyPI's sdist with its digest, else the archive its project
    publishes (SOURCE_ARCHIVES, by the repository its metadata names), else its GitHub repository at
    the version's tag; each but PyPI's checked to answer."""
    name, version = str(pkg["name"]), str(pkg["version"])
    try:
        sdist, pypi = pypi_sdist(name, version), "no sdist on PyPI"
    except Exception as exc:  # not on PyPI at all, or PyPI did not answer: the other addresses decide
        sdist, pypi = None, f"PyPI: {exc}"
    if sdist:
        return f"{sdist['url']} (sha256 {sdist['sha256']})"
    repos = [str(u) for u in pkg.get("repos") or []] or [str(pkg.get("home") or "")]
    tried = [t.format(version=version) for repo in repos for key, templates in SOURCE_ARCHIVES.items()
             if key in repo for t in templates]
    tried += [u for repo in repos for tag in (f"v{version}", version) for u in [github_archive(repo, tag)] if u]
    tried = list(dict.fromkeys(tried))
    url = first_answering(tried)
    if not url:
        raise ValueError(f"{pypi}, and none of these answers: {', '.join(tried) or 'no address to try'}")
    return url


def lgpl_listing(packages: List[Dict[str, object]]) -> Tuple[List[str], List[str]]:
    """The lines of LGPL_SOURCES.md, and what could not be found."""
    lines = ["# Where the source of the LGPL components in this release's builds is", "",
             "The builds carry these packages under the GNU Lesser General Public License, at the versions",
             "below. Their source is not in this archive: each line says where that version's source was",
             "when the release was built. See THIRD_PARTY_NOTICES.md for the licences.", ""]
    failed: List[str] = []
    for pkg in packages:
        try:
            lines.append(f"- {pkg['name']} {pkg['version']} ({pkg['licence']}): {lgpl_source(pkg)}")
        except Exception as exc:
            failed.append(f"{pkg['name']} {pkg['version']}: {exc}")
    carriers = [pkg for pkg in packages if pkg.get("qt_libraries")]
    core = next((str(pkg["qt_core"]) for pkg in carriers if pkg.get("qt_core")), "")
    if carriers:
        names = ", ".join(str(pkg["name"]) for pkg in carriers)
        try:
            if not core:
                raise ValueError("no Qt core library among their files")
            version = qt_version(core.split("/", 1)[0])
            minor = ".".join(version.split(".")[:2])
            tried = [t.format(minor=minor, version=version) for t in QT_SOURCE]
            url = first_answering(tried)
            if not url:
                raise ValueError(f"none of these answers: {', '.join(tried)}")
            lines.append(f"- Qt {version}, the libraries inside {names} (under their licence): {url}")
        except Exception as exc:
            failed.append(f"Qt, the libraries inside {names}: {exc}")
    return lines, failed


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


_CMAKE = ("CMakeLists.txt", ".cmake")
_NATIVE = (".c", ".cc", ".cpp", ".cxx", ".pyx")


def _members(archive: bytes, filename: str, suffixes: Tuple[str, ...]) -> List[Tuple[str, bytes]]:
    """(name, content) of each file in a source archive whose name ends with one of `suffixes`."""
    found: List[Tuple[str, bytes]] = []
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            found = [(n, z.read(n)) for n in z.namelist() if n.endswith(suffixes)]
    else:
        with tarfile.open(fileobj=io.BytesIO(archive)) as t:
            found = [(m.name, t.extractfile(m).read()) for m in t.getmembers()
                     if m.isfile() and m.name.endswith(suffixes)]
    return found


def _build_files(archive: bytes, filename: str) -> List[str]:
    """The CMake files inside a source archive."""
    return [body.decode("utf-8", "replace") for _name, body in _members(archive, filename, _CMAKE)]


def _tagged_archive(home: str, version: str) -> Tuple[bytes, str]:
    """The project's repository at the version's tag (v<version>, else <version>), and its address."""
    for url in [u for u in (github_archive(home, tag) for tag in (f"v{version}", version)) if u]:
        try:
            return _get(url), url
        except Exception:
            continue
    raise ValueError(f"no tag v{version} / {version} at {home or 'an unknown home page'}")


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
                try:
                    body, origin = _tagged_archive(pkg["home"], version)
                except ValueError as exc:
                    raise ValueError(f"no sdist on PyPI and {exc}") from None
                filename = f"{name}-{version}.tar.gz"
            (out_dir / filename).write_bytes(body)
            lines.append(f"- {name} {version} ({pkg['licence']}): `{filename}`, from {origin}")
            build_files = _build_files(body, filename)
            if sdist and pkg.get("compiled") and not _members(body, filename, _CMAKE + _NATIVE):
                repo_body, repo_url = _tagged_archive(pkg["home"], version)
                repo_name = f"{name}-{version}-repository.tar.gz"
                (out_dir / repo_name).write_bytes(repo_body)
                lines.append(f"  - the build files and C source of its compiled part, which the sdist leaves "
                             f"out: `{repo_name}`, from {repo_url}")
                build_files += _build_files(repo_body, repo_name)
            for kind, source, ref in cmake_fetches("\n".join(build_files)):
                url = source if kind == "url" else github_archive(source, ref)
                if not url:
                    raise ValueError(f"its build fetches {source} {ref or '(no fixed commit)'}, which this cannot download")
                part = re.sub(r"[^A-Za-z0-9._-]+", "-", url.split("github.com/", 1)[-1].replace("/archive/", "-"))
                (out_dir / part).write_bytes(_get(url))
                lines.append(f"  - built into it: `{part}`, from {url} (fetched by its CMake build)")
        except Exception as exc:
            failed.append(f"{name} {version}: {exc}")
    (out_dir / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lgpl_lines, lgpl_failed = lgpl_listing(lgpl_distributions())
    (out_dir / LGPL_LISTING).write_text("\n".join(lgpl_lines) + "\n", encoding="utf-8")
    for problem in failed:
        print(f"::error::GPL source not fetched: {problem}", file=sys.stderr)
    for problem in lgpl_failed:
        print(f"::error::LGPL source not found: {problem}", file=sys.stderr)
    return 1 if failed or lgpl_failed else 0


def main(argv: List[str]) -> int:
    if argv[:1] == ["--list"]:
        for pkg in gpl_distributions():
            print(f"{pkg['name']}=={pkg['version']}  ({pkg['licence']})")
        for pkg in lgpl_distributions():
            qt = "  carries Qt libraries" if pkg["qt_libraries"] else ""
            print(f"{pkg['name']}=={pkg['version']}  ({pkg['licence']}, source not attached: {LGPL_LISTING}){qt}")
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    return fetch_all(Path(argv[0]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
