from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json


from eli.tools.image_engine.runtime_paths import image_outputs_dir, image_logs_dir, image_jobs_dir, image_index_db
ArtifactType = Literal["image", "plot", "manifest", "contact_sheet", "profile"]
JobStatus = Literal["queued", "running", "complete", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str, fallback: str = "job", max_len: int = 72) -> str:
    import re
    value = re.sub(r"[^a-zA-Z0-9_\- ]+", "", (text or "").strip().lower())
    value = re.sub(r"\s+", "_", value).strip("_")
    return (value[:max_len] or fallback)


@dataclass(slots=True)
class EngineConfig:
    """Configuration for the ELI image subsystem."""

    root: str = ""
    output_dir: str = field(default_factory=lambda: str(image_outputs_dir()))
    log_dir: str = field(default_factory=lambda: str(image_logs_dir()))
    jobs_dir: str = field(default_factory=lambda: str(image_jobs_dir()))
    memory_db: str = field(default_factory=lambda: str(image_index_db()))
    default_backend: str = "procedural"
    fallback_backend: str = "procedural"
    default_format: str = "png"
    save_memory: bool = True
    auto_score: bool = True
    make_contact_sheet: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> "EngineConfig":
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JobRequest:
    """Generic job request consumed by ImageEngine.run()."""

    task: str = "generate_image"
    prompt: str = ""
    project: str = ""
    intent: str = "auto"
    count: int = 1
    width: int = 1400
    height: int = 900
    seed: int = 77
    style: str = "auto"
    palette: str = "auto"
    backend: str = "procedural"
    output_format: str = "png"
    title: str = ""
    negative_prompt: str = ""
    data: Any = None
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "JobRequest":
        normalized = dict(data)
        if "query" in normalized and "prompt" not in normalized:
            normalized["prompt"] = normalized.pop("query")
        if "type" in normalized and "intent" not in normalized:
            normalized["intent"] = normalized.pop("type")
        if "format" in normalized and "output_format" not in normalized:
            normalized["output_format"] = normalized.pop("format")
        if "negative" in normalized and "negative_prompt" not in normalized:
            normalized["negative_prompt"] = normalized.pop("negative")
        known = set(cls.__dataclass_fields__)
        options = {k: v for k, v in normalized.items() if k not in known}
        normalized = {k: v for k, v in normalized.items() if k in known}
        request = cls(**normalized)
        request.options.update(options)
        return request

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactRecord:
    artifact_type: ArtifactType
    path: str
    score: float | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class JobResult:
    job_id: str
    status: JobStatus
    task: str
    job_dir: str
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    best: str = ""
    manifest: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    finished_at: str = ""

    def add(self, record: ArtifactRecord) -> None:
        self.artifacts.append(record)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifacts"] = [a.to_dict() for a in self.artifacts]
        return data
