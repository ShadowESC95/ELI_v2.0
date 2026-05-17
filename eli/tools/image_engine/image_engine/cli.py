from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contracts import EngineConfig, JobRequest
from .service import ImageEngine
from . import visual_core as core


def _json_print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _load_json_arg(value: str) -> Any:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def add_common_engine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=str, default="", help="Optional image engine config JSON.")
    parser.add_argument("--memory-db", type=str, default="", help="Override SQLite visual memory path.")
    parser.add_argument("--out", type=str, default="", help="Override jobs output folder.")
    parser.add_argument("--logs", type=str, default="", help="Override logs folder.")
    parser.add_argument("--no-memory", action="store_true", help="Disable SQLite indexing for this run.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image_engine",
        description="ELI-native image, plot, visual-memory, and project-profile engine.",
    )
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Generate images.")
    add_common_engine_args(gen)
    gen.add_argument("--query", "--prompt", dest="query", type=str, default="", help="Text prompt.")
    gen.add_argument("--query-file", type=str, default="", help="Text file containing a prompt.")
    gen.add_argument("--project", type=str, default="", help="Project/reference folder.")
    gen.add_argument("--preset", type=str, default="", help="Preset JSON file or preset name from presets/.")
    gen.add_argument("--type", dest="scene_type", type=str, default="auto", choices=["auto", "landscape", "poster", "abstract", "emblem", "product", "cityscape", "space"])
    gen.add_argument("--style", type=str, default="auto", choices=["auto", "balanced", "cinematic", "minimal", "luxury", "neon", "fantasy"])
    gen.add_argument("--palette", type=str, default="auto")
    gen.add_argument("--backend", type=str, default="procedural", choices=["procedural", "diffusion", "auto"])
    gen.add_argument("--model", type=str, default="")
    gen.add_argument("--device", type=str, default="auto")
    gen.add_argument("--steps", type=int, default=36)
    gen.add_argument("--guidance", type=float, default=7.2)
    gen.add_argument("--negative", type=str, default="")
    gen.add_argument("--title", type=str, default="")
    gen.add_argument("--count", type=int, default=1)
    gen.add_argument("--seed", type=int, default=77)
    gen.add_argument("--width", type=int, default=1400)
    gen.add_argument("--height", type=int, default=900)
    gen.add_argument("--supersample", type=int, default=1)
    gen.add_argument("--prefix", type=str, default="image_engine")
    gen.add_argument("--format", type=str, default="png", choices=["png", "jpg", "jpeg", "webp"])
    gen.add_argument("--sheet", action="store_true")
    gen.add_argument("--save-specs", action="store_true", help="Accepted for compatibility; per-artifact specs are always saved.")
    gen.add_argument("--manifest", action="store_true", help="Accepted for compatibility; job manifest is always saved.")
    gen.add_argument("--name-from-prompt", action="store_true")
    gen.add_argument("--verbose", action="store_true")

    plot = sub.add_parser("plot", help="Generate a plot/chart/graph from CSV, JSON, JSONL, or inline JSON.")
    add_common_engine_args(plot)
    plot.add_argument("--data", type=str, default="", help="CSV/JSON/JSONL file path.")
    plot.add_argument("--json", type=str, default="", help="Inline JSON data or path to JSON file.")
    plot.add_argument("--project", type=str, default="")
    plot.add_argument("--query", "--prompt", dest="query", type=str, default="", help="Optional plot intent/prompt.")
    plot.add_argument("--kind", "--chart", dest="kind", type=str, default="auto", choices=["auto", "line", "bar", "scatter", "area", "hist", "histogram", "pie"])
    plot.add_argument("--x", type=str, default="", help="X column. Use 'index' for row index.")
    plot.add_argument("--y", type=str, default="", help="Y column(s), comma-separated.")
    plot.add_argument("--title", type=str, default="ELI Data Plot")
    plot.add_argument("--xlabel", type=str, default="")
    plot.add_argument("--ylabel", type=str, default="")
    plot.add_argument("--bins", type=int, default=16)
    plot.add_argument("--theme", type=str, default="dark", choices=["dark", "light"])
    plot.add_argument("--palette", type=str, default="auto")
    plot.add_argument("--seed", type=int, default=77)
    plot.add_argument("--width", type=int, default=1400)
    plot.add_argument("--height", type=int, default=900)
    plot.add_argument("--dpi", type=int, default=160)
    plot.add_argument("--format", type=str, default="png", choices=["png", "jpg", "jpeg", "webp"])
    plot.add_argument("--verbose", action="store_true")

    profile = sub.add_parser("profile", help="Create a project visual profile JSON.")
    add_common_engine_args(profile)
    profile.add_argument("--project", type=str, required=True)
    profile.add_argument("--query", type=str, default="")

    find = sub.add_parser("find", help="Search visual memory.")
    add_common_engine_args(find)
    find.add_argument("query", nargs="?", default="")
    find.add_argument("--type", dest="artifact_type", type=str, default="", choices=["", "image", "plot", "contact_sheet", "profile", "manifest"])
    find.add_argument("--project", type=str, default="")
    find.add_argument("--limit", type=int, default=25)

    jobs = sub.add_parser("jobs", help="List recent jobs from visual memory.")
    add_common_engine_args(jobs)
    jobs.add_argument("--limit", type=int, default=25)

    run = sub.add_parser("run", help="Run a raw JSON job request.")
    add_common_engine_args(run)
    run.add_argument("request", help="JSON string or path to JSON request.")

    return parser


def engine_from_args(args: argparse.Namespace) -> ImageEngine:
    if getattr(args, "config", ""):
        config = EngineConfig.from_file(args.config)
    else:
        config = EngineConfig()
    if getattr(args, "memory_db", ""):
        config.memory_db = args.memory_db
    if getattr(args, "out", ""):
        config.jobs_dir = args.out
    if getattr(args, "logs", ""):
        config.log_dir = args.logs
        if not getattr(args, "memory_db", ""):
            config.memory_db = str(Path(args.logs) / "image_index.sqlite")
    if getattr(args, "no_memory", False):
        config.save_memory = False
    return ImageEngine(config)


def _read_query(query: str, query_file: str = "") -> str:
    text = query or ""
    if query_file:
        path = Path(query_file).expanduser()
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore")
    return text.strip()



def _apply_generate_preset(args: argparse.Namespace) -> argparse.Namespace:
    if not getattr(args, "preset", ""):
        return args
    preset = core.load_preset(args.preset)
    default_values = {
        "query": "",
        "project": "",
        "scene_type": "auto",
        "style": "auto",
        "palette": "auto",
        "backend": "procedural",
        "model": "",
        "device": "auto",
        "steps": 36,
        "guidance": 7.2,
        "negative": "",
        "title": "",
        "count": 1,
        "seed": 77,
        "width": 1400,
        "height": 900,
        "supersample": 1,
        "prefix": "image_engine",
        "format": "png",
        "sheet": False,
        "name_from_prompt": False,
    }
    key_map = {"type": "scene_type", "name-from-prompt": "name_from_prompt", "name_from_prompt": "name_from_prompt"}
    for key, value in preset.items():
        attr = key_map.get(key, key)
        if not hasattr(args, attr):
            continue
        if getattr(args, attr) == default_values.get(attr):
            setattr(args, attr, value)
    return args

def command_generate(args: argparse.Namespace) -> int:
    args = _apply_generate_preset(args)
    engine = engine_from_args(args)
    request = {
        "task": "generate_image",
        "prompt": _read_query(args.query, args.query_file),
        "project": args.project,
        "intent": args.scene_type,
        "count": args.count,
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "style": args.style,
        "palette": args.palette,
        "backend": args.backend,
        "output_format": args.format,
        "title": args.title,
        "negative_prompt": args.negative,
        "options": {
            "preset": args.preset,
            "query_file": args.query_file,
            "model": args.model,
            "device": args.device,
            "steps": args.steps,
            "guidance": args.guidance,
            "supersample": args.supersample,
            "prefix": args.prefix,
            "sheet": args.sheet,
            "name_from_prompt": args.name_from_prompt,
            "verbose": args.verbose,
        },
    }
    result = engine.run(request)
    _json_print(result)
    return 0 if result.get("status") == "complete" else 1


def command_plot(args: argparse.Namespace) -> int:
    engine = engine_from_args(args)
    inline = _load_json_arg(args.json) if args.json else None
    request = {
        "task": "generate_plot",
        "prompt": args.query,
        "project": args.project,
        "count": 1,
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "palette": args.palette,
        "output_format": args.format,
        "title": args.title,
        "data": inline,
        "options": {
            "data_file": args.data,
            "kind": args.kind,
            "x": args.x,
            "y": args.y,
            "xlabel": args.xlabel,
            "ylabel": args.ylabel,
            "bins": args.bins,
            "theme": args.theme,
            "dpi": args.dpi,
            "verbose": args.verbose,
        },
    }
    result = engine.run(request)
    _json_print(result)
    return 0 if result.get("status") == "complete" else 1


def command_profile(args: argparse.Namespace) -> int:
    engine = engine_from_args(args)
    result = engine.run({"task": "project_profile", "project": args.project, "prompt": args.query})
    _json_print(result)
    return 0 if result.get("status") == "complete" else 1


def command_find(args: argparse.Namespace) -> int:
    engine = engine_from_args(args)
    _json_print(engine.search(args.query, artifact_type=args.artifact_type, project=args.project, limit=args.limit))
    return 0


def command_jobs(args: argparse.Namespace) -> int:
    engine = engine_from_args(args)
    _json_print(engine.jobs(limit=args.limit))
    return 0


def command_run(args: argparse.Namespace) -> int:
    engine = engine_from_args(args)
    request = _load_json_arg(args.request)
    result = engine.run(request)
    _json_print(result)
    return 0 if result.get("status") == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Compatibility mode: old style `python -m image_engine --query "..."`
    # becomes `python -m image_engine generate --query "..."`.
    if not argv or argv[0].startswith("-"):
        argv = ["generate", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            return command_generate(args)
        if args.command == "plot":
            return command_plot(args)
        if args.command == "profile":
            return command_profile(args)
        if args.command == "find":
            return command_find(args)
        if args.command == "jobs":
            return command_jobs(args)
        if args.command == "run":
            return command_run(args)
        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
