from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from eli.learning.dataset_filters import is_bad_response, load_jsonl, row_is_reviewed
from eli.utils.log import get_logger
from eli.learning.base_model_resolver import resolve_base_model_path


def _eli_canonical_root_PROJECT_ROOT() -> Path:
    # Canonical env-honoring root — __file__ resolves into the read-only
    # bundle in frozen builds (identical to this path in source installs).
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _eli_canonical_root_PROJECT_ROOT()

log = get_logger(__name__)
REGISTRY_PATH = PROJECT_ROOT / "models/lora/registry/eli_phi_targets.json"
def _runs_dir() -> Path:
    try:
        from eli.core.paths import learning_dir
        return Path(learning_dir()) / "runs"
    except Exception:
        return PROJECT_ROOT / "training" / "runs"


RUNS_DIR = _runs_dir()

# Built-ins. `allowed_targets()` is the live allowlist — built-ins PLUS whatever the
# operator declared in the registry. The contract is unchanged (nothing trains unless
# it was explicitly declared); what changed is that declaring is no longer a source edit.
ALLOWED_TARGETS = {"eli_phi", "eli_phi_ultra"}


def allowed_targets() -> set[str]:
    try:
        from eli.learning.target_registry import allowed_target_names
        return allowed_target_names() | set(ALLOWED_TARGETS)
    except Exception:
        return set(ALLOWED_TARGETS)

DEFAULTS = {
    "eli_phi": {
        "base_family": "phi3",
        "base_model_path": "./phi-3-mini-base",
        "adapter_path": "models/lora/adapters/eli-lora-adapter-phi3",
        "dataset_path": "training/datasets/eli_supervised_v0.eli_phi.trainable.jsonl",
        "output_dir": "models/lora/adapters/eli-lora-adapter-phi3-next",
    },
    "eli_phi_ultra": {
        "base_family": "phi3",
        "base_model_path": "./phi-3-mini-base",
        "adapter_path": "models/lora/adapters/eli-lora-adapter-phi3-ultra",
        "dataset_path": "training/datasets/eli_supervised_v0.eli_phi_ultra.trainable.jsonl",
        "output_dir": "models/lora/adapters/eli-lora-adapter-phi3-ultra-next",
    },
}

FORBIDDEN_TARGET_TERMS = {
    "openhermes",
    "mistral",
    "qwen",
    "tinyllama",
    "generic_gguf",
    "gguf",
}


@dataclass
class TrainerTarget:
    target: str
    base_family: str
    base_model_path: str
    adapter_path: str
    dataset_path: str
    output_dir: str


def _project_path(value: str | Path, *, project_root: Path = PROJECT_ROOT) -> Path:
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return (project_root / p).resolve()


def _load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _target_from_registry(data: dict[str, Any], target: str) -> dict[str, Any]:
    targets = data.get("targets")

    if isinstance(targets, dict):
        item = targets.get(target)
        return item if isinstance(item, dict) else {}

    if isinstance(targets, list):
        for item in targets:
            if isinstance(item, dict) and str(item.get("id") or item.get("target")) == target:
                return item
        return {}

    item = data.get(target)
    return item if isinstance(item, dict) else {}


def resolve_target(
    target: str,
    *,
    registry_path: Path = REGISTRY_PATH,
    project_root: Path = PROJECT_ROOT,
    dataset_path: str | Path | None = None,
) -> TrainerTarget:
    target = str(target or "").strip()

    known = allowed_targets()
    if target not in known:
        raise ValueError(
            f"Refusing target={target!r}. Allowed targets: {sorted(known)}"
        )

    cfg = dict(DEFAULTS.get(target) or {})
    try:
        from eli.learning.target_registry import get_target
        cfg.update(get_target(target) or {})
    except Exception:
        log.debug("[lora] target registry unavailable; built-in defaults only",
                  exc_info=True)
    reg = _load_registry(registry_path)
    cfg.update(_target_from_registry(reg, target))

    if dataset_path:
        cfg["dataset_path"] = str(dataset_path)

    # Accept several likely registry key names without forcing one schema.
    base_model_path = (
        cfg.get("base_model_path")
        or cfg.get("base_model")
        or cfg.get("base")
        or DEFAULTS.get(target, {}).get("base_model_path", "")
    )
    adapter_path = (
        cfg.get("adapter_path")
        or cfg.get("adapter")
        or DEFAULTS.get(target, {}).get("adapter_path", "")
    )
    trainable_dataset = (
        cfg.get("dataset_path")
        or cfg.get("trainable_dataset")
        or cfg.get("dataset")
        or DEFAULTS.get(target, {}).get("dataset_path", "")
    )
    output_dir = (
        cfg.get("output_dir")
        or cfg.get("output_adapter")
        or DEFAULTS.get(target, {}).get("output_dir", "")
    )

    return TrainerTarget(
        target=target,
        base_family=str(cfg.get("base_family") or ""),
        base_model_path=str(base_model_path),
        adapter_path=str(adapter_path),
        dataset_path=str(trainable_dataset),
        output_dir=str(output_dir),
    )


def _read_adapter_config(adapter_dir: Path) -> dict[str, Any]:
    cfg = adapter_dir / "adapter_config.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _row_targets(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()

    target = row.get("target")
    if target:
        out.add(str(target))

    targets = row.get("targets")
    if isinstance(targets, list):
        out.update(str(x) for x in targets if str(x).strip())

    return _eli_attach_base_resolution_any(out)


def _validate_dataset_rows(rows: list[dict[str, Any]], target: str) -> tuple[list[str], dict[str, int]]:
    problems: list[str] = []
    # A row tagged for a *declared* target is legitimate however it is named — the
    # leak this catches is a row aimed at some generic/inference artifact that was
    # never declared for training (a raw GGUF above all).
    try:
        _declared = allowed_targets()
    except Exception:
        _declared = set(ALLOWED_TARGETS)
    counts = {
        "rows": len(rows),
        "reviewed_rows": 0,
        "targeted_rows": 0,
        "bad_response_rows": 0,
        "needs_review_rows": 0,
        "wrong_target_rows": 0,
        "generic_target_leak_rows": 0,
    }

    for i, row in enumerate(rows, start=1):
        tags = [str(x) for x in row.get("tags") or []]
        targets = _row_targets(row)

        if row_is_reviewed(row):
            counts["reviewed_rows"] += 1
        else:
            problems.append(f"row {i}: not reviewed/approved")

        if "needs_review" in tags:
            counts["needs_review_rows"] += 1
            problems.append(f"row {i}: contains needs_review tag")

        if target in targets or row.get("target") == target:
            counts["targeted_rows"] += 1
        else:
            counts["wrong_target_rows"] += 1
            problems.append(f"row {i}: missing required target={target}")

        leaked = [t for t in targets
                  if t.lower() in FORBIDDEN_TARGET_TERMS and t != target and t not in _declared]
        if leaked:
            counts["generic_target_leak_rows"] += 1
            problems.append(f"row {i}: undeclared target marker {sorted(leaked)}")

        if is_bad_response(row.get("response", "")):
            counts["bad_response_rows"] += 1
            problems.append(f"row {i}: bad response surface")

    return problems, counts


def build_training_plan(
    target: str,
    *,
    registry_path: Path = REGISTRY_PATH,
    project_root: Path = PROJECT_ROOT,
    dataset_path: str | Path | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    cfg = resolve_target(
        target,
        registry_path=registry_path,
        project_root=project_root,
        dataset_path=dataset_path,
    )

    base_path = _project_path(cfg.base_model_path, project_root=project_root)
    adapter_path = _project_path(cfg.adapter_path, project_root=project_root)
    dataset_file = _project_path(cfg.dataset_path, project_root=project_root)
    output_dir = _project_path(cfg.output_dir, project_root=project_root)

    problems: list[str] = []
    warnings: list[str] = []

    # Family is validated against what the base model declares for itself
    # (config.json model_type) instead of being hardcoded to one family. A target
    # that says "qwen3" over a Llama checkpoint is still refused — the check moved
    # from "is it Phi" to "is it what you said it was".
    actual_family = None
    try:
        from eli.learning.target_registry import detect_family, family_matches
        actual_family = detect_family(base_path)
        if not family_matches(cfg.base_family, actual_family):
            problems.append(
                f"base_family mismatch: target declares {cfg.base_family!r} but "
                f"{base_path} declares {actual_family!r}")
    except Exception as _fam_err:
        warnings.append(f"could not read base model family: {_fam_err}")

    if not base_path.exists():
        warnings.append(f"base model path missing: {base_path}")

    # A target that has never trained has no adapter yet — that is the normal first
    # run, not a fault. Only a *malformed* adapter is a problem (checked below).
    first_run = not adapter_path.exists()
    if first_run:
        warnings.append(f"no existing adapter at {adapter_path} (first run for this target)")

    if not dataset_file.exists():
        problems.append(f"dataset missing: {dataset_file}")

    adapter_config = _read_adapter_config(adapter_path)
    if adapter_config:
        if adapter_config.get("peft_type") != "LORA":
            problems.append("adapter_config peft_type is not LORA")
        if adapter_config.get("task_type") != "CAUSAL_LM":
            problems.append("adapter_config task_type is not CAUSAL_LM")

        declared_base = str(adapter_config.get("base_model_name_or_path") or "")
        if declared_base and cfg.base_family:
            # The existing adapter must belong to the same family we are about to
            # continue training, whatever that family is.
            from eli.learning.target_registry import detect_family as _df, family_matches as _fm
            adapter_family = _df(declared_base) or ""
            token_match = cfg.base_family.lower() in declared_base.lower()
            if not (token_match or _fm(cfg.base_family, adapter_family)):
                problems.append(
                    f"adapter declares a base model outside the {cfg.base_family!r} "
                    f"family: {declared_base}")
    elif adapter_path.exists():
        problems.append(f"adapter_config.json missing under {adapter_path}")

    rows: list[dict[str, Any]] = []
    row_counts = {
        "rows": 0,
        "reviewed_rows": 0,
        "targeted_rows": 0,
        "bad_response_rows": 0,
        "needs_review_rows": 0,
        "wrong_target_rows": 0,
        "generic_target_leak_rows": 0,
    }

    if dataset_file.exists():
        rows = load_jsonl(dataset_file)
        row_problems, row_counts = _validate_dataset_rows(rows, cfg.target)
        problems.extend(row_problems)

    train_ready = not problems and base_path.exists() and dataset_file.exists()

    plan = {
        "ok": True,
        "dry_run": not execute,
        "will_train": bool(execute and train_ready),
        "train_ready": bool(train_ready),
        "target": cfg.target,
        "first_run": bool(first_run),
        "base_family_declared": cfg.base_family,
        "base_family_actual": actual_family,
        "allowed_targets": sorted(allowed_targets()),
        "config": asdict(cfg),
        "resolved_paths": {
            "base_model_path": str(base_path),
            "adapter_path": str(adapter_path),
            "dataset_path": str(dataset_file),
            "output_dir": str(output_dir),
        },
        "adapter_config": {
            "peft_type": adapter_config.get("peft_type"),
            "task_type": adapter_config.get("task_type"),
            "base_model_name_or_path": adapter_config.get("base_model_name_or_path"),
            "r": adapter_config.get("r"),
            "lora_alpha": adapter_config.get("lora_alpha"),
            "target_modules": adapter_config.get("target_modules"),
            "inference_mode": adapter_config.get("inference_mode"),
        },
        "dataset": row_counts,
        "problems": problems,
        "warnings": warnings,
        "safety_contract": [
            "Default mode is dry-run only.",
            "Only targets the operator has explicitly declared are allowed.",
            "GGUF files are inference artifacts and are never trained directly.",
            "Rows must be reviewed/approved and explicitly scoped to the selected target.",
            "Real training requires a local trainable Hugging Face base model directory.",
            "The base model must belong to the family the target declares.",
        ],
    }

    if execute and not train_ready:
        plan["ok"] = False
        plan["error"] = "Refusing execution because train_ready=false."

    if execute and train_ready:
        plan["ok"] = False
        plan["error"] = "Execution path intentionally not implemented in guard phase."

    return plan


def write_plan(plan: dict[str, Any], *, out: Path | None = None) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if out is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = RUNS_DIR / f"lora_guard_{plan['target']}_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_eli_json_dumps_hardened(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return _eli_attach_base_resolution_any(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ELI Phi-targeted LoRA trainer guard.")
    ap.add_argument("--target", default="all", help="eli_phi, eli_phi_ultra, or all")
    ap.add_argument("--dataset", default="", help="Optional dataset override for single-target mode")
    ap.add_argument("--registry", "--registry-path", dest="registry_path", default="", help="Optional target registry override")
    ap.add_argument("--project-root", default="", help="Optional project root for resolving relative registry paths")
    ap.add_argument("--execute", action="store_true", help="Attempt real training. Currently refused unless future trainer is implemented.")
    ap.add_argument("--out", default="", help="Optional plan output path for single-target mode")
    args = ap.parse_args(argv)

    targets = sorted(ALLOWED_TARGETS) if args.target == "all" else [args.target]
    reports = []

    for target in targets:
        registry_path = Path(args.registry_path).expanduser() if args.registry_path else None
        project_root = Path(args.project_root).expanduser() if args.project_root else None
        plan = build_training_plan(
            target,
            registry_path=registry_path,
            project_root=project_root,
            dataset_path=args.dataset or None,
            execute=bool(args.execute),
        )
        out = Path(args.out).expanduser() if args.out and len(targets) == 1 else None
        plan_path = write_plan(plan, out=out)
        plan["plan_path"] = str(plan_path)
        reports.append(plan)

    ok = all(r.get("ok") for r in reports)
    print(_eli_json_dumps_hardened({"ok": ok, "reports": reports}, indent=2, ensure_ascii=False))
    return 0 if ok else 2



# ELI_BASE_RESOLVER_GUARD_V2
# Strict trainable-base resolution. This must appear BEFORE the CLI entrypoint.
# It recursively hardens target reports so CLI and imported test paths agree.

def _eli_attach_base_resolution(report):
    if not isinstance(report, dict):
        return report

    cfg = report.get("config") or {}
    target = str(report.get("target") or cfg.get("target") or "").strip()

    if target not in {"eli_phi", "eli_phi_ultra"}:
        return report

    requested = cfg.get("base_model_path") or report.get("base_model_path") or ""
    resolution = resolve_base_model_path(requested or None)

    report["base_model_resolution"] = resolution

    warnings = list(report.get("warnings") or [])
    problems = list(report.get("problems") or [])

    warnings = [
        w for w in warnings
        if not str(w).startswith("base model path missing:")
    ]

    if not resolution.get("ok"):
        msg = "trainable Phi-3 base model unresolved"
        if msg not in problems:
            problems.append(msg)

    report["warnings"] = warnings
    report["problems"] = problems

    dataset_rows = int((report.get("dataset") or {}).get("rows") or 0)
    report["train_ready"] = bool(dataset_rows > 0 and not problems and resolution.get("ok"))

    if report.get("dry_run", True):
        report["will_train"] = False

    return report


def _eli_attach_base_resolution_any(obj):
    if isinstance(obj, list):
        return [_eli_attach_base_resolution_any(x) for x in obj]

    if isinstance(obj, dict):
        if "reports" in obj and isinstance(obj["reports"], list):
            obj["reports"] = [_eli_attach_base_resolution_any(x) for x in obj["reports"]]

        if "config" in obj and ("target" in obj or "target" in (obj.get("config") or {})):
            obj = _eli_attach_base_resolution(obj)

    return obj



# ELI_BASE_RESOLVER_GUARD_V4
# Local JSON serializer hardener for LoRA guard reports.
# This is intentionally local to this module; it does not monkeypatch stdlib json.
_ELI_ORIG_JSON_DUMPS = json.dumps


def _eli_harden_lora_guard_report(report):
    if not isinstance(report, dict):
        return report

    cfg = report.get("config") or {}
    target = str(report.get("target") or cfg.get("target") or "").strip()

    if target not in {"eli_phi", "eli_phi_ultra"}:
        return report

    requested = cfg.get("base_model_path") or report.get("base_model_path") or ""
    resolution = resolve_base_model_path(requested or None)

    report["base_model_resolution"] = resolution

    problems = list(report.get("problems") or [])
    warnings = list(report.get("warnings") or [])

    warnings = [
        w for w in warnings
        if not str(w).startswith("base model path missing:")
    ]

    if not resolution.get("ok"):
        msg = "trainable Phi-3 base model unresolved"
        if msg not in problems:
            problems.append(msg)

    report["problems"] = problems
    report["warnings"] = warnings

    dataset_rows = int((report.get("dataset") or {}).get("rows") or 0)
    report["train_ready"] = bool(dataset_rows > 0 and not problems and resolution.get("ok"))

    if report.get("dry_run", True):
        report["will_train"] = False

    return report


def _eli_harden_lora_guard_payload(obj):
    if isinstance(obj, list):
        return [_eli_harden_lora_guard_payload(x) for x in obj]

    if isinstance(obj, dict):
        if isinstance(obj.get("reports"), list):
            obj["reports"] = [_eli_harden_lora_guard_payload(x) for x in obj["reports"]]

        cfg = obj.get("config") if isinstance(obj.get("config"), dict) else {}
        if "target" in obj or "target" in cfg:
            obj = _eli_harden_lora_guard_report(obj)

    return obj


def _eli_json_dumps_hardened(obj, *args, **kwargs):
    return _ELI_ORIG_JSON_DUMPS(_eli_harden_lora_guard_payload(obj), *args, **kwargs)



# ELI_BUILD_PLAN_BASE_RESOLUTION_V5
# Harden the actual plan object, not just CLI JSON rendering.
# This prevents stale ./phi-3-mini-base from surviving after a valid HF base
# has been downloaded under models/hf/Phi-3-mini-4k-instruct.
try:
    _ELI_ORIGINAL_BUILD_TRAINING_PLAN_V5
except NameError:
    _ELI_ORIGINAL_BUILD_TRAINING_PLAN_V5 = build_training_plan


def _eli_normalize_plan_base_model_v5(report):
    if not isinstance(report, dict):
        return report

    cfg = report.setdefault("config", {})
    resolved_paths = report.setdefault("resolved_paths", {})
    adapter_cfg = report.get("adapter_config")
    if not isinstance(adapter_cfg, dict):
        adapter_cfg = {}

    requested = (
        cfg.get("base_model_path")
        or adapter_cfg.get("base_model_name_or_path")
        or resolved_paths.get("base_model_path")
    )

    base = resolve_base_model_path(requested, allow_default_candidates=True)
    report["base_model_resolution"] = base

    problems = list(report.get("problems") or [])
    warnings = [
        w for w in list(report.get("warnings") or [])
        if not str(w).startswith("base model path missing:")
    ]

    if base.get("ok"):
        rel = base.get("relative") or base.get("path")
        abs_path = base.get("path")

        cfg["base_model_path"] = rel
        resolved_paths["base_model_path"] = abs_path

        if isinstance(report.get("adapter_config"), dict):
            report["adapter_config"]["base_model_name_or_path"] = rel

        problems = [
            p for p in problems
            if p != "trainable Phi-3 base model unresolved"
        ]

        report["train_ready"] = bool(report.get("ok", True)) and not problems
        if report.get("dry_run", True):
            report["will_train"] = False
    else:
        if "trainable Phi-3 base model unresolved" not in problems:
            problems.append("trainable Phi-3 base model unresolved")
        report["train_ready"] = False
        report["will_train"] = False

    report["problems"] = problems
    report["warnings"] = warnings
    return report


def build_training_plan(*args, **kwargs):
    return _eli_normalize_plan_base_model_v5(
        _ELI_ORIGINAL_BUILD_TRAINING_PLAN_V5(*args, **kwargs)
    )


if __name__ == "__main__":
    raise SystemExit(main())

