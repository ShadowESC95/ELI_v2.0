#!/usr/bin/env python3
"""
ELI mesh analysis helper.

Analyzes a mesh file (VTK/VTU/STL/etc) using meshio and writes a Markdown report.

Usage (module):
    from eli.perception.analyze_mesh import analyze_mesh_file
    result = analyze_mesh_file("/path/to/mesh.vtu", "/path/to/report.md")

Usage (CLI):
    python3 -m eli.perception.analyze_mesh --path mesh.vtu --out report.md
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional


def analyze_mesh_file(path: str, out_md: str) -> Dict[str, Any]:
    """
    Analyze a mesh file and write a Markdown report.

    Returns dict with keys: ok, path, points, dim, bounds, cells,
    point_data, cell_data, artifacts_dir, out_md.
    """
    try:
        import numpy as np  # type: ignore
        import meshio  # type: ignore
    except ImportError as e:
        return {
            "ok": False,
            "error": f"Missing dependency: {e}. Install with: pip install meshio numpy",
            "path": path,
        }

    p = Path(path).expanduser().resolve()
    outp = Path(out_md).expanduser().resolve()
    outp.parent.mkdir(parents=True, exist_ok=True)

    if not p.exists():
        return {"ok": False, "error": f"File not found: {p}", "path": str(p)}

    artifacts_dir = outp.parent / f"analyze_mesh_{time.strftime('%Y%m%d_%H%M%S')}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        mesh = meshio.read(str(p))
    except Exception as e:
        return {"ok": False, "error": f"meshio read failed: {e}", "path": str(p)}

    pts = np.asarray(mesh.points)
    bounds: Optional[Dict[str, Any]] = None
    if pts.size:
        bounds = {
            "min": pts.min(axis=0).tolist(),
            "max": pts.max(axis=0).tolist(),
        }

    cell_counts: Dict[str, int] = {c.type: len(c.data) for c in mesh.cells}

    point_data: Dict[str, Any] = {}
    for k, v in (mesh.point_data or {}).items():
        arr = np.asarray(v)
        try:
            finite = arr[np.isfinite(arr)]
            if finite.size:
                point_data[k] = {
                    "shape": list(arr.shape),
                    "min": float(finite.min()),
                    "max": float(finite.max()),
                }
            else:
                point_data[k] = {"shape": list(arr.shape)}
        except Exception:
            point_data[k] = {"shape": list(arr.shape)}

    cell_data: Dict[str, Any] = {}
    for k, vv in (mesh.cell_data or {}).items():
        shapes = [list(np.asarray(x).shape) for x in vv]
        cell_data[k] = {"blocks": len(vv), "shapes": shapes[:5]}

    report = {
        "ok": True,
        "path": str(p),
        "points": int(pts.shape[0]) if pts.ndim == 2 else 0,
        "dim": int(pts.shape[1]) if pts.ndim == 2 else None,
        "bounds": bounds,
        "cells": cell_counts,
        "point_data": point_data,
        "cell_data": cell_data,
        "artifacts_dir": str(artifacts_dir),
        "out_md": str(outp),
    }

    (artifacts_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    # Build Markdown
    md: list[str] = []
    md.append(f"# Mesh analysis: `{p.name}`\n\n")
    md.append(f"- Points: **{report['points']}** (dim {report['dim']})\n")
    if bounds:
        md.append(f"- Bounds min: `{bounds['min']}`\n")
        md.append(f"- Bounds max: `{bounds['max']}`\n")

    md.append("\n## Cell blocks\n")
    for k, n in cell_counts.items():
        md.append(f"- {k}: {n}\n")

    if point_data:
        md.append("\n## Point data\n")
        for k, info in point_data.items():
            rng = (
                f"range [{info.get('min')}, {info.get('max')}]"
                if "min" in info
                else ""
            )
            md.append(f"- {k}: shape {info.get('shape')} {rng}\n")

    if cell_data:
        md.append("\n## Cell data (summary)\n")
        for k, info in cell_data.items():
            md.append(f"- {k}: blocks {info.get('blocks')} shapes {info.get('shapes')}\n")

    outp.write_text("".join(md), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Analyze a mesh file")
    ap.add_argument("--path", required=True, help="Path to mesh file (VTU, STL, etc.)")
    ap.add_argument("--out", default="artifacts/mesh_report_latest.md", help="Output Markdown path")
    ns = ap.parse_args()
    print(json.dumps(analyze_mesh_file(ns.path, ns.out), indent=2))
