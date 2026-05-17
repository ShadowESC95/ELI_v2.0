from __future__ import annotations

from pathlib import Path
from typing import Iterable


def _legacy_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []

    config_root = home / ".config"
    if config_root.exists():
        roots.extend(
            sorted(
                path
                for path in config_root.glob("eli-*")
                if path.is_dir() and path.name != "eli"
            )
        )

    roots.extend(sorted(path for path in home.glob(".eli_*") if path.is_dir()))
    return roots


def legacy_named_paths(*names: str) -> list[Path]:
    candidates: list[Path] = []
    for root in _legacy_roots():
        for name in names:
            candidate = root / name
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def latest_existing_path(candidates: Iterable[Path]) -> Path | None:
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime_ns)


def migrate_text_file(
    canonical_path: Path,
    legacy_candidates: Iterable[Path],
    *,
    default_text: str = "",
) -> Path:
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    if canonical_path.exists():
        return canonical_path

    legacy_path = latest_existing_path(legacy_candidates)
    if legacy_path is not None:
        try:
            canonical_path.write_text(
                legacy_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return canonical_path
        except Exception:
            pass

    canonical_path.write_text(default_text, encoding="utf-8")
    return canonical_path
