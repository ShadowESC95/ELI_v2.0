from __future__ import annotations

import os
from pathlib import Path


def _physical_project_root() -> Path:
    """
    Resolve the project root from this file's actual location.

    Expected source layout:
        <root>/eli/tools/image_engine/runtime_paths.py

    This is the safest default for portable / copied / multi-user installs.
    """
    here = Path(__file__).resolve()

    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "eli").is_dir():
            return parent

    try:
        return here.parents[3]
    except Exception:
        return Path.cwd().resolve()


def project_root() -> Path:
    """
    Return the active ELI project root.

    Authority order:
    1. Physical module location.
    2. ELI_PROJECT_ROOT only if it points to the same physical tree.
    3. ELI_PROJECT_ROOT as fallback only when physical detection failed.

    This prevents a copied clean-room install from inheriting another user's
    stale /home/... project root through the shell environment.
    """
    physical = _physical_project_root()

    env_root_raw = os.getenv("ELI_PROJECT_ROOT", "").strip()
    if env_root_raw:
        try:
            env_root = Path(env_root_raw).expanduser().resolve()
            here = Path(__file__).resolve()

            # Accept env override only when this module is physically inside it.
            try:
                here.relative_to(env_root)
                return env_root
            except ValueError:
                pass

            # If physical detection failed badly, allow env as last-resort fallback.
            if not (physical / "eli").is_dir():
                return env_root
        except Exception:
            pass

    return physical


def artifacts_dir() -> Path:
    """
    Return local runtime artifacts directory for this install.

    ELI_ARTIFACTS_DIR is accepted only if ELI_PROJECT_ROOT is valid for this
    physical tree or if the caller intentionally exports it for this process.
    """
    env_artifacts = os.getenv("ELI_ARTIFACTS_DIR", "").strip()
    env_root_raw = os.getenv("ELI_PROJECT_ROOT", "").strip()

    if env_artifacts and env_root_raw:
        try:
            env_root = Path(env_root_raw).expanduser().resolve()
            here = Path(__file__).resolve()
            here.relative_to(env_root)
            p = Path(env_artifacts).expanduser().resolve()
        except Exception:
            p = project_root() / "artifacts"
    else:
        p = project_root() / "artifacts"

    p.mkdir(parents=True, exist_ok=True)
    return p


def image_engine_root() -> Path:
    p = artifacts_dir() / "image_engine"
    p.mkdir(parents=True, exist_ok=True)
    return p


def image_outputs_dir() -> Path:
    p = image_engine_root() / "outputs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def image_logs_dir() -> Path:
    p = image_engine_root() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def image_jobs_dir() -> Path:
    p = image_outputs_dir() / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def image_index_db() -> Path:
    p = image_logs_dir() / "image_index.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
