from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths

        return Path(get_paths().project_root)
    except Exception:
        return Path(__file__).resolve().parents[2]


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _first_heading(readme: Path) -> str:
    try:
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or readme.parent.name
            if stripped:
                return stripped[:120]
    except Exception:
        pass
    return readme.parent.name if readme.exists() else ""


def _project_record(project_dir: Path, root: Path) -> Dict[str, Any]:
    files = [p for p in project_dir.rglob("*") if p.is_file()]
    scripts = sorted(p for p in files if p.suffix == ".py" or p.name.endswith(".sh"))
    assets = sorted(
        p for p in files
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    )
    configs = sorted(
        p for p in files
        if p.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini"}
        or "config" in p.parts
    )
    readme = project_dir / "README.md"
    name_low = project_dir.name.lower()
    if "backup" in name_low or "bad_calibration" in name_low:
        lifecycle = "backup"
    elif scripts or assets:
        lifecycle = "active_candidate"
    else:
        lifecycle = "unknown"

    return {
        "name": project_dir.name,
        "path": str(project_dir),
        "relative_path": _relative(project_dir, root),
        "title": _first_heading(readme) or project_dir.name,
        "lifecycle": lifecycle,
        "readme_exists": readme.exists(),
        "readme_path": str(readme) if readme.exists() else "",
        "file_count": len(files),
        "script_count": len(scripts),
        "asset_count": len(assets),
        "config_count": len(configs),
        "scripts": [_relative(p, project_dir) for p in scripts[:24]],
        "assets": [_relative(p, project_dir) for p in assets[:16]],
        "configs": [_relative(p, project_dir) for p in configs[:16]],
    }


def build_experimental_inventory(root: str | Path | None = None) -> Dict[str, Any]:
    """Return a safe local inventory of repo-root experimental projects.

    This function never executes experimental code. It only reads file names and
    README headings so GUI and audit surfaces can show the area safely.
    """

    exp_root = Path(root) if root is not None else _project_root() / "experimental"
    exp_root = exp_root.expanduser().resolve()
    if not exp_root.exists():
        return {
            "ok": False,
            "root": str(exp_root),
            "exists": False,
            "projects": [],
            "archives": [],
            "counts": {
                "projects": 0,
                "active_projects": 0,
                "backup_projects": 0,
                "files": 0,
                "scripts": 0,
                "assets": 0,
                "configs": 0,
                "archives": 0,
            },
        }

    projects: List[Dict[str, Any]] = [
        _project_record(p, exp_root)
        for p in sorted(exp_root.iterdir())
        if p.is_dir()
    ]
    archives = sorted(p for p in exp_root.iterdir() if p.is_file() and p.suffix.lower() == ".zip")
    all_files = [p for p in exp_root.rglob("*") if p.is_file()]
    scripts = [p for p in all_files if p.suffix == ".py" or p.name.endswith(".sh")]
    assets = [
        p for p in all_files
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    ]
    configs = [
        p for p in all_files
        if p.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini"}
        or "config" in p.parts
    ]

    return {
        "ok": True,
        "root": str(exp_root),
        "exists": True,
        "projects": projects,
        "archives": [
            {
                "name": p.name,
                "path": str(p),
                "relative_path": _relative(p, exp_root),
                "size_bytes": p.stat().st_size if p.exists() else 0,
            }
            for p in archives
        ],
        "counts": {
            "projects": len(projects),
            "active_projects": sum(1 for p in projects if p.get("lifecycle") == "active_candidate"),
            "backup_projects": sum(1 for p in projects if p.get("lifecycle") == "backup"),
            "files": len(all_files),
            "scripts": len(scripts),
            "assets": len(assets),
            "configs": len(configs),
            "archives": len(archives),
        },
    }

