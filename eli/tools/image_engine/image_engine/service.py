from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from .contracts import ArtifactRecord, EngineConfig, JobRequest, JobResult, slug, utc_now
from .memory import ImageMemory
from .prompt_compiler import PromptCompiler
from .project_analyzer import analyze_project_profile
from .quality import choose_best, image_hash, score_image
from .plotting import generate_plot
from . import visual_core as core



from eli.tools.image_engine.runtime_paths import image_outputs_dir, image_logs_dir, image_jobs_dir, image_index_db, image_engine_root
def _normalise_runtime_paths(config):
    """
    Convert legacy source-local image-engine paths into per-user artifact paths.

    This prevents generated images, logs, manifests, jobs, and image-index DBs
    from landing inside eli/tools/image_engine in redistributed installs.
    """
    def clean(value):
        return str(value or "").strip()

    output = clean(getattr(config, "output_dir", ""))
    log = clean(getattr(config, "log_dir", ""))
    jobs = clean(getattr(config, "jobs_dir", ""))
    memory = clean(getattr(config, "memory_db", ""))

    if output in {"", "outputs", "./outputs"}:
        config.output_dir = str(image_outputs_dir())

    if log in {"", "logs", "./logs"}:
        config.log_dir = str(image_logs_dir())

    if jobs in {"", "outputs/jobs", "./outputs/jobs"}:
        config.jobs_dir = str(image_jobs_dir())

    if memory in {"", "logs/image_index.sqlite", "./logs/image_index.sqlite"}:
        config.memory_db = str(image_index_db())

    return config

class ImageEngine:
    """ELI-native image subsystem.

    It accepts job dictionaries, creates job folders, compiles prompt/plot plans,
    renders images or charts, writes manifests, scores outputs, and indexes
    artifacts in SQLite memory.
    """

    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig()
        self.config = _normalise_runtime_paths(self.config)
        self.root = Path(self.config.root).expanduser().resolve() if self.config.root else core.package_root()
        self.output_dir = self._resolve(self.config.output_dir)
        self.log_dir = self._resolve(self.config.log_dir)
        self.jobs_dir = self._resolve(self.config.jobs_dir)
        self.memory_path = self._resolve(self.config.memory_db)
        self.compiler = PromptCompiler()
        self.memory = ImageMemory(self.memory_path) if self.config.save_memory else None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, path: str | Path) -> "ImageEngine":
        return cls(EngineConfig.from_file(path))

    def _resolve(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    def _new_job_id(self, task: str, prompt: str = "") -> str:
        stem = slug(prompt or task, fallback=task, max_len=34)
        return f"{task}_{time.strftime('%Y%m%d_%H%M%S')}_{stem}"

    def run(self, request: dict[str, Any] | JobRequest) -> dict[str, Any]:
        req = request if isinstance(request, JobRequest) else JobRequest.from_mapping(request)
        task = (req.task or "generate_image").lower()
        if task in {"generate", "image", "generate_image", "render"}:
            result = self.generate_images(req)
        elif task in {"plot", "chart", "graph", "generate_plot"}:
            result = self.generate_plot(req)
        elif task in {"profile", "project_profile"}:
            result = self.project_profile(req)
        else:
            raise ValueError(f"Unsupported image engine task: {task}")
        return result.to_dict()

    def generate_images(self, req: JobRequest) -> JobResult:
        job_id = self._new_job_id("image", req.prompt or req.title)
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        result = JobResult(job_id=job_id, status="running", task="generate_image", job_dir=str(job_dir))
        core.configure_logging(self.log_dir, verbose=bool(req.options.get("verbose", False)))

        request_dict = req.to_dict()
        if self.memory:
            self.memory.create_job(job_id, "generate_image", request_dict, project=req.project, prompt=req.prompt)

        try:
            project_path = self._resolve_project(req.project)
            project = core.analyze_project_folder(str(project_path) if project_path else "")
            brief = self.compiler.compile_image(request_dict, project)
            core.save_json(brief.to_dict(), job_dir / "prompt_plan.json")

            args = self._image_args(req, job_dir)
            backend = core.build_backend(args)
            interpreter = core.PromptInterpreter()
            saved: list[Path] = []
            scored: list[tuple[Path, dict[str, Any]]] = []

            for i in range(max(1, int(req.count))):
                spec = interpreter.build(req.prompt, project, args, i)
                image = backend.generate(spec)

                ext = core.output_extension(args.format)
                name = "_".join([
                    args.prefix,
                    f"{i:03d}",
                    spec.scene_type,
                    spec.palette.name,
                    f"seed{spec.seed}",
                ])
                if args.name_from_prompt:
                    name = f"{args.prefix}_{core.sanitize_filename(spec.title, 36)}_{i:03d}_{spec.scene_type}_seed{spec.seed}"
                out_path = job_dir / f"{name}.{ext}"

                core.save_image(image, out_path, args.format)
                saved.append(out_path)

                spec_data = core.spec_to_jsonable(spec)
                quality = score_image(out_path) if self.config.auto_score else {"score": None}
                scored.append((out_path, quality))

                metadata = {
                    "spec": spec_data,
                    "quality": quality,
                    "brief": brief.to_dict(),
                }
                core.save_json(metadata, job_dir / f"{name}.json")

                record = ArtifactRecord(
                    artifact_type="image",
                    path=str(out_path),
                    score=quality.get("score"),
                    tags=[spec.scene_type, spec.style, spec.palette.name, *spec.project_tags[:12]],
                    metadata=metadata,
                )
                result.add(record)
                if self.memory:
                    self.memory.add_artifact(
                        job_id,
                        "image",
                        out_path,
                        prompt=spec.prompt,
                        project=req.project,
                        tags=record.tags,
                        score=record.score,
                        metadata=metadata,
                        artifact_hash=quality.get("average_hash", ""),
                    )

            if self.config.make_contact_sheet and len(saved) > 1:
                sheet_path = job_dir / f"{args.prefix}_contact_sheet.jpg"
                core.make_contact_sheet(saved, sheet_path)
                sheet_record = ArtifactRecord("contact_sheet", str(sheet_path), metadata={"count": len(saved)})
                result.add(sheet_record)
                if self.memory:
                    self.memory.add_artifact(job_id, "contact_sheet", sheet_path, prompt=req.prompt, project=req.project, metadata=sheet_record.metadata)

            best_path = choose_best(scored)
            if best_path:
                best_ext = best_path.suffix
                best_copy = job_dir / f"best{best_ext}"
                shutil.copy2(best_path, best_copy)
                result.best = str(best_copy)

            result.status = "complete"
            result.finished_at = utc_now()
            manifest_path = job_dir / "manifest.json"
            result.manifest = str(manifest_path)
            core.save_json(result.to_dict(), manifest_path)

            if self.memory:
                self.memory.finish_job(job_id, "complete", result.to_dict())

            return result

        except Exception as exc:
            logging.exception("Image job failed")
            result.status = "failed"
            result.error = str(exc)
            result.finished_at = utc_now()
            manifest_path = job_dir / "manifest.json"
            result.manifest = str(manifest_path)
            core.save_json(result.to_dict(), manifest_path)
            if self.memory:
                self.memory.finish_job(job_id, "failed", result.to_dict())
            return result

    def generate_plot(self, req: JobRequest) -> JobResult:
        job_id = self._new_job_id("plot", req.prompt or req.title or "data")
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        result = JobResult(job_id=job_id, status="running", task="generate_plot", job_dir=str(job_dir))
        core.configure_logging(self.log_dir, verbose=bool(req.options.get("verbose", False)))

        request_dict = req.to_dict()
        plot_plan = self.compiler.compile_plot({**request_dict, **req.options})
        core.save_json(plot_plan, job_dir / "plot_plan.json")

        if self.memory:
            self.memory.create_job(job_id, "generate_plot", request_dict, project=req.project, prompt=req.prompt)

        try:
            fmt = str(req.output_format or self.config.default_format).lower()
            ext = core.output_extension(fmt)
            out_path = job_dir / f"{slug(req.title or req.prompt or 'plot', 'plot')}.{ext}"

            plot_request = {**request_dict, **req.options}
            plot_request.setdefault("width", req.width)
            plot_request.setdefault("height", req.height)
            plot_request.setdefault("title", req.title or "ELI Data Plot")
            plot_request.setdefault("palette", req.palette)
            plot_output = generate_plot(
                plot_request,
                out_path,
                data_file=str(req.options.get("data_file") or req.options.get("data_path") or ""),
                data=req.data,
            )

            quality = score_image(out_path) if self.config.auto_score else {"score": None, "average_hash": image_hash(out_path)}
            metadata = {
                "plot": plot_output.spec,
                "summary": plot_output.summary,
                "quality": quality,
                "plan": plot_plan,
            }

            core.save_json(metadata, out_path.with_suffix(".json"))

            record = ArtifactRecord(
                artifact_type="plot",
                path=str(out_path),
                score=quality.get("score"),
                tags=["plot", str(plot_output.spec.get("kind", "")), *plot_output.summary.get("numeric_columns", [])[:12]],
                metadata=metadata,
            )
            result.add(record)
            result.best = str(out_path)
            result.status = "complete"
            result.finished_at = utc_now()
            result.manifest = str(job_dir / "manifest.json")
            core.save_json(result.to_dict(), job_dir / "manifest.json")

            if self.memory:
                self.memory.add_artifact(
                    job_id,
                    "plot",
                    out_path,
                    prompt=req.prompt,
                    project=req.project,
                    tags=record.tags,
                    score=record.score,
                    metadata=metadata,
                    artifact_hash=quality.get("average_hash", ""),
                )
                self.memory.finish_job(job_id, "complete", result.to_dict())

            return result

        except Exception as exc:
            logging.exception("Plot job failed")
            result.status = "failed"
            result.error = str(exc)
            result.finished_at = utc_now()
            result.manifest = str(job_dir / "manifest.json")
            core.save_json(result.to_dict(), job_dir / "manifest.json")
            if self.memory:
                self.memory.finish_job(job_id, "failed", result.to_dict())
            return result

    def project_profile(self, req: JobRequest) -> JobResult:
        job_id = self._new_job_id("profile", req.project or req.prompt or "project")
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        project_path = self._resolve_project(req.project)
        profile = analyze_project_profile(project_path or req.project)
        path = job_dir / "project_visual_profile.json"
        core.save_json(profile, path)

        result = JobResult(job_id=job_id, status="complete", task="project_profile", job_dir=str(job_dir), best=str(path), manifest=str(path), finished_at=utc_now())
        result.add(ArtifactRecord("profile", str(path), tags=profile.get("tags", []), metadata=profile))
        if self.memory:
            self.memory.create_job(job_id, "project_profile", req.to_dict(), project=req.project, prompt=req.prompt)
            self.memory.add_artifact(job_id, "profile", path, prompt=req.prompt, project=req.project, tags=profile.get("tags", []), metadata=profile)
            self.memory.finish_job(job_id, "complete", result.to_dict())
        return result

    def search(self, query: str = "", *, artifact_type: str = "", project: str = "", limit: int = 25) -> list[dict[str, Any]]:
        if not self.memory:
            return []
        return self.memory.search(query, artifact_type=artifact_type, project=project, limit=limit)

    def jobs(self, limit: int = 25) -> list[dict[str, Any]]:
        if not self.memory:
            return []
        return self.memory.list_jobs(limit=limit)

    def _resolve_project(self, project: str) -> Path | None:
        if not project:
            return None
        p = Path(project).expanduser()
        if p.is_absolute():
            return p
        direct = (Path.cwd() / p).resolve()
        if direct.exists():
            return direct
        under_projects = (self.root / "projects" / p).resolve()
        return under_projects if under_projects.exists() else direct

    def _image_args(self, req: JobRequest, job_dir: Path) -> argparse.Namespace:
        opts = req.options
        return argparse.Namespace(
            query=req.prompt,
            query_file=str(opts.get("query_file", "")),
            project=req.project,
            preset=str(opts.get("preset", "")),
            type=req.intent or "auto",
            style=req.style or "auto",
            palette=req.palette or "auto",
            backend=req.backend or self.config.default_backend,
            model=str(opts.get("model", "")),
            device=str(opts.get("device", "auto")),
            steps=int(opts.get("steps", 36)),
            guidance=float(opts.get("guidance", 7.2)),
            negative=req.negative_prompt or str(opts.get("negative", "")),
            title=req.title,
            count=max(1, int(req.count)),
            seed=int(req.seed),
            width=int(req.width),
            height=int(req.height),
            supersample=int(opts.get("supersample", 1)),
            out=str(job_dir),
            logs=str(self.log_dir),
            prefix=str(opts.get("prefix", "image_engine")),
            format=str(req.output_format or opts.get("format", self.config.default_format)),
            sheet=bool(opts.get("sheet", False)),
            save_specs=True,
            manifest=True,
            name_from_prompt=bool(opts.get("name_from_prompt", False)),
            verbose=bool(opts.get("verbose", False)),
        )
