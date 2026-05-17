from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

PATH_KEY_RE = re.compile(r"(path|dir|file|folder|home|root|model)", re.I)


def project_root(start: str | Path | None = None) -> Path:
    """
    Resolve the ELI project root dynamically on any user's machine.

    Priority:
    1. ELI_HOME / ELI_PROJECT_ROOT environment variable.
    2. Walk upward from this file or supplied start path.
    3. Current working directory fallback.
    """
    for key in ("ELI_HOME", "ELI_PROJECT_ROOT"):
        raw = os.environ.get(key)
        if raw:
            p = Path(raw).expanduser().resolve()
            if (p / "eli").is_dir():
                return p

    p = Path(start or __file__).resolve()
    if p.is_file():
        p = p.parent

    for cur in (p, *p.parents):
        if (cur / "eli").is_dir() and (cur / "config").exists():
            return cur

    return Path.cwd().resolve()


PROJECT_ROOT = project_root()


def expand_project_vars(value: str, root: str | Path | None = None) -> str:
    """
    Expand portable project placeholders and normal OS variables.

    Supported:
    - ${ELI_HOME}
    - ${ELI_PROJECT_ROOT}
    - ${PROJECT_ROOT}
    - %ELI_HOME%
    - %ELI_PROJECT_ROOT%
    - %PROJECT_ROOT%
    - ~
    - normal environment variables
    """
    root_path = Path(root or PROJECT_ROOT).resolve()
    s = str(value)

    replacements = {
        "${ELI_HOME}": str(root_path),
        "${ELI_PROJECT_ROOT}": str(root_path),
        "${PROJECT_ROOT}": str(root_path),
        "%ELI_HOME%": str(root_path),
        "%ELI_PROJECT_ROOT%": str(root_path),
        "%PROJECT_ROOT%": str(root_path),
    }

    for k, v in replacements.items():
        s = s.replace(k, v)

    return os.path.expandvars(os.path.expanduser(s))


def resolve_path_value(value: Any, root: str | Path | None = None) -> Any:
    """
    Convert a config path value into an absolute path for this machine.

    Non-strings are returned unchanged.
    URLs are returned unchanged.
    Relative paths are resolved against the detected ELI project root.
    """
    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s:
        return value

    if "://" in s:
        return value

    expanded = expand_project_vars(s, root)
    p = Path(expanded)

    if p.is_absolute():
        return str(p)

    return str((Path(root or PROJECT_ROOT).resolve() / p).resolve())


def make_portable_path_value(value: Any, root: str | Path | None = None) -> Any:
    """
    Convert machine-specific absolute ELI paths into repo-relative paths.

    Example:
        <ELI_PROJECT_ROOT>/models/x.gguf
    becomes:
        models/x.gguf
    """
    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s or "://" in s:
        return value

    root_path = Path(root or PROJECT_ROOT).resolve()
    root_s = str(root_path).replace("\\", "/")
    norm = s.replace("\\", "/")

    if norm == root_s:
        return "."

    if norm.startswith(root_s + "/"):
        return norm[len(root_s) + 1:]

    # Strip Linux/macOS absolute project prefixes from any user's machine.
    m = re.search(r"[/\\](?:home|Users)[/\\][^/\\]+[/\\](?:Desktop|Documents|Downloads)?[/\\]?ELI_MKXI[/\\](.+)$", s)
    if m:
        return m.group(1).replace("\\", "/")

    # Strip temporary staging prefix.
    m = re.search(r"[/\\]ELI_MKXI_github_stage[/\\](.+)$", s)
    if m:
        return m.group(1).replace("\\", "/")

    return value


def normalize_settings_obj(obj: Any, root: str | Path | None = None) -> Any:
    """
    Recursively normalize settings dictionaries.

    Path-like keys are made portable.
    Nested dict/list structures are supported.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and PATH_KEY_RE.search(k) and isinstance(v, str):
                out[k] = make_portable_path_value(v, root)
            else:
                out[k] = normalize_settings_obj(v, root)
        return out

    if isinstance(obj, list):
        return [normalize_settings_obj(x, root) for x in obj]

    return obj
