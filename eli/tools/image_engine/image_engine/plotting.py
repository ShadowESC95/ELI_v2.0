from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from . import visual_core as core


@dataclass(slots=True)
class PlotOutput:
    path: str
    spec: dict[str, Any]
    summary: dict[str, Any]


def _require_matplotlib():
    try:
        import logging
        logging.getLogger("matplotlib").setLevel(logging.WARNING)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Plot generation requires matplotlib. Install with: pip install matplotlib"
        ) from exc


def coerce_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    try:
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except ValueError:
        return text


def load_records(data_file: str | Path = "", data: Any = None) -> list[dict[str, Any]]:
    if data is not None:
        return records_from_object(data)

    if not data_file:
        raise ValueError("Plot jobs need --data, --json, or request['data'].")

    path = Path(data_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [
                {k: coerce_value(v) for k, v in row.items()}
                for row in csv.DictReader(f)
            ]

    if suffix in {".json", ".jsonl"}:
        if suffix == ".jsonl":
            records = []
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
            return records_from_object(records)
        return records_from_object(json.loads(path.read_text(encoding="utf-8")))

    raise ValueError("Supported plot data formats: .csv, .json, .jsonl")


def records_from_object(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, str):
        obj = json.loads(obj)

    if isinstance(obj, list):
        if not obj:
            return []
        if isinstance(obj[0], dict):
            return [{k: coerce_value(v) for k, v in row.items()} for row in obj]
        return [{"index": i, "value": coerce_value(v)} for i, v in enumerate(obj)]

    if isinstance(obj, dict):
        if "records" in obj:
            return records_from_object(obj["records"])
        if "data" in obj:
            return records_from_object(obj["data"])
        # Column-oriented object: {"x": [...], "y": [...]}
        if all(isinstance(v, list) for v in obj.values()):
            keys = list(obj)
            length = min(len(obj[k]) for k in keys) if keys else 0
            return [
                {k: coerce_value(obj[k][i]) for k in keys}
                for i in range(length)
            ]
        return [{k: coerce_value(v) for k, v in obj.items()}]

    raise ValueError("Unsupported data object for plotting.")


def numeric_columns(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return []
    keys = sorted({k for row in records for k in row})
    result = []
    for key in keys:
        vals = [row.get(key) for row in records if row.get(key) is not None]
        if vals and sum(isinstance(v, (int, float)) for v in vals) / len(vals) >= 0.75:
            result.append(key)
    return result


def first_text_column(records: list[dict[str, Any]]) -> str:
    if not records:
        return "index"
    keys = list(records[0])
    nums = set(numeric_columns(records))
    for key in keys:
        if key not in nums:
            return key
    return keys[0] if keys else "index"


def split_columns(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def infer_plot_spec(records: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
    kind = (request.get("kind") or request.get("chart") or "auto").lower()
    nums = numeric_columns(records)

    x = request.get("x") or ""
    y_cols = split_columns(request.get("y") or request.get("ys") or "")

    if not x:
        x = first_text_column(records) if len(records) <= 40 else "index"

    if not y_cols:
        y_cols = nums[:2] if nums else ["value"]

    if kind == "auto":
        if len(records) <= 12 and x != "index":
            kind = "bar"
        elif len(y_cols) == 1 and x in nums and y_cols[0] in nums:
            kind = "line"
        elif len(y_cols) >= 2 and all(c in nums for c in y_cols[:2]):
            kind = "scatter"
        else:
            kind = "line"

    return {
        "kind": kind,
        "x": x,
        "y": y_cols,
        "title": request.get("title") or "ELI Data Plot",
        "xlabel": request.get("xlabel") or ("" if x == "index" else x),
        "ylabel": request.get("ylabel") or ", ".join(y_cols),
        "width": int(request.get("width") or 1400),
        "height": int(request.get("height") or 900),
        "dpi": int(request.get("dpi") or 160),
        "theme": request.get("theme") or "dark",
        "palette": request.get("palette") or "auto",
    }


def column_values(records: list[dict[str, Any]], column: str) -> list[Any]:
    if column == "index":
        return list(range(len(records)))
    return [row.get(column) for row in records]


def numeric_values(values: Iterable[Any]) -> list[float]:
    result = []
    for v in values:
        if isinstance(v, (int, float)):
            result.append(float(v))
        elif v is None:
            result.append(float("nan"))
        else:
            try:
                result.append(float(v))
            except ValueError:
                result.append(float("nan"))
    return result


def apply_theme(fig: Any, ax: Any, palette: core.Palette, theme: str) -> None:
    if theme == "light":
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#ffffff")
        ax.tick_params(colors="#222222")
        ax.xaxis.label.set_color("#222222")
        ax.yaxis.label.set_color("#222222")
        ax.title.set_color("#111111")
        for spine in ax.spines.values():
            spine.set_color("#444444")
        ax.grid(True, alpha=0.18)
        return

    fig.patch.set_facecolor(tuple(c / 255 for c in palette.dark))
    ax.set_facecolor(tuple(c / 255 for c in core.darken(palette.dark, 0.05)))
    ax.tick_params(colors=tuple(c / 255 for c in palette.light))
    ax.xaxis.label.set_color(tuple(c / 255 for c in palette.light))
    ax.yaxis.label.set_color(tuple(c / 255 for c in palette.light))
    ax.title.set_color(tuple(c / 255 for c in palette.light))
    for spine in ax.spines.values():
        spine.set_color(tuple(c / 255 for c in palette.mid))
    ax.grid(True, alpha=0.18)


def generate_plot(
    request: dict[str, Any],
    output_path: str | Path,
    *,
    data_file: str | Path = "",
    data: Any = None,
) -> PlotOutput:
    plt = _require_matplotlib()
    records = load_records(data_file=data_file or request.get("data_file") or request.get("data") or "", data=data if data is not None else request.get("inline_data"))
    if not records:
        raise ValueError("No records were found for plotting.")

    spec = infer_plot_spec(records, request)
    palette = core.choose_palette(
        " ".join([str(spec.get("title", "")), str(request.get("prompt", "")), str(spec.get("theme", ""))]),
        int(request.get("seed") or 77),
        preferred=spec.get("palette", "auto"),
    )

    fig_w = max(3.0, spec["width"] / spec["dpi"])
    fig_h = max(2.0, spec["height"] / spec["dpi"])
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=spec["dpi"])
    apply_theme(fig, ax, palette, spec["theme"])

    x_values = column_values(records, spec["x"])
    y_cols = spec["y"]
    colors = [palette.accent, palette.light, palette.warm, palette.primary, palette.mid]
    mpl_colors = [tuple(c / 255 for c in color) for color in colors]

    kind = spec["kind"]
    if kind in {"line", "area"}:
        for idx, col in enumerate(y_cols):
            y = numeric_values(column_values(records, col))
            ax.plot(x_values, y, marker="o", linewidth=2.0, label=col, color=mpl_colors[idx % len(mpl_colors)])
            if kind == "area":
                ax.fill_between(x_values, y, alpha=0.18, color=mpl_colors[idx % len(mpl_colors)])

    elif kind == "bar":
        if len(y_cols) == 1:
            y = numeric_values(column_values(records, y_cols[0]))
            ax.bar(x_values, y, label=y_cols[0], color=mpl_colors[0])
        else:
            x_idx = np.arange(len(records))
            width = 0.78 / max(1, len(y_cols))
            for idx, col in enumerate(y_cols):
                y = numeric_values(column_values(records, col))
                ax.bar(x_idx + idx * width, y, width=width, label=col, color=mpl_colors[idx % len(mpl_colors)])
            ax.set_xticks(x_idx + width * (len(y_cols) - 1) / 2)
            ax.set_xticklabels([str(v) for v in x_values], rotation=30, ha="right")

    elif kind == "scatter":
        if len(y_cols) < 2:
            raise ValueError("Scatter plots need at least two numeric columns in --y, e.g. --y col_a,col_b")
        x = numeric_values(column_values(records, y_cols[0] if spec["x"] == "index" else spec["x"]))
        y = numeric_values(column_values(records, y_cols[1]))
        ax.scatter(x, y, s=64, alpha=0.82, color=mpl_colors[0], label=f"{spec['x']} vs {y_cols[1]}")

    elif kind in {"hist", "histogram"}:
        col = y_cols[0]
        y = [v for v in numeric_values(column_values(records, col)) if not np.isnan(v)]
        ax.hist(y, bins=int(request.get("bins") or 16), color=mpl_colors[0], alpha=0.88, label=col)

    elif kind == "pie":
        col = y_cols[0]
        values = numeric_values(column_values(records, col))
        labels = [str(v) for v in x_values]
        ax.pie(values, labels=labels, autopct="%1.1f%%", colors=mpl_colors * ((len(values) // len(mpl_colors)) + 1))
        ax.axis("equal")

    else:
        raise ValueError(f"Unsupported plot kind: {kind}")

    ax.set_title(spec["title"], pad=18, fontsize=16, fontweight="bold")
    if kind != "pie":
        ax.set_xlabel(spec["xlabel"])
        ax.set_ylabel(spec["ylabel"])
        if len(y_cols) > 1 or kind in {"line", "area", "hist", "histogram"}:
            legend = ax.legend(framealpha=0.18)
            if legend:
                for text in legend.get_texts():
                    text.set_color(tuple(c / 255 for c in palette.light) if spec["theme"] != "light" else "#222222")

    fig.autofmt_xdate()
    fig.tight_layout()

    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    summary = {
        "rows": len(records),
        "columns": sorted({k for row in records for k in row}),
        "numeric_columns": numeric_columns(records),
    }
    return PlotOutput(path=str(out), spec=spec, summary=summary)
