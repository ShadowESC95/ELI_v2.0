from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _project_root() -> Path:
    try:
        from eli.core.paths import canonical_root
        return canonical_root(Path(__file__).resolve().parents[2])
    except Exception:
        return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return {}


_LOAD_LABELS = {"n_ctx": "context (n_ctx)", "n_gpu_layers": "GPU layers",
                "n_batch": "batch"}


def system_memory_line() -> str:
    """Total/available RAM and CPU threads, from the same probe the loader uses."""
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        if not getattr(hw, "ram_gb", 0):
            return ""
        return (f"ram_total_gb: {hw.ram_gb:.1f}, ram_available_gb: "
                f"{hw.available_ram_gb:.1f}, cpu_threads_total: {hw.cpu_threads}")
    except Exception:
        return ""


def runtime_load_facts(snapshot: Dict[str, Any] | None,
                       settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """The requested-vs-loaded comparison, computed once, for every runtime surface.

    Live report (2.4.57): the operator asked ELI why its ctx/batch/GPU-layer
    numbers looked inconsistent -- the log showed layers requested 7 / loaded 6,
    and three different ctx figures (the tuner's 12288 and 10240, the operator's
    12200). ELI answered "my current runtime configuration is consistent and not
    conflicting". Every fact it was handed was true, but the evidence only listed
    what LOADED plus a `clamped` flag that no real snapshot writer ever sets
    (always null), so nothing in it said the loader had been asked for more than
    it delivered. A model asked "is this consistent?" of evidence that lacks the
    comparison will say yes.

    So the comparison is derived here, deterministically, from the snapshot's own
    requested/effective blocks (via the same `runtime_load_gap` GPU_STATUS uses --
    one rule, not a second opinion), and `consistent` is only True when there is
    genuinely nothing to report. The tuner's stored recommendation is surfaced
    too, labelled as what it is: a suggestion kept as a fallback, which by design
    is NOT what loads when the operator's own values fit.
    """
    snapshot = dict(snapshot or {})
    settings = dict(settings or {})
    try:
        from eli.cognition.context_synthesiser import runtime_load_gap
        gap = runtime_load_gap(dict(snapshot)) if snapshot else {}
    except Exception:
        gap = {}
    reduced = dict(gap.get("reduced") or {})
    eff = dict(gap.get("effective") or {})

    differences: list[str] = []
    for key, label in _LOAD_LABELS.items():
        pair = reduced.get(key)
        if pair:
            differences.append(
                f"{label}: requested {pair['requested']}, loaded {pair['effective']} — "
                f"reduced to fit this machine's free memory")

    # A saved value differing from what loaded, when the requested block did not explain it.
    cfg_keys = {"n_ctx": "n_ctx", "n_gpu_layers": "n_gpu_layers", "n_batch": "batch_size"}
    for key, cfg_key in cfg_keys.items():
        if key in reduced:
            continue
        try:
            configured = int(settings.get(cfg_key) or 0)
            loaded = int(eff.get(key) or 0)
        except Exception:
            continue
        if configured > 0 and loaded > 0 and configured != loaded:
            differences.append(
                f"{_LOAD_LABELS[key]}: saved setting {configured}, loaded {loaded}")

    tuner: Dict[str, Any] = {}
    for key, cfg_key in (("n_ctx", "hw_profile_n_ctx"),
                         ("n_gpu_layers", "hw_profile_n_gpu_layers"),
                         ("n_batch", "hw_profile_batch_size")):
        value = settings.get(cfg_key)
        if value not in (None, "", 0):
            tuner[key] = value

    return {
        "clamped": bool(reduced),
        "reduced": reduced,
        "differences": differences,
        "consistent": not differences,
        "tuner_recommendation": tuner,
        "tuner_note": (
            "The tuner's numbers are a stored suggestion (fallback), not what loaded: "
            "the operator's own values are used when they fit, and the loader "
            "reduces only what does not."
        ) if tuner else "",
        "max_tokens_note": (
            "settings max_tokens is a ceiling derived from the loaded ctx, not a "
            "per-call limit: each generation fits its own budget from the prompt "
            "size and reasoning mode."
        ),
    }


def _git_info(root: Path) -> Dict[str, Any]:
    def run(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, cwd=str(root), text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        except Exception:
            return ""

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "commit": run(["git", "rev-parse", "--short", "HEAD"]),
        "dirty_files": run(["git", "status", "--short"]).splitlines(),
    }


def _gpu_hardware_fallback() -> Dict[str, Any]:
    # Cross-vendor: ELI ships to AMD/Intel/Apple/Qualcomm machines too. This reported {"available":
    # False} on all of them as soon as nvidia-smi wasn't found, the same class of bug fixed in
    # self_status.py and executor_enhanced.py's GPU_STATUS.
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__ + ": " + str(exc)}
    if not hw.has_gpu:
        return {"available": False}
    return {
        "available": True,
        "name": hw.gpu_name,
        "vendor": hw.gpu_vendor,
        "memory_total_mib": int(hw.total_vram_mb) if hw.total_vram_mb else None,
        "estimated": bool(hw.gpu_detection_uncertain),
    }


def _nvidia_info() -> Dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        if not out:
            return _gpu_hardware_fallback()
        first = out.splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        return {
            "available": True,
            "name": parts[0] if len(parts) > 0 else "",
            "memory_total_mib": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else parts[1] if len(parts) > 1 else None,
            "memory_free_mib": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else parts[2] if len(parts) > 2 else None,
            "driver": parts[3] if len(parts) > 3 else "",
        }
    except Exception as exc:
        rep = _gpu_hardware_fallback()
        rep.setdefault("nvidia_smi_error", type(exc).__name__ + ": " + str(exc))
        return rep


def _safe_getattr(obj: Any, names: list[str]) -> Any:
    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            continue
    return None


def _gguf_runtime() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "module_imported": False,
        "llm_exists": False,
        "effective": {},
        "live_override": {},
        "errors": [],
    }
    try:
        from eli.cognition import gguf_inference as gg
        out["module_imported"] = True
        llm = getattr(gg, "_llm", None)
        out["llm_exists"] = llm is not None
        out["live_override"] = (
            getattr(gg, "_live_runtime_override", None)
            or getattr(gg, "_live_runtime_params", None)
            or {}
        )

        effective = {}
        for key, names in {
            "n_ctx": ["n_ctx", "_n_ctx", "context_size"],
            "n_gpu_layers": ["n_gpu_layers", "_n_gpu_layers"],
            "n_threads": ["n_threads", "_n_threads"],
            "n_batch": ["n_batch", "batch_size", "_n_batch"],
            "model_path": ["model_path", "_model_path"],
        }.items():
            val = _safe_getattr(gg, names)
            if val is not None:
                effective[key] = str(val) if isinstance(val, Path) else val

        if llm is not None:
            for key, names in {
                "llm_n_ctx": ["n_ctx", "_n_ctx", "context_params"],
                "llm_model_path": ["model_path", "model"],
            }.items():
                val = _safe_getattr(llm, names)
                if val is not None:
                    effective[key] = str(val)

            # llama-cpp-python exposes metadata inconsistently across versions.
            try:
                if hasattr(llm, "n_ctx") and callable(llm.n_ctx):
                    effective["llm_n_ctx_callable"] = llm.n_ctx()
            except Exception:
                pass

        out["effective"] = effective
    except Exception as exc:
        out["errors"].append(type(exc).__name__ + ": " + str(exc))
    return out


def import_health(modules: list[str] | None = None) -> Dict[str, Any]:
    modules = modules or [
        "eli.kernel.engine",
        "eli.execution.router_enhanced",
        "eli.execution.executor_enhanced",
        "eli.cognition.gguf_inference",
        "eli.cognition.orchestrator",
        "eli.cognition.context_synthesiser",
        "eli.cognition.response_governance",
        "eli.memory.memory_truth",
        "eli.runtime.truth_report",
    ]
    results = {}
    for name in modules:
        try:
            importlib.import_module(name)
            results[name] = {"ok": True}
        except Exception as exc:
            results[name] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
    return results


def runtime_truth_report(engine: Any = None) -> Dict[str, Any]:
    root = _project_root()
    # The install tree isn't where a packaged build keeps its data: the code is on a read-only
    # AppImage mount while settings and the snapshot live under the user's config/data dirs. Reading
    # them from the project root made this report describe a runtime that doesn't exist (the 2.1.82
    # self-report failure ce40453 fixed elsewhere).
    try:
        from eli.core.paths import get_paths as _gp
        _p = _gp()
        settings_path = Path(_p.config_dir) / "settings.json"
        snapshot_path = Path(_p.artifacts_dir) / "runtime_snapshot.json"
    except Exception:
        settings_path = root / "config" / "settings.json"
        snapshot_path = root / "artifacts" / "runtime_snapshot.json"
    settings = _read_json(settings_path)
    snapshot = _read_json(snapshot_path)

    env_keys = [
        "ELI_PROJECT_ROOT",
        "ELI_DATA_DIR",
        "ELI_CONFIG_DIR",
        "ELI_GGUF_MODEL",
        "ELI_GGUF_MODEL_PATH",
        "ELI_GGUF_N_CTX",
        "ELI_GGUF_N_GPU_LAYERS",
        "ELI_GGUF_N_THREADS",
        "ELI_GGUF_N_BATCH",
        "ELI_GGUF_MAX_TOKENS",
        "ELI_LOCAL_STT_MODEL",
        "ELI_WHISPER_MODEL",
        "ELI_WHISPER_MODEL_DIR",
    ]

    engine_info: Dict[str, Any] = {}
    if engine is not None:
        engine_info = {
            "class": type(engine).__name__,
            "reasoning_mode": getattr(engine, "reasoning_mode", None),
            "mode": getattr(engine, "mode", None),
            "last_action": getattr(engine, "_last_action", None),
            "last_trace_exists": getattr(engine, "_last_trace", None) is not None,
        }

    return {
        "project_root": str(root),
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "git": _git_info(root),
        "settings_path": str(settings_path),
        "settings_exists": settings_path.exists(),
        "settings": {
            k: settings.get(k)
            for k in (
                "provider",
                "model_path",
                "gguf_model_path",
                "n_ctx",
                "n_gpu_layers",
                "n_threads",
                "batch_size",
                "max_tokens",
                "temperature",
                "top_p",
                "hw_profile_n_ctx",
                "hw_profile_n_gpu_layers",
                "hw_profile_batch_size",
            )
            if k in settings
        },
        "runtime_snapshot_path": str(snapshot_path),
        "runtime_snapshot_exists": snapshot_path.exists(),
        "runtime_snapshot": snapshot,
        "load_facts": runtime_load_facts(snapshot, settings),
        "environment": {k: os.environ.get(k) for k in env_keys if os.environ.get(k) is not None},
        "gpu": _nvidia_info(),
        "gguf": _gguf_runtime(),
        "engine": engine_info,
        "import_health": import_health(),
    }


def format_runtime_truth(report: Dict[str, Any] | None = None) -> str:
    report = report or runtime_truth_report()
    settings = report.get("settings", {})
    snapshot = report.get("runtime_snapshot", {})
    gguf = report.get("gguf", {})
    gpu = report.get("gpu", {})
    git = report.get("git", {})
    imports = report.get("import_health", {})
    # Effective runtime: what actually loaded. The launcher writes the split into
    # runtime_snapshot.json and _live_runtime_params after the load that succeeded. If those say
    # load_mode=CPU while settings asked for 21 GPU layers, that mismatch is the truth.
    snap_eff = snapshot.get("effective") or {}
    snap_req = snapshot.get("requested") or {}
    eff_n_ctx     = snap_eff.get("n_ctx", snapshot.get("n_ctx"))
    eff_gpu       = snap_eff.get("n_gpu_layers", snapshot.get("n_gpu_layers"))
    eff_threads   = snap_eff.get("n_threads", snapshot.get("n_threads"))
    eff_batch     = snap_eff.get("n_batch", snapshot.get("n_batch"))
    load_mode     = snapshot.get("load_mode")
    on_gpu        = snapshot.get("on_gpu")
    facts         = report.get("load_facts") or runtime_load_facts(snapshot, settings)
    # snapshot["clamped"] is never set by a real writer; an explicit flag wins, else the comparison.
    clamped       = snapshot.get("clamped") if snapshot.get("clamped") is not None \
        else facts.get("clamped")

    bad_imports = {k: v for k, v in imports.items() if not v.get("ok")}
    plat = report.get("platform", {})
    payload = {
        "surface": "runtime_truth_evidence",
        "project_root": report.get("project_root"),
        "python": report.get("python"),
        "platform": {
            "system": plat.get("system"),
            "release": plat.get("release"),
            "machine": plat.get("machine"),
        },
        "git": {
            "branch": git.get("branch"),
            "commit": git.get("commit"),
            "dirty_files_count": len(git.get("dirty_files") or []),
        },
        "configured": {
            "provider": settings.get("provider"),
            "model_path": settings.get("model_path") or settings.get("gguf_model_path"),
            "n_ctx": settings.get("n_ctx"),
            "n_gpu_layers": settings.get("n_gpu_layers"),
            "n_threads": settings.get("n_threads"),
            "batch_size": settings.get("batch_size"),
            "max_tokens": settings.get("max_tokens"),
        },
        "effective": {
            "snapshot_path": report.get("runtime_snapshot_path"),
            "snapshot_exists": report.get("runtime_snapshot_exists"),
            "load_mode": load_mode,
            "on_gpu": on_gpu,
            "clamped": clamped,
            "requested": snap_req,
            "n_ctx": eff_n_ctx,
            "n_gpu_layers": eff_gpu,
            "n_threads": eff_threads,
            "n_batch": eff_batch,
        },
        "load_facts": facts,
        "gguf": {
            "module_imported": gguf.get("module_imported"),
            "llm_exists": gguf.get("llm_exists"),
            "effective": gguf.get("effective", {}),
            "live_override": gguf.get("live_override", {}),
        },
        "gpu": gpu,
        "import_health": {
            "ok": len(imports) - len(bad_imports),
            "total": len(imports),
            "failed": bad_imports,
        },
    }
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)
