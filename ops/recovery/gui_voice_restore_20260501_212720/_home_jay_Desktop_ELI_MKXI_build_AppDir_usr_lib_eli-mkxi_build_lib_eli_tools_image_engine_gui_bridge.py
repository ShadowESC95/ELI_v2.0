from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.core.paths import get_paths
from eli.kernel.state import get_user_name, get_user_profile_text, load_user_profile

from .image_engine.visual_core import (
    PALETTES,
    apply_preset_defaults,
    build_parser,
    generate_batch,
    package_root,
    validate_args,
)


SCENE_CHOICES = ["auto", "portrait", "landscape", "poster", "abstract", "emblem", "product", "cityscape", "space"]
STYLE_CHOICES = ["auto", "balanced", "cinematic", "minimal", "luxury", "neon", "fantasy"]
PALETTE_CHOICES = ["auto", *sorted(PALETTES.keys())]


@dataclass
class ImageGenerationRequest:
    prompt: str
    project: str = ""
    preset: str = ""
    scene_type: str = "auto"
    style: str = "auto"
    palette: str = "auto"
    count: int = 1
    width: int = 1400
    height: int = 900
    seed: int = 77
    supersample: int = 1
    negative: str = ""
    prefix: str = "eli"
    fmt: str = "png"
    backend: str = "auto"
    model: str = ""
    device: str = "auto"
    steps: int = 36
    guidance: float = 7.2
    save_specs: bool = True
    manifest: bool = True
    sheet: bool = False
    name_from_prompt: bool = True
    use_chat_context: bool = True
    use_proactive_context: bool = True
    auto_personalize: bool = True
    out_dir: str = ""
    logs_dir: str = ""


@dataclass
class ImageGenerationResult:
    saved_paths: List[str]
    contact_sheet: str | None
    manifest_path: str | None
    out_dir: str
    applied_prompt: str
    personalization_notes: List[str] = field(default_factory=list)


def tool_root() -> Path:
    return package_root()


def output_dir() -> Path:
    return tool_root() / "outputs"


def discover_local_image_models() -> List[Path]:
    project_root = Path(__file__).resolve().parents[3]
    candidate_roots = [
        project_root / "models" / "image",
        project_root / "models" / "diffusion",
        project_root / "models" / "sd",
        project_root / "models",
        Path.home() / "models",
    ]
    allowed_suffixes = {".safetensors", ".ckpt"}
    discovered: List[Path] = []
    model_dirs: List[Path] = []
    seen: set[str] = set()

    def _looks_like_image_model(path: Path) -> bool:
        low = str(path).lower()
        if "/lora/" in low or "adapter_model" in low:
            return False
        return True

    for root in candidate_roots:
        try:
            if not root.exists():
                continue
        except Exception:
            continue

        try:
            if root.is_file() and root.suffix.lower() in allowed_suffixes:
                resolved = root.resolve()
                key = str(resolved)
                if key not in seen and _looks_like_image_model(resolved):
                    seen.add(key)
                    discovered.append(resolved)
                continue
        except Exception:
            continue

        try:
            for marker in root.rglob("model_index.json"):
                resolved = marker.parent.resolve()
                key = str(resolved)
                if key not in seen and _looks_like_image_model(resolved):
                    seen.add(key)
                    discovered.append(resolved)
                    model_dirs.append(resolved)
            for suffix in allowed_suffixes:
                for model_file in root.rglob(f"*{suffix}"):
                    resolved = model_file.resolve()
                    if any(resolved.is_relative_to(model_dir) for model_dir in model_dirs):
                        continue
                    key = str(resolved)
                    if key not in seen and _looks_like_image_model(resolved):
                        seen.add(key)
                        discovered.append(resolved)
        except Exception:
            continue

    discovered.sort(key=lambda p: str(p).lower())
    return discovered


def discover_presets() -> List[str]:
    preset_dir = tool_root() / "presets"
    if not preset_dir.exists():
        return []
    return sorted(p.stem for p in preset_dir.glob("*.json"))


def list_recent_outputs(limit: int = 24) -> List[Path]:
    out = output_dir()
    if not out.exists():
        return []
    items = [p for p in out.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return items[:limit]


def _load_recent_proactive_lines(max_lines: int = 6) -> List[str]:
    files = [
        Path(get_paths().artifacts_dir) / "proactive" / "latest_context.txt",
        Path(get_paths().artifacts_dir) / "proactive" / "latest_action.txt",
    ]
    lines: List[str] = []
    for path in files:
        try:
            if path.exists():
                lines.extend(
                    ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if ln.strip()
                )
        except Exception:
            continue
    return lines[:max_lines]


def _is_noise_context_line(text: str) -> bool:
    low = text.strip().lower()
    if not low:
        return True
    noisy_prefixes = (
        "create shortcut for",
        "reflection (24h)",
        "(24h): conversation",
        "conversation volume:",
        "summary:",
    )
    return any(low.startswith(prefix) for prefix in noisy_prefixes)


def _is_eli_self_prompt(text: str) -> bool:
    low = str(text or "").lower()
    return bool(
        re.search(r"\b(draw|generate|create|show|image|picture|portrait)\b.{0,40}\b(yourself|eli)\b", low)
        or re.search(r"\b(who you see eli as|what you look like|what eli looks like|eli self[- ]?portrait)\b", low)
    )


def _eli_self_prompt() -> str:
    return (
        "ELI self-portrait: non-human photorealistic 3D cybernetic intelligence avatar, "
        "translucent synthetic face, luminous neural core, quantum circuitry, dark engineering console, "
        "cinematic volumetric light, no text, no ordinary human clothing"
    )


def _visual_profile_lines(profile_text: str, limit: int = 3) -> List[str]:
    blocked = (
        "name:",
        "user name",
        "preferred name",
        "user's name",
        "username",
    )
    compact: List[str] = []
    for line in str(profile_text or "").splitlines():
        cleaned = " ".join(line.strip().split())
        low = cleaned.lower()
        if not cleaned or any(marker in low for marker in blocked):
            continue
        compact.append(cleaned[:120])
        if len(compact) >= limit:
            break
    return compact


def build_personalized_prompt(
    base_prompt: str,
    settings: Dict[str, Any] | None = None,
    *,
    proactive_ground: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> tuple[str, List[str]]:
    settings = dict(settings or {})
    prompt = (base_prompt or "").strip()
    notes: List[str] = []

    if not settings.get("image_auto_personalize", True):
        return prompt, notes

    additions: List[str] = []
    eli_self_prompt = _is_eli_self_prompt(prompt)
    if eli_self_prompt:
        prompt = _eli_self_prompt()
        notes.append("Expanded ELI self-image prompt")

    user_name = get_user_name("") or str(settings.get("user_name", "") or "").strip()
    if user_name:
        notes.append(f"User identity: {user_name}")
        if not eli_self_prompt:
            additions.append("Align the visual direction with the user's saved aesthetic preferences.")

    style_profile = str(settings.get("image_style_profile", "auto") or "auto").strip()
    if style_profile and style_profile != "auto":
        notes.append(f"Preferred style: {style_profile}")
        additions.append(f"Preferred aesthetic: {style_profile}.")

    palette_profile = str(settings.get("image_palette_profile", "auto") or "auto").strip()
    if palette_profile and palette_profile != "auto":
        notes.append(f"Palette bias: {palette_profile}")
        additions.append(f"Preferred palette family: {palette_profile}.")

    profile = load_user_profile()
    profile_text = get_user_profile_text().strip()
    if profile_text:
        compact = _visual_profile_lines(profile_text)
        if compact:
            notes.append("Applied user profile context")
            additions.append("User profile cues: " + "; ".join(compact) + ".")

    note_text = str(settings.get("image_profile_notes", "") or "").strip()
    if note_text:
        notes.append("Applied custom visual notes")
        additions.append("Visual identity notes: " + note_text + ".")

    if settings.get("image_use_chat_context", True) and conversation_history and not eli_self_prompt:
        recent_user = [
            str(m.get("content", "")).strip()
            for m in reversed(conversation_history)
            if m.get("role") == "user" and str(m.get("content", "")).strip()
        ][:2]
        prompt_low = prompt.lower()
        recent_user = [
            line for line in recent_user
            if line and line.lower() != prompt_low and line.lower() not in prompt_low
        ]
        if recent_user:
            recent_user.reverse()
            notes.append("Used recent chat context")
            additions.append(
                "Recent user context: " + " | ".join(line[:180] for line in recent_user) + "."
            )

    use_proactive = settings.get("image_use_proactive_context", True) and not eli_self_prompt
    if use_proactive:
        pattern_lines: List[str] = []
        habit_lines: List[str] = []
        proactive_ground = dict(proactive_ground or {})
        for item in proactive_ground.get("daemon_patterns", [])[:3]:
            suggestion = str(item.get("suggestion", "") or "").strip()
            if suggestion and not _is_noise_context_line(suggestion):
                pattern_lines.append(suggestion)
        for item in proactive_ground.get("habit_rules", [])[:2]:
            name = str(item.get("name", "") or "").strip()
            if name:
                habit_lines.append(name)
        artifact_lines = [
            line for line in _load_recent_proactive_lines(max_lines=4)
            if not _is_noise_context_line(line)
        ]
        if pattern_lines or habit_lines or artifact_lines:
            notes.append("Used proactive context")
            chunks = []
            if pattern_lines:
                chunks.append("Detected patterns: " + "; ".join(pattern_lines))
            if habit_lines:
                chunks.append("Active habits: " + "; ".join(habit_lines))
            if artifact_lines:
                chunks.append("Recent proactive notes: " + "; ".join(artifact_lines))
            additions.append(" ".join(chunks) + ".")

    if not prompt:
        prompt = "Generate a distinctive image that matches the user's current context."

    if not additions:
        return prompt, notes

    final_prompt = prompt + "\n\nVisual direction:\n- " + "\n- ".join(additions)
    return final_prompt.strip(), notes


def generate_images(
    request: ImageGenerationRequest,
    settings: Dict[str, Any] | None = None,
    *,
    proactive_ground: Optional[Dict[str, Any]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> ImageGenerationResult:
    parser = build_parser()
    args = parser.parse_args([])
    args.preset = request.preset
    args = apply_preset_defaults(args, parser)

    settings = dict(settings or {})
    settings["image_auto_personalize"] = bool(request.auto_personalize)
    settings["image_use_chat_context"] = bool(request.use_chat_context)
    settings["image_use_proactive_context"] = bool(request.use_proactive_context)
    applied_prompt, notes = build_personalized_prompt(
        request.prompt,
        settings,
        proactive_ground=proactive_ground,
        conversation_history=conversation_history,
    )

    args.query = applied_prompt
    args.project = request.project or str(settings.get("image_default_project_path", "") or "")
    args.preset = request.preset
    args.type = request.scene_type
    args.style = request.style
    args.palette = request.palette
    args.backend = request.backend or str(settings.get("image_backend", "auto") or "auto")
    args.model = request.model or str(settings.get("image_model_path", "") or "")
    args.device = request.device or str(settings.get("image_device", "auto") or "auto")
    args.steps = int(request.steps or settings.get("image_steps", 36) or 36)
    args.guidance = float(request.guidance or settings.get("image_guidance", 7.2) or 7.2)
    args.negative = request.negative or str(settings.get("image_negative_prompt", "") or "")
    args.count = int(request.count)
    args.seed = int(request.seed)
    args.width = int(request.width)
    args.height = int(request.height)
    args.supersample = int(request.supersample)
    args.out = request.out_dir
    args.logs = request.logs_dir
    args.prefix = request.prefix
    args.format = request.fmt
    args.sheet = bool(request.sheet)
    args.save_specs = bool(request.save_specs)
    args.manifest = bool(request.manifest)
    args.name_from_prompt = bool(request.name_from_prompt)
    args.verbose = False
    args = validate_args(args)

    saved_paths = [str(p) for p in generate_batch(args)]
    out_dir = str((Path(args.out).expanduser().resolve() if args.out else output_dir().resolve()))

    sheet_path = Path(out_dir) / f"{args.prefix}_contact_sheet.jpg"
    manifest_path = Path(out_dir) / f"{args.prefix}_manifest.json"
    result = ImageGenerationResult(
        saved_paths=saved_paths,
        contact_sheet=str(sheet_path) if args.sheet and sheet_path.exists() else None,
        manifest_path=str(manifest_path) if args.manifest and manifest_path.exists() else None,
        out_dir=out_dir,
        applied_prompt=applied_prompt,
        personalization_notes=notes,
    )
    _write_runtime_artifact(result, settings)
    return result


def _write_runtime_artifact(result: ImageGenerationResult, settings: Dict[str, Any]) -> None:
    try:
        runtime_dir = Path(get_paths().artifacts_dir) / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload["settings"] = {
            "image_style_profile": settings.get("image_style_profile", "auto"),
            "image_palette_profile": settings.get("image_palette_profile", "auto"),
            "image_auto_personalize": bool(settings.get("image_auto_personalize", True)),
        }
        (runtime_dir / "last_image_generation.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
