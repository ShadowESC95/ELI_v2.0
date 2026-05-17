#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "ShadowESC95/ELI_MKXI_v2.0_PRO"
DEFAULT_TAG = "local-assets-v2.0"


def _run(cmd: List[str], cwd: Path = ROOT) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def _download(repo: str, tag: str, download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    _run(["gh", "release", "download", tag, "--repo", repo, "--dir", str(download_dir), "--clobber"])


def _cat_assets(asset_paths: List[Path], dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as out:
        for path in asset_paths:
            with path.open("rb") as src:
                shutil.copyfileobj(src, out, length=1024 * 1024)


def restore(args: argparse.Namespace) -> int:
    download_dir = Path(args.download_dir).expanduser().resolve()
    if not args.from_dir:
        _download(args.repo, args.tag, download_dir)
    else:
        download_dir = Path(args.from_dir).expanduser().resolve()

    manifest_path = download_dir / "direct_asset_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"direct_asset_manifest.json not found in {download_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    for idx, row in enumerate(files, 1):
        rel = row.get("path")
        assets = [download_dir / name for name in (row.get("assets") or [])]
        missing = [str(p) for p in assets if not p.exists()]
        if missing:
            raise SystemExit(f"Missing assets for {rel}: {missing[:5]}")
        dst = ROOT / str(rel)
        print(f"[restore {idx}/{len(files)}] {rel}", flush=True)
        _cat_assets(assets, dst)
    print("[restore] Complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore direct/chunked ELI local assets from GitHub Release.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--download-dir", default=str(ROOT / "dist" / "github_assets" / "direct_download"))
    parser.add_argument("--from-dir", default="", help="restore from an existing local download directory")
    args = parser.parse_args()
    return restore(args)


if __name__ == "__main__":
    raise SystemExit(main())

