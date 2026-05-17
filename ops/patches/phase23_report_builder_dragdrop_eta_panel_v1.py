#!/usr/bin/env python3
from __future__ import annotations

import datetime as _dt
import pathlib
import py_compile
import re
import shutil
import textwrap

ROOT = pathlib.Path.cwd()
TARGET = ROOT / "eli/gui/labs_tab.py"

STAMP = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / f"ops/reports/phase23_report_builder_dragdrop_eta_panel_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

BACKUP = OUT / "labs_tab.py.before_phase23_dragdrop_eta.bak"
DIFF_HINT = OUT / "phase23_patch_notes.txt"
SUMMARY = OUT / "SUMMARY.md"

if not TARGET.exists():
    raise SystemExit(f"TARGET_MISSING: {TARGET}")

src = TARGET.read_text(encoding="utf-8")
shutil.copy2(TARGET, BACKUP)

original = src


def fail(msg: str) -> None:
    TARGET.write_text(original, encoding="utf-8")
    raise SystemExit(f"PATCH_FAILED_BACKUP_RESTORED: {msg}")


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Ensure imports used by persisted timing / ETA estimator
# ─────────────────────────────────────────────────────────────────────────────

def ensure_plain_import(text: str, module: str) -> str:
    if re.search(rf"(?m)^import\s+{re.escape(module)}\b", text):
        return text
    future = "from __future__ import annotations\n"
    if future in text:
        return text.replace(future, future + f"import {module}\n", 1)

    # fallback: insert before first existing import/from
    m = re.search(r"(?m)^(import\s+\w+|from\s+\w+)", text)
    if m:
        return text[:m.start()] + f"import {module}\n" + text[m.start():]
    return f"import {module}\n" + text


for mod in ("json", "math", "statistics", "time"):
    src = ensure_plain_import(src, mod)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Insert drag/drop QListWidget subclass before _ReportTab
# ─────────────────────────────────────────────────────────────────────────────

DROP_CLASS = r'''
# ── Phase 23: drag/drop evidence source list ────────────────────────────────
class _ReportEvidenceDropList(QListWidget):
    """Evidence list that accepts dropped files and folders."""

    def __init__(self, on_paths, parent=None):
        super().__init__(parent)
        self._on_paths = on_paths
        self.setAcceptDrops(True)
        try:
            self.viewport().setAcceptDrops(True)
        except Exception:
            pass
        try:
            self.setDropIndicatorShown(True)
        except Exception:
            pass
        self.setToolTip(
            "Drop supported evidence files or folders here, "
            "or use Add Files / Add Folder / Add project tree."
        )

    def _paths_from_event(self, event) -> list[str]:
        paths = []
        try:
            mime = event.mimeData()
            if mime is None or not mime.hasUrls():
                return paths
            for url in mime.urls():
                try:
                    local = url.toLocalFile()
                except Exception:
                    local = ""
                if local:
                    paths.append(local)
        except Exception:
            return []
        return paths

    def dragEnterEvent(self, event):
        if self._paths_from_event(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._paths_from_event(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._paths_from_event(event)
        if not paths:
            super().dropEvent(event)
            return
        try:
            if callable(self._on_paths):
                self._on_paths(paths)
            event.acceptProposedAction()
        except Exception:
            event.ignore()


'''

if "class _ReportEvidenceDropList(QListWidget):" not in src:
    anchor = "class _ReportTab(QWidget):"
    require(anchor in src, "Could not find _ReportTab declaration")
    src = src.replace(anchor, DROP_CLASS + anchor, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Replace plain source list with drop-enabled evidence list
# ─────────────────────────────────────────────────────────────────────────────

old_source_list = "        self._sources_list = QListWidget()"
new_source_list = "        self._sources_list = _ReportEvidenceDropList(self._rb_accept_evidence_drop_paths)"

if new_source_list not in src:
    require(old_source_list in src, "Could not find Report Builder _sources_list = QListWidget()")
    src = src.replace(old_source_list, new_source_list, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Insert evidence-drop ingest helpers before _read_pdf()
# ─────────────────────────────────────────────────────────────────────────────

DROP_HELPERS = r'''
    # ── Phase 23: evidence drag/drop ingestion ─────────────────────────────
    def _rb_existing_evidence_paths(self) -> set[str]:
        existing: set[str] = set()
        for item in getattr(self, "_sources", []) or []:
            try:
                raw = str(item.get("path", "") or "")
                if raw:
                    existing.add(str(Path(raw).expanduser().resolve()))
            except Exception:
                continue
        return existing

    def _rb_ingest_dropped_evidence_file(self, p: Path) -> tuple[bool, str]:
        """
        Ingest one dropped evidence file using the same preview semantics as
        the button-driven source loader. Returns (added, reason).
        """
        try:
            p = p.expanduser().resolve()
        except Exception:
            p = Path(str(p))

        if not p.exists() or not p.is_file():
            return False, "not-file"

        suffix = p.suffix.lower()
        if suffix not in self._SUPPORTED_EXTS:
            return False, "unsupported"

        canonical = str(p)
        if canonical in self._rb_existing_evidence_paths():
            return False, "duplicate"

        try:
            if suffix == ".pdf":
                preview = self._read_pdf(p)
                kind = "pdf"
            elif suffix in {".csv", ".tsv"}:
                preview = self._read_table(p)
                kind = suffix.lstrip(".")
            elif suffix == ".ipynb":
                preview = self._read_notebook(p)
                kind = "notebook"
            else:
                preview = p.read_text(encoding="utf-8", errors="replace")
                kind = suffix.lstrip(".") or "text"

            if len(preview) > self._MAX_PREVIEW_BYTES:
                preview = preview[: self._MAX_PREVIEW_BYTES] + "\n…(truncated)…"

            self._sources.append({
                "path": str(p),
                "name": p.name,
                "kind": kind,
                "bytes": int(p.stat().st_size),
                "preview": preview,
            })
            return True, "added"

        except Exception as exc:
            self._sources.append({
                "path": str(p),
                "name": p.name,
                "kind": suffix.lstrip(".") or "file",
                "bytes": int(p.stat().st_size) if p.exists() else 0,
                "preview": f"[Could not read: {exc}]",
            })
            return True, "added-with-preview-error"

    def _rb_accept_evidence_drop_paths(self, raw_paths: list[str]) -> None:
        """
        Accept files or folders dropped into the Evidence box.

        Folders are scanned recursively for Report Builder-supported source
        extensions. File count is capped only to prevent accidental ingestion
        of an entire drive; the cap can be raised using:
          ELI_REPORT_BUILDER_DROP_FILE_LIMIT
        """
        candidates: list[Path] = []
        unsupported_roots = 0
        folder_count = 0

        try:
            limit = int(os.environ.get("ELI_REPORT_BUILDER_DROP_FILE_LIMIT", "750") or "750")
        except Exception:
            limit = 750
        limit = max(1, limit)

        for raw in raw_paths or []:
            p = Path(str(raw)).expanduser()
            try:
                p = p.resolve()
            except Exception:
                pass

            if p.is_file():
                candidates.append(p)
                continue

            if p.is_dir():
                folder_count += 1
                try:
                    for child in sorted(p.rglob("*")):
                        if len(candidates) >= limit:
                            break
                        if child.is_file() and child.suffix.lower() in self._SUPPORTED_EXTS:
                            candidates.append(child)
                except Exception:
                    unsupported_roots += 1
                continue

            unsupported_roots += 1

        added = 0
        duplicates = 0
        unsupported = 0
        not_files = 0
        preview_errors = 0

        for p in candidates[:limit]:
            ok, reason = self._rb_ingest_dropped_evidence_file(p)
            if ok:
                added += 1
                if reason == "added-with-preview-error":
                    preview_errors += 1
            elif reason == "duplicate":
                duplicates += 1
            elif reason == "unsupported":
                unsupported += 1
            else:
                not_files += 1

        self._refresh_sources_list()

        if hasattr(self, "_status"):
            parts = [
                f"Evidence drop complete: added {added} source(s)"
            ]
            if folder_count:
                parts.append(f"from {folder_count} folder(s)")
            if duplicates:
                parts.append(f"{duplicates} duplicate(s) skipped")
            if unsupported or unsupported_roots:
                parts.append(f"{unsupported + unsupported_roots} unsupported/unreadable path(s) skipped")
            if not_files:
                parts.append(f"{not_files} non-file path(s) skipped")
            if preview_errors:
                parts.append(f"{preview_errors} source(s) added with preview-read warnings")
            if len(candidates) >= limit:
                parts.append(
                    f"drop scan capped at {limit} file(s); raise ELI_REPORT_BUILDER_DROP_FILE_LIMIT to ingest more"
                )
            self._status.setText("; ".join(parts) + ".")


'''

if "def _rb_accept_evidence_drop_paths(self, raw_paths: list[str])" not in src:
    read_pdf_anchor = "    def _read_pdf(self, p: Path) -> str:"
    require(read_pdf_anchor in src, "Could not find _read_pdf anchor for drop helper insertion")
    src = src.replace(read_pdf_anchor, DROP_HELPERS + read_pdf_anchor, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Insert persisted timing + ETA helpers before _rb_contract()
# ─────────────────────────────────────────────────────────────────────────────

ETA_HELPERS = r'''
    # ── Phase 23: persisted Report Builder timing + ETA model ──────────────
    @staticmethod
    def _rb_minutes_label(minutes: float) -> str:
        m = max(1, int(round(float(minutes or 0.0))))
        if m < 60:
            return f"{m}m"
        hours, rem = divmod(m, 60)
        if rem == 0:
            return f"{hours}h"
        return f"{hours}h {rem}m"

    def _rb_range_label(self, fast_minutes: float, slow_minutes: float) -> str:
        fast = min(float(fast_minutes), float(slow_minutes))
        slow = max(float(fast_minutes), float(slow_minutes))
        return f"{self._rb_minutes_label(fast)}–{self._rb_minutes_label(slow)}"

    def _rb_timing_store_path(self) -> Path:
        return Path("artifacts/runtime/report_builder_timing_samples.json")

    def _rb_get_timing_samples(self) -> list[dict[str, Any]]:
        cached = getattr(self, "_rb_timing_samples", None)
        if isinstance(cached, list):
            return cached

        path = self._rb_timing_store_path()
        samples: list[dict[str, Any]] = []
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict):
                    raw = data.get("samples", [])
                else:
                    raw = data
                if isinstance(raw, list):
                    samples = [dict(x) for x in raw if isinstance(x, dict)]
        except Exception:
            samples = []

        self._rb_timing_samples = samples[-120:]
        return self._rb_timing_samples

    def _rb_record_timing(self, stage: str, prompt: str, output: str, elapsed_seconds: float) -> None:
        try:
            samples = self._rb_get_timing_samples()
            output_words = self._rb_word_count(output or "")
            record = {
                "saved_at": time.time(),
                "stage": str(stage or "unknown"),
                "elapsed_seconds": float(max(0.0, elapsed_seconds or 0.0)),
                "prompt_chars": int(len(prompt or "")),
                "output_chars": int(len(output or "")),
                "output_words": int(output_words),
                "words_per_minute": (
                    float(output_words) / max(float(elapsed_seconds or 0.0) / 60.0, 1e-9)
                    if output_words > 0 and elapsed_seconds and elapsed_seconds > 0
                    else 0.0
                ),
            }
            samples.append(record)
            samples[:] = samples[-120:]

            path = self._rb_timing_store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"samples": samples}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # Timing telemetry must never break document generation.
            return

    def _rb_eta_speed_profile(self) -> dict[str, Any]:
        samples = []
        for rec in self._rb_get_timing_samples():
            try:
                wpm = float(rec.get("words_per_minute", 0.0) or 0.0)
                elapsed = float(rec.get("elapsed_seconds", 0.0) or 0.0)
                words = int(rec.get("output_words", 0) or 0)
                if wpm > 0 and elapsed >= 3.0 and words >= 20:
                    samples.append(wpm)
            except Exception:
                continue

        if samples:
            med = float(statistics.median(samples))
            low_wpm = max(3.0, med * 0.65)
            high_wpm = max(low_wpm + 1.0, med * 1.35)
            return {
                "low_wpm": low_wpm,
                "high_wpm": high_wpm,
                "basis": (
                    f"calibrated from {len(samples)} stored local Report Builder inference sample(s); "
                    f"median observed generation ≈ {med:.1f} words/min"
                ),
                "calibrated": True,
            }

        low = self._rb_float_env("ELI_REPORT_BUILDER_EST_LOW_WORDS_PER_MIN", 20.0)
        high = self._rb_float_env("ELI_REPORT_BUILDER_EST_HIGH_WORDS_PER_MIN", 70.0)
        low, high = min(low, high), max(low, high)
        return {
            "low_wpm": max(1.0, low),
            "high_wpm": max(2.0, high),
            "basis": (
                "heuristic only; no stored local Report Builder timing samples yet. "
                "The ETA will calibrate after real direct-broker generation calls."
            ),
            "calibrated": False,
        }

    def _rb_estimate_generation_plan(self, doc_type: str, *, review_enabled: bool) -> dict[str, Any]:
        contract = self._rb_contract(doc_type)
        speed = self._rb_eta_speed_profile()

        target_words = max(1, int(contract.get("target_words", 1) or 1))
        section_words = max(1, int(contract.get("section_words", 1) or 1))
        chunk_words = max(1, int(contract.get("chunk_words", 1) or 1))
        max_chunks = max(1, int(contract.get("max_chunks_per_section", 1) or 1))

        estimated_sections = max(1, int(round(target_words / max(section_words, 1))))
        section_calls = max(1, math.ceil(section_words / max(chunk_words, 1)))
        draft_calls = estimated_sections * section_calls
        review_calls = estimated_sections * 2 if review_enabled else 0
        blueprint_calls = 1
        polish_calls = 1

        # Word-volume is deliberately about generated-output workload,
        # not merely the final document size. Review/revision emits extra text.
        blueprint_words = max(600, min(3200, estimated_sections * 180))
        drafting_words = target_words
        review_words = int(target_words * 1.10) if review_enabled else 0
        polish_words = min(max(600, int(target_words * 0.16)), 9000)

        call_overhead = self._rb_float_env("ELI_REPORT_BUILDER_EST_CALL_OVERHEAD_MINUTES", 1.5)
        call_overhead = max(0.0, call_overhead)

        low_wpm = max(1.0, float(speed["low_wpm"]))
        high_wpm = max(low_wpm + 1.0, float(speed["high_wpm"]))

        def stage_range(words: int, calls: int) -> tuple[float, float]:
            fast = (float(words) / high_wpm) + (float(calls) * call_overhead * 0.65)
            slow = (float(words) / low_wpm) + (float(calls) * call_overhead * 1.35)
            return fast, slow

        blueprint_fast, blueprint_slow = stage_range(blueprint_words, blueprint_calls)
        draft_fast, draft_slow = stage_range(drafting_words, draft_calls)
        review_fast, review_slow = stage_range(review_words, review_calls) if review_enabled else (0.0, 0.0)
        polish_fast, polish_slow = stage_range(polish_words, polish_calls)

        full_fast = blueprint_fast + draft_fast + review_fast + polish_fast
        full_slow = blueprint_slow + draft_slow + review_slow + polish_slow

        return {
            "contract": contract,
            "speed": speed,
            "target_words": target_words,
            "section_words": section_words,
            "chunk_words": chunk_words,
            "max_chunks_per_section": max_chunks,
            "estimated_sections": estimated_sections,
            "estimated_calls": blueprint_calls + draft_calls + review_calls + polish_calls,
            "blueprint_range": self._rb_range_label(blueprint_fast, blueprint_slow),
            "draft_range": self._rb_range_label(draft_fast, draft_slow),
            "review_range": (
                self._rb_range_label(review_fast, review_slow)
                if review_enabled
                else "off"
            ),
            "polish_range": self._rb_range_label(polish_fast, polish_slow),
            "full_range": self._rb_range_label(full_fast, full_slow),
        }

    def _rb_last_blueprint_eta_lines(self, doc_type: str) -> list[str]:
        sections = getattr(self, "_rb_last_blueprint_sections", None)
        last_doc_type = getattr(self, "_rb_last_blueprint_doc_type", None)

        if not isinstance(sections, list) or not sections or last_doc_type != doc_type:
            return []

        review_enabled = bool(
            getattr(self, "_auto_review_check", None)
            and self._auto_review_check.isChecked()
        )
        estimate = self._rb_estimate_generation_plan(doc_type, review_enabled=review_enabled)
        speed = estimate["speed"]
        low_wpm = max(1.0, float(speed["low_wpm"]))
        high_wpm = max(low_wpm + 1.0, float(speed["high_wpm"]))

        lines = [
            "",
            "Last blueprint-calibrated section estimates from this session:",
        ]

        display_sections = sections[:18]
        contract = estimate["contract"]

        for i, section in enumerate(display_sections, start=1):
            title = str(section.get("title", "") or f"Section {i}")
            try:
                words = int(section.get("resolved_target_words", 0) or 0)
            except Exception:
                words = 0
            if words <= 0:
                try:
                    words = int(
                        self._rb_section_target_words(
                            section,
                            contract,
                            len(sections),
                        )
                    )
                except Exception:
                    words = int(estimate["section_words"])

            fast = float(words) / high_wpm
            slow = float(words) / low_wpm
            lines.append(
                f"- {title}: ≈ {words:,} words; section drafting ETA "
                f"{self._rb_range_label(fast, slow)} before review overhead."
            )

        if len(sections) > len(display_sections):
            lines.append(f"- … {len(sections) - len(display_sections)} additional section(s) omitted from preview.")

        return lines


'''

if "def _rb_estimate_generation_plan(self, doc_type: str, *, review_enabled: bool)" not in src:
    contract_anchor = "    def _rb_contract(self, doc_type: str) -> Dict[str, int]:"
    require(contract_anchor in src, "Could not find _rb_contract anchor for ETA helper insertion")
    src = src.replace(contract_anchor, ETA_HELPERS + contract_anchor, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Instrument _rb_infer() to record real timing samples
# ─────────────────────────────────────────────────────────────────────────────

m_infer = re.search(
    r"(?ms)^    def _rb_infer\(\n.*?^    def _rb_terms\(",
    src,
)
require(m_infer is not None, "Could not locate _rb_infer function surface")

infer_surface = m_infer.group(0)

if "self._rb_record_timing(stage, prompt, response or \"\", elapsed)" not in infer_surface:
    require(
        "        response = broker.infer(\n" in infer_surface,
        "Could not find broker.infer assignment inside _rb_infer",
    )
    infer_surface_new = infer_surface.replace(
        "        response = broker.infer(\n",
        "        started = time.perf_counter()\n"
        "        response = broker.infer(\n",
        1,
    )

    needle = (
        "        )\n"
        "        return self._rb_guard_generated_text"
    )
    require(
        needle in infer_surface_new,
        "Could not find _rb_infer return insertion point",
    )
    infer_surface_new = infer_surface_new.replace(
        needle,
        "        )\n"
        "        elapsed = max(0.0, time.perf_counter() - started)\n"
        "        self._rb_record_timing(stage, prompt, response or \"\", elapsed)\n"
        "        return self._rb_guard_generated_text",
        1,
    )

    src = src[:m_infer.start()] + infer_surface_new + src[m_infer.end():]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Store last blueprint sections so Generation Plan can expose per-section ETA
# ─────────────────────────────────────────────────────────────────────────────

blueprint_old = (
    "                sections = self._rb_parse_blueprint(blueprint_text)\n"
    "                if not sections:\n"
)

blueprint_new = (
    "                sections = self._rb_parse_blueprint(blueprint_text)\n"
    "                self._rb_last_blueprint_doc_type = doc_type\n"
    "                self._rb_last_blueprint_sections = sections\n"
    "                self._rb_last_blueprint_at = time.time()\n"
    "                if not sections:\n"
)

if blueprint_new not in src:
    require(blueprint_old in src, "Could not find blueprint parse block")
    src = src.replace(blueprint_old, blueprint_new, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Expand Generation Plan pane with runtime ETA / project scale
# ─────────────────────────────────────────────────────────────────────────────

summary_method_match = re.search(
    r"(?ms)^    def _build_prompt_plan_summary\(self, mode: str, raw_prompt: str\) -> str:\n.*?^    def _copy_preview_prompt\(",
    src,
)
require(summary_method_match is not None, "Could not locate _build_prompt_plan_summary method")

summary_surface = summary_method_match.group(0)

if "Estimated runtime before execution:" not in summary_surface:
    anchor_after_tokens = (
        "        approx_tokens = max(1, len(raw_prompt) // 4)\n"
    )
    require(anchor_after_tokens in summary_surface, "Could not find approx_tokens line in plan summary")
    inject_vars = (
        "        approx_tokens = max(1, len(raw_prompt) // 4)\n"
        "        eta = self._rb_estimate_generation_plan(\n"
        "            doc_type,\n"
        "            review_enabled=(review == \"on\"),\n"
        "        )\n"
        "        blueprint_eta_lines = self._rb_last_blueprint_eta_lines(doc_type)\n"
    )
    summary_surface = summary_surface.replace(anchor_after_tokens, inject_vars, 1)

    select_profile_anchor = (
        '            "Selected profile behavior:",\n'
    )
    require(select_profile_anchor in summary_surface, "Could not find Selected profile behavior insertion point")

    eta_block = (
        '            "Projected document scale:",\n'
        '            f"- Planned final-document floor: ≈ {eta[\'target_words\']:,} words.",\n'
        '            f"- Planned section floor: ≈ {eta[\'section_words\']:,} words per substantive section.",\n'
        '            f"- Continuation chunk target: ≈ {eta[\'chunk_words\']:,} words.",\n'
        '            f"- Maximum continuation chunks per section: {eta[\'max_chunks_per_section\']}.",\n'
        '            f"- Provisional section count before blueprint: ≈ {eta[\'estimated_sections\']}.",\n'
        '            f"- Estimated direct-broker inference passes: ≈ {eta[\'estimated_calls\']}.",\n'
        '            "",\n'
        '            "Estimated runtime before execution:",\n'
        '            f"- Full Report Builder run: {eta[\'full_range\']}.",\n'
        '            f"- Blueprint / structure pass: {eta[\'blueprint_range\']}.",\n'
        '            f"- Section drafting pass: {eta[\'draft_range\']}.",\n'
        '            f"- Internal review + revision pass: {eta[\'review_range\']}.",\n'
        '            f"- Final format polish / autosave pass: {eta[\'polish_range\']}.",\n'
        '            f"- ETA basis: {eta[\'speed\'][\'basis\']}",\n'
        '            *blueprint_eta_lines,\n'
        '            "",\n'
        '            "Selected profile behavior:",\n'
    )
    summary_surface = summary_surface.replace(select_profile_anchor, eta_block, 1)

    src = src[:summary_method_match.start()] + summary_surface + src[summary_method_match.end():]


# ─────────────────────────────────────────────────────────────────────────────
# 9. Write patched file and compile
# ─────────────────────────────────────────────────────────────────────────────

TARGET.write_text(src, encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except Exception as exc:
    TARGET.write_text(original, encoding="utf-8")
    raise SystemExit(f"PY_COMPILE_FAILED_BACKUP_RESTORED: {exc}")

notes = textwrap.dedent(f"""
    Phase 23 patch installed successfully.

    Target:
      {TARGET}

    Backup:
      {BACKUP}

    Features installed:
      1. Drag/drop files and folders into the Report Builder evidence list.
      2. Recursive supported-file ingest for dropped folders.
      3. Duplicate-path suppression and configurable drop file cap:
           ELI_REPORT_BUILDER_DROP_FILE_LIMIT
      4. Persisted Report Builder timing samples:
           artifacts/runtime/report_builder_timing_samples.json
      5. Generation Plan ETA panel:
           - target document scale
           - predicted section count
           - predicted direct-broker pass count
           - stage-by-stage ETA range
           - full run ETA range
      6. ETA calibration from real local Report Builder generation timing.
      7. Last-blueprint per-section ETA preview when a blueprint already exists in-session.
      8. _rb_infer() timing instrumentation without altering the Phase 21 direct-broker architecture.
""").strip() + "\n"

DIFF_HINT.write_text(notes, encoding="utf-8")

SUMMARY.write_text(textwrap.dedent(f"""
    # Phase 23 — Report Builder Drag-and-Drop + ETA Panel

    ## Result

    - PY_COMPILE_OK
    - Target patched: `{TARGET}`
    - Backup created: `{BACKUP}`

    ## Installed behavior

    ### Evidence drag/drop
    The Report Builder evidence list now accepts:
    - dropped individual files,
    - dropped folders,
    - recursive supported-file ingestion from folders.

    It de-duplicates already-loaded evidence paths and reports the number of files added/skipped in the bottom status bar.

    Default dropped-folder ingest cap:
    ```bash
    export ELI_REPORT_BUILDER_DROP_FILE_LIMIT=750
    ```

    ### Generation Plan ETA
    The Generation Plan panel now reports before execution:
    - planned final word floor,
    - planned section floor,
    - chunk continuation target,
    - maximum chunk count per section,
    - provisional section count,
    - estimated direct-broker inference pass count,
    - estimated total runtime,
    - estimated runtime for blueprint, section drafting, review/revision, and polish/autosave.

    ### ETA calibration
    Report Builder inference timing is now persisted to:

    `artifacts/runtime/report_builder_timing_samples.json`

    Before timing history exists, the ETA is labelled heuristic.
    After actual direct-broker calls complete, it recalibrates from local observed generation speed.

    ### Blueprint-calibrated section estimates
    Once a blueprint has been generated in-session, the Generation Plan panel can show section-level word and ETA estimates based on the last parsed blueprint.

    ## Architecture preserved

    This patch does **not** revert Phase 21.
    Full document generation still uses the direct broker path, not `self._eli(...)`.
""").strip() + "\n", encoding="utf-8")

print(SUMMARY.read_text(encoding="utf-8"))
