#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from github_asset_manifest import ROOT, build_manifest


DEFAULT_REPO = "ShadowESC95/ELI_MKXI_v2.0_PRO"
DEFAULT_TAG = "local-assets-v2.0"
DEFAULT_CHUNK_BYTES = 1_900_000_000


def _run(cmd: List[str], cwd: Path = ROOT) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def _asset_name(rel: str) -> str:
    safe = rel.replace("/", "__").replace("\\", "__").replace(" ", "_")
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    safe = "".join(ch if ch in keep else "_" for ch in safe)
    return f"asset__{safe}"


def _ensure_release(repo: str, tag: str) -> None:
    view = subprocess.run(["gh", "release", "view", tag, "--repo", repo], cwd=ROOT)
    if view.returncode == 0:
        return
    _run([
        "gh", "release", "create", tag,
        "--repo", repo,
        "--title", "ELI MKXI v2.0 PRO local model and voice assets",
        "--notes",
        "Large local assets uploaded as direct files/chunks. Restore with scripts/restore_github_asset_files.py.",
    ])


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        dst.unlink()
    if src.is_symlink():
        shutil.copy2(src.resolve(), dst)
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _split_file(src: Path, prefix: Path, chunk_bytes: int) -> List[Path]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for old in prefix.parent.glob(prefix.name + "*"):
        old.unlink()
    _run(["split", "-b", str(chunk_bytes), "-d", "-a", "4", str(src), str(prefix)])
    return sorted(prefix.parent.glob(prefix.name + "*"))


def _selected_rows(manifest: Dict[str, Any], include_runtime: bool, include_venv: bool) -> List[Dict[str, Any]]:
    rows = []
    for row in manifest.get("files") or []:
        category = row.get("category")
        if row.get("upload_recommended"):
            rows.append(row)
            continue
        if include_runtime and category == "runtime_private_state":
            rows.append(row)
            continue
        if include_venv and category == "rebuildable_virtualenv":
            rows.append(row)
            continue
    return rows


def upload(args: argparse.Namespace) -> int:
    repo = args.repo
    tag = args.tag
    work = Path(args.work_dir).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    _ensure_release(repo, tag)

    manifest = build_manifest(include_hashes=False)
    rows = _selected_rows(manifest, args.include_runtime, args.include_venv)
    plan_path = work / "direct_asset_manifest.json"
    if plan_path.exists():
        upload_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        upload_plan.setdefault("files", [])
        upload_plan["repo"] = repo
        upload_plan["tag"] = tag
        upload_plan["chunk_bytes"] = int(args.chunk_bytes)
    else:
        upload_plan: Dict[str, Any] = {
            "schema": "eli_direct_github_asset_plan_v1",
            "repo": repo,
            "tag": tag,
            "chunk_bytes": int(args.chunk_bytes),
            "files": [],
        }
    completed = {str(row.get("path")) for row in upload_plan.get("files") or []}
    plan_path.write_text(json.dumps(upload_plan, indent=2), encoding="utf-8")
    _run(["gh", "release", "upload", tag, str(plan_path), "--repo", repo, "--clobber"])

    for idx, row in enumerate(rows, 1):
        rel = str(row["path"])
        if rel in completed:
            print(f"[asset {idx}/{len(rows)}] skip completed {rel}", flush=True)
            continue
        src = ROOT / rel
        if not src.exists() or not src.is_file():
            continue
        size = int(row["bytes"])
        base_name = _asset_name(rel)
        entry = {
            "path": rel,
            "bytes": size,
            "category": row.get("category"),
            "assets": [],
        }
        print(f"[asset {idx}/{len(rows)}] {rel} ({size} bytes)", flush=True)
        if size == 0:
            print("  [empty] recorded without GitHub asset upload", flush=True)
        elif size > int(args.chunk_bytes):
            prefix = work / f"{base_name}.part-"
            chunks = _split_file(src, prefix, int(args.chunk_bytes))
            for chunk in chunks:
                _run(["gh", "release", "upload", tag, str(chunk), "--repo", repo, "--clobber"])
                entry["assets"].append(chunk.name)
                if not args.keep_work:
                    chunk.unlink()
        else:
            staged = work / base_name
            if staged.exists() or staged.is_symlink():
                staged.unlink()
            _link_or_copy(src, staged)
            _run(["gh", "release", "upload", tag, str(staged), "--repo", repo, "--clobber"])
            entry["assets"].append(staged.name)
            if not args.keep_work:
                staged.unlink()

        upload_plan["files"].append(entry)
        plan_path.write_text(json.dumps(upload_plan, indent=2), encoding="utf-8")
        _run(["gh", "release", "upload", tag, str(plan_path), "--repo", repo, "--clobber"])

    print(f"Wrote upload plan: {plan_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload large ELI local assets directly/chunked to GitHub Release.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    parser.add_argument("--work-dir", default=str(ROOT / "dist" / "github_assets" / "direct_work"))
    parser.add_argument("--include-runtime", action="store_true", help="include artifacts/ private runtime state")
    parser.add_argument("--include-venv", action="store_true", help="include .venv machine-specific environment")
    parser.add_argument("--keep-work", action="store_true", help="keep staged upload files/chunks")
    args = parser.parse_args()
    return upload(args)


if __name__ == "__main__":
    raise SystemExit(main())
