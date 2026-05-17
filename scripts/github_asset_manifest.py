#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]


def _git_ignored_files() -> List[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "--ignored", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    raw = proc.stdout.split(b"\0")
    files: List[Path] = []
    for item in raw:
        if not item:
            continue
        path = ROOT / item.decode("utf-8", errors="replace")
        if path.is_file():
            files.append(path)
    return files


def _sha256(path: Path, limit_bytes: int = 0) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        remaining = int(limit_bytes or 0)
        while True:
            if remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                remaining -= len(chunk)
            else:
                chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            if limit_bytes and remaining <= 0:
                break
    return h.hexdigest()


def _classify(rel: str) -> Dict[str, Any]:
    if rel.startswith(".venv/") or "/site-packages/" in rel:
        return {
            "category": "rebuildable_virtualenv",
            "upload_recommended": False,
            "reason": "recreated by install scripts; huge and machine-specific",
        }
    if rel.startswith("models/"):
        return {
            "category": "model_asset",
            "upload_recommended": True,
            "reason": "required for offline local model/image operation",
        }
    if rel.startswith("tts_piper/"):
        return {
            "category": "voice_asset",
            "upload_recommended": True,
            "reason": "required for bundled offline TTS voices",
        }
    if rel.startswith("artifacts/"):
        return {
            "category": "runtime_private_state",
            "upload_recommended": False,
            "reason": "contains local runtime state, memories, generated outputs, or logs",
        }
    if "__pycache__" in rel or rel.endswith(".pyc"):
        return {
            "category": "cache",
            "upload_recommended": False,
            "reason": "rebuildable Python cache",
        }
    if rel.endswith((".bak", ".backup")) or ".bak_" in rel or ".bak_" in Path(rel).name:
        return {
            "category": "local_backup",
            "upload_recommended": False,
            "reason": "local patch backup",
        }
    return {
        "category": "ignored_other",
        "upload_recommended": False,
        "reason": "ignored by repository policy",
    }


def build_manifest(include_hashes: bool = False) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    by_category: Dict[str, Dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    for path in _git_ignored_files():
        rel = str(path.relative_to(ROOT))
        stat = path.stat()
        meta = _classify(rel)
        row = {
            "path": rel,
            "bytes": int(stat.st_size),
            "category": meta["category"],
            "upload_recommended": bool(meta["upload_recommended"]),
            "reason": meta["reason"],
        }
        if include_hashes:
            row["sha256"] = _sha256(path)
        rows.append(row)
        cat = row["category"]
        by_category[cat]["files"] += 1
        by_category[cat]["bytes"] += int(stat.st_size)

    rows.sort(key=lambda r: (-int(r["bytes"]), str(r["path"])))
    total_bytes = sum(int(r["bytes"]) for r in rows)
    upload_bytes = sum(int(r["bytes"]) for r in rows if r["upload_recommended"])
    return {
        "schema": "eli_github_asset_manifest_v1",
        "project_root": str(ROOT),
        "repo_hint": "ShadowESC95/ELI_MKXI_v2.0_PRO",
        "total_ignored_files": len(rows),
        "total_ignored_bytes": total_bytes,
        "recommended_upload_bytes": upload_bytes,
        "categories": dict(sorted(by_category.items())),
        "files": rows,
        "notes": [
            "GitHub normal Git rejects files over 100 MB.",
            "Use release assets or external object storage for large model/voice payloads.",
            "Do not upload .venv or runtime_private_state unless you explicitly accept local-state leakage and platform lock-in.",
        ],
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    include_hashes = "--hash" in args
    output = ROOT / "dist" / "github_assets" / "asset_manifest.json"
    if "--output" in args:
        idx = args.index("--output")
        try:
            output = Path(args[idx + 1]).expanduser()
        except IndexError:
            raise SystemExit("--output requires a path")

    manifest = build_manifest(include_hashes=include_hashes)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Ignored files: {manifest['total_ignored_files']}")
    print(f"Ignored bytes: {manifest['total_ignored_bytes']}")
    print(f"Recommended upload bytes: {manifest['recommended_upload_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

