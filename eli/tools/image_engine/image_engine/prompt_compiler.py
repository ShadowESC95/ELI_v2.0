from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from . import visual_core as core


@dataclass(slots=True)
class VisualBrief:
    intent: str
    subject: str
    mood: list[str]
    composition: str
    style: str
    scene_type: str
    palette: str
    negative: list[str]
    project_tags: list[str]
    render_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptCompiler:
    """Converts user intent/project context into a render-oriented visual brief."""

    def compile_image(self, request: dict[str, Any], project: core.ProjectContext | None = None) -> VisualBrief:
        prompt = request.get("prompt") or request.get("query") or ""
        project = project or core.ProjectContext(text="", tags=[], colors=[], files=[])

        combined = " ".join([prompt, project.text or "", " ".join(project.tags[:60])]).strip()
        tokens = set(core.tokenize(combined))
        style = request.get("style") or "auto"
        if style == "auto":
            style = core.infer_style(combined)

        forced_scene = request.get("intent") or request.get("type") or "auto"
        scene_type = core.infer_scene_type(combined, forced=forced_scene)
        seed = int(request.get("seed") or 77)
        palette_name = request.get("palette") or "auto"
        palette = core.choose_palette(combined, seed, preferred=palette_name, project_colors=project.colors)

        subject_words = [
            t for t in core.tokenize(prompt)
            if t not in core.STOPWORDS and len(t) > 2
        ][:10]
        subject = " ".join(subject_words) or core.title_from_prompt(combined)

        mood: list[str] = []
        for word in ["cinematic", "mythic", "technical", "luxury", "minimal", "neon", "natural", "dark", "bright", "ancient", "futuristic"]:
            if word in combined.lower() or word in tokens:
                mood.append(word)
        if not mood:
            mood.append(style)

        composition = {
            "poster": "clear hierarchy, central hero element, readable negative space",
            "emblem": "centered mark, symmetrical silhouette, strong outer boundary",
            "product": "premium product focus, controlled lighting, clean foreground",
            "abstract": "balanced generative movement, depth, layered visual rhythm",
            "space": "deep background, luminous focal body, star field depth",
            "cityscape": "horizon-led urban composition, atmospheric perspective",
            "landscape": "foreground-midground-background depth with atmospheric light",
        }.get(scene_type, "balanced composition with a clear focal point")

        negative = [
            "watermark",
            "brand names",
            "company names",
            "unreadable text",
            "cluttered layout",
            "malformed geometry",
        ]
        if request.get("negative_prompt"):
            negative.extend(core.tokenize(str(request["negative_prompt"])))

        notes = [
            "save full manifest",
            "score output candidates",
            "index artifacts in local visual memory",
        ]
        if project.tags:
            notes.append("use project tags as weak style hints")
        if project.colors:
            notes.append("derive palette from project reference colors")

        return VisualBrief(
            intent=str(forced_scene),
            subject=subject,
            mood=mood,
            composition=composition,
            style=str(style),
            scene_type=str(scene_type),
            palette=palette.name,
            negative=negative,
            project_tags=project.tags[:30],
            render_notes=notes,
        )

    def compile_plot(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = request.get("kind") or request.get("chart") or "auto"
        title = request.get("title") or "ELI Data Plot"
        prompt = request.get("prompt") or ""
        return {
            "intent": "plot",
            "kind": kind,
            "title": title,
            "prompt": prompt,
            "x": request.get("x", ""),
            "y": request.get("y", ""),
            "notes": [
                "use matplotlib Agg backend",
                "write plot image plus JSON manifest",
                "index plot in visual memory",
            ],
        }
