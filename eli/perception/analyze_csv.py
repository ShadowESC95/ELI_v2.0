from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import json
import time

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

def analyze_csv_file(path: str, out_md: str, max_rows: int = 2000) -> Dict[str, Any]:
    p = Path(path)
    outp = Path(out_md)
    outp.parent.mkdir(parents=True, exist_ok=True)

    if not p.exists():
        return {"ok": False, "error": "not_found", "path": str(p)}

    # Read with basic robustness
    try:
        df = pd.read_csv(p, nrows=int(max_rows))
        read_mode = "csv"
    except Exception:
        try:
            df = pd.read_excel(p, nrows=int(max_rows))
            read_mode = "excel"
        except Exception as e:
            return {"ok": False, "error": "read_failed", "detail": repr(e), "path": str(p)}

    artifacts_dir = outp.parent / f"analyze_csv_{time.strftime('%Y%m%d_%H%M%S')}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Basic profile
    shape = [int(df.shape[0]), int(df.shape[1])]
    cols = [str(c) for c in df.columns.tolist()]

    # per-column summary
    summary = {}
    for c in df.columns:
        s = df[c]
        info: Dict[str, Any] = {"dtype": str(s.dtype)}
        try:
            info["nulls"] = int(s.isna().sum())
        except Exception:
            pass

        # numeric stats if applicable
        try:
            if pd.api.types.is_numeric_dtype(s):
                finite = pd.to_numeric(s, errors="coerce").dropna()
                if len(finite):
                    info["min"] = float(finite.min())
                    info["max"] = float(finite.max())
                    info["mean"] = float(finite.mean())
        except Exception:
            pass

        # top values
        try:
            vc = s.astype(str).value_counts().head(10)
            info["top_values"] = [{"value": k, "count": int(v)} for k, v in vc.items()]
        except Exception:
            pass

        summary[str(c)] = info

    report = {
        "ok": True,
        "path": str(p),
        "read_mode": read_mode,
        "shape": shape,
        "columns": cols,
        "summary": summary,
        "artifacts_dir": str(artifacts_dir),
        "out_md": str(outp),
    }

    (artifacts_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Write markdown
    md = []
    md.append(f"# CSV analysis: `{p.name}`\n\n")
    md.append(f"- Read mode: `{read_mode}`\n")
    md.append(f"- Shape: **{shape[0]} rows × {shape[1]} cols**\n\n")
    md.append("## Columns\n")
    for c in cols:
        md.append(f"- `{c}` ({summary[c].get('dtype')}) nulls={summary[c].get('nulls')}\n")
    md.append("\n## Notes\n")
    md.append(f"- Profile saved: `{(artifacts_dir / 'report.json').as_posix()}`\n")
    outp.write_text("".join(md), encoding="utf-8")

    return report

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--out", default="artifacts/csv_report_latest.md")
    ap.add_argument("--max_rows", type=int, default=2000)
    ns = ap.parse_args()
    print(json.dumps(analyze_csv_file(ns.path, ns.out, ns.max_rows), indent=2))
