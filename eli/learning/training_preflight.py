from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from eli.learning.base_model_resolver import BASE_UNRESOLVED, resolve_base_model_path
from eli.learning import lora_trainer_guard as guard


try:
    from eli.core.paths import canonical_root
    PROJECT_ROOT = canonical_root(Path(__file__).resolve().parents[2])
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_MODULES = [
    "torch",
    "transformers",
    "peft",
    "accelerate",
    "datasets",
]


def module_available(name: str) -> bool:
    """
    Robust module availability probe.

    importlib.util.find_spec() can raise ValueError when a test/runtime stub
    exists in sys.modules but has no __spec__.
    """
    mod = sys.modules.get(name)
    if mod is not None:
        spec = getattr(mod, "__spec__", None)
        if spec is None:
            return True

    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


def module_report() -> dict[str, dict[str, bool]]:
    return {name: {"available": module_available(name)} for name in REQUIRED_MODULES}


def _guard_plan_for_target(target: str) -> dict[str, Any]:
    if hasattr(guard, "build_training_plan"):
        return guard.build_training_plan(target)

    if hasattr(guard, "_build_training_plan"):
        return guard._build_training_plan(target)

    raise RuntimeError("No compatible LoRA guard plan builder found.")


def preflight_target(
    target: str,
    base_model_path=None,
    *,
    allow_default_candidates: bool = True,
) -> dict[str, Any]:
    modules = module_report()
    missing_modules = [k for k, v in modules.items() if not v["available"]]

    guard_plan = _guard_plan_for_target(target)
    requested_base = (
        base_model_path
        or guard_plan.get("config", {}).get("base_model_path")
        or guard_plan.get("adapter_config", {}).get("base_model_name_or_path")
    )

    base = resolve_base_model_path(
        requested_base,
        allow_default_candidates=allow_default_candidates,
    )

    problems: list[str] = []

    if not base.get("ok"):
        problems.append(BASE_UNRESOLVED)

    if missing_modules:
        problems.append("missing training modules: " + ", ".join(missing_modules))

    # Scrub weak old guard warnings from nested report.
    if isinstance(guard_plan, dict):
        guard_plan["warnings"] = [
            w for w in list(guard_plan.get("warnings") or [])
            if not str(w).startswith("base model path missing:")
        ]

    return {
        "ok": True,
        "target": target,
        "can_train": not problems,
        "problems": problems,
        "modules": modules,
        "missing_modules": missing_modules,
        "base_model_resolution": base,
        "guard_plan": guard_plan,
    }


def preflight_all() -> dict[str, Any]:
    """Preflight for every declared target: the built-ins and the operator's own."""
    return {
        "ok": True,
        "reports": [preflight_target(t) for t in sorted(guard.allowed_targets())],
    }


def targets_to_train(request: str = "") -> list[str]:
    """The declared targets a request to train is for: the ones it names, in the order named (the
    autonomy scheduler names the one preflight found ready), else the first one that is ready now,
    else none. The scheduled LoRA job and chat's LORA_TRAIN both choose by this; chat used to take
    eli_phi whatever was declared or ready."""
    import re
    low = (request or "").lower()
    named = []
    for target in guard.allowed_targets():
        hit = re.search(r"(?<![\w-])" + re.escape(target.lower()) + r"(?![\w-])", low)
        if hit:
            named.append((hit.start(), target))
    if named:
        return [target for _, target in sorted(named)]
    ready = [r.get("target") for r in (preflight_all().get("reports") or []) if r.get("can_train")]
    return [str(ready[0])] if ready else []


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="all")
    args = ap.parse_args(argv)

    if args.target == "all":
        payload = preflight_all()
    else:
        payload = preflight_target(args.target)

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
