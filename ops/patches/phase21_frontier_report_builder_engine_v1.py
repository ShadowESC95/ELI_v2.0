#!/usr/bin/env python3
from __future__ import annotations

import datetime as _dt
import difflib
import pathlib
import py_compile
import re
import shutil
import sys

ROOT = pathlib.Path.cwd()
TARGET = ROOT / "eli/gui/labs_tab.py"
STAMP = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / f"ops/reports/phase21_frontier_report_builder_engine_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

SUMMARY = OUT / "SUMMARY.md"
BACKUP = OUT / "labs_tab.py.before_phase21_frontier_report_builder_engine_v1.bak"
DIFF = OUT / "labs_tab.phase21_frontier_report_builder_engine_v1.diff"


def die(message: str) -> None:
    raise SystemExit(message)


if not TARGET.exists():
    die(f"TARGET_MISSING: {TARGET}")

original = TARGET.read_text(encoding="utf-8")
shutil.copy2(TARGET, BACKUP)
patched = original


# ---------------------------------------------------------------------------
# Import normalisation. Idempotent.
# ---------------------------------------------------------------------------

def ensure_plain_import(src: str, module_name: str) -> str:
    if re.search(rf"(?m)^import\s+{re.escape(module_name)}(?:\s|$)", src):
        return src
    future = re.search(r"(?m)^from __future__ import annotations\s*$", src)
    if future:
        pos = future.end()
        return src[:pos] + f"\nimport {module_name}" + src[pos:]
    return f"import {module_name}\n" + src


for _module in ("json", "math", "os", "time"):
    patched = ensure_plain_import(patched, _module)

# Ensure typing members used by inserted methods exist.
typing_line = re.search(r"(?m)^from typing import ([^\n]+)$", patched)
if not typing_line:
    die("PATCH_ANCHOR_MISSING: from typing import ... line not found")

members = [item.strip() for item in typing_line.group(1).split(",") if item.strip()]
for member in ("Any", "Dict", "List", "Optional", "Tuple"):
    if member not in members:
        members.append(member)
patched = patched[:typing_line.start()] + "from typing import " + ", ".join(members) + patched[typing_line.end():]


# ---------------------------------------------------------------------------
# Frontier helper methods inserted before the existing outline parser.
# ---------------------------------------------------------------------------

helpers = r'''
    # ── Phase 21: frontier direct-broker Report Builder helpers ────────────
    #
    # Architectural rule:
    #   Internal Report Builder stage prompts must never be handed back to the
    #   ordinary ELI chat callback. That callback routes the prompt as user
    #   dialogue, which can turn a document-generation stage into an unrelated
    #   diagnostic/audit action. Report Builder generation is a dedicated local
    #   production engine and therefore calls the inference broker directly.

    _RB_SECTION_COMPLETE = "[[SECTION_COMPLETE]]"
    _RB_CONTINUE_SECTION = "[[CONTINUE_SECTION]]"

    _RB_CONTROL_POISON = (
        "NAME_SOURCE_AUDIT",
        "EXPLAIN_COGNITION_RUNTIME",
        "Router parsed:",
        "Cognition runtime:",
        "Memory and retrieval runtime:",
        "route_action",
        "result_action",
        "agents_used",
        "aggregated_confidence",
        "matched_by",
        '"action": "EXPLAIN_',
        "'action': 'EXPLAIN_",
        "[COGNITIVE]",
        "[AGENT:",
        "[GGUF][",
    )

    @staticmethod
    def _rb_word_count(text: str) -> int:
        return len(re.findall(r"\b[\w’'-]+\b", text or ""))

    @staticmethod
    def _rb_int_env(name: str, default: int) -> int:
        raw = str(os.environ.get(name, "") or "").strip()
        if not raw:
            return int(default)
        try:
            return int(raw)
        except Exception:
            return int(default)

    @staticmethod
    def _rb_float_env(name: str, default: float) -> float:
        raw = str(os.environ.get(name, "") or "").strip()
        if not raw:
            return float(default)
        try:
            return float(raw)
        except Exception:
            return float(default)

    def _rb_contract(self, doc_type: str) -> Dict[str, int]:
        # Finished-document and per-section targets. These are deliberately
        # large. The generator reaches them through continuation loops, not by
        # pretending a 16k-context model can emit a 100k-word dissertation in
        # one forward pass.
        defaults: Dict[str, Dict[str, int]] = {
            "Document": {
                "target_total_words": 6000,
                "target_section_words": 850,
                "chunk_goal_words": 1600,
                "section_cap": 14,
                "max_chunks_per_section": 6,
                "review_section_char_limit": 52000,
            },
            "Article": {
                "target_total_words": 8000,
                "target_section_words": 950,
                "chunk_goal_words": 1800,
                "section_cap": 14,
                "max_chunks_per_section": 7,
                "review_section_char_limit": 54000,
            },
            "Research Article": {
                "target_total_words": 14000,
                "target_section_words": 1300,
                "chunk_goal_words": 2400,
                "section_cap": 18,
                "max_chunks_per_section": 9,
                "review_section_char_limit": 60000,
            },
            "Review Article": {
                "target_total_words": 24000,
                "target_section_words": 1800,
                "chunk_goal_words": 3200,
                "section_cap": 24,
                "max_chunks_per_section": 12,
                "review_section_char_limit": 68000,
            },
            "Master's Thesis": {
                "target_total_words": 45000,
                "target_section_words": 2600,
                "chunk_goal_words": 4200,
                "section_cap": 30,
                "max_chunks_per_section": 16,
                "review_section_char_limit": 76000,
            },
            "PhD Dissertation": {
                "target_total_words": 100000,
                "target_section_words": 3800,
                "chunk_goal_words": 5600,
                "section_cap": 48,
                "max_chunks_per_section": 22,
                "review_section_char_limit": 84000,
            },
            "Peer-Review Paper": {
                "target_total_words": 12000,
                "target_section_words": 1200,
                "chunk_goal_words": 2200,
                "section_cap": 16,
                "max_chunks_per_section": 8,
                "review_section_char_limit": 58000,
            },
            "Literature Review": {
                "target_total_words": 30000,
                "target_section_words": 2100,
                "chunk_goal_words": 3600,
                "section_cap": 28,
                "max_chunks_per_section": 14,
                "review_section_char_limit": 72000,
            },
            "Research Proposal": {
                "target_total_words": 12000,
                "target_section_words": 1100,
                "chunk_goal_words": 2200,
                "section_cap": 20,
                "max_chunks_per_section": 8,
                "review_section_char_limit": 58000,
            },
            "Lab Report": {
                "target_total_words": 10000,
                "target_section_words": 1000,
                "chunk_goal_words": 2000,
                "section_cap": 16,
                "max_chunks_per_section": 8,
                "review_section_char_limit": 56000,
            },
            "Technical Report": {
                "target_total_words": 18000,
                "target_section_words": 1400,
                "chunk_goal_words": 2600,
                "section_cap": 22,
                "max_chunks_per_section": 10,
                "review_section_char_limit": 64000,
            },
            "Simulation Report": {
                "target_total_words": 22000,
                "target_section_words": 1600,
                "chunk_goal_words": 3000,
                "section_cap": 24,
                "max_chunks_per_section": 12,
                "review_section_char_limit": 68000,
            },
        }

        contract = dict(defaults.get(doc_type, defaults["Research Article"]))
        depth_name = self._depth_combo.currentText() if hasattr(self, "_depth_combo") else "Extended"
        depth_scale = {
            "Executive concise": 0.45,
            "Balanced": 0.75,
            "Extended": 1.0,
            "Maximal / examiner-ready": 1.35,
        }.get(depth_name, 1.0)
        external_scale = max(0.20, self._rb_float_env("ELI_REPORT_BUILDER_SCALE", 1.0))
        scale = depth_scale * external_scale

        for key in ("target_total_words", "target_section_words", "chunk_goal_words"):
            contract[key] = max(300, int(round(contract[key] * scale)))

        override_map = {
            "ELI_REPORT_BUILDER_TARGET_WORDS": "target_total_words",
            "ELI_REPORT_BUILDER_SECTION_WORDS": "target_section_words",
            "ELI_REPORT_BUILDER_CHUNK_WORDS": "chunk_goal_words",
            "ELI_REPORT_BUILDER_SECTION_CAP": "section_cap",
            "ELI_REPORT_BUILDER_MAX_CHUNKS_PER_SECTION": "max_chunks_per_section",
            "ELI_REPORT_BUILDER_REVIEW_SECTION_CHAR_LIMIT": "review_section_char_limit",
        }
        for env_name, key in override_map.items():
            value = self._rb_int_env(env_name, 0)
            if value > 0:
                contract[key] = value
        return contract

    def _rb_max_tokens(self, stage: str) -> int:
        # Default -1 is intentional: gguf_inference interprets <=0 as use the
        # dynamically available output window after counting the stage prompt.
        safe_stage = re.sub(r"[^A-Z0-9]+", "_", (stage or "DEFAULT").upper()).strip("_")
        stage_raw = os.environ.get(f"ELI_REPORT_BUILDER_MAX_TOKENS_{safe_stage}")
        generic_raw = os.environ.get("ELI_REPORT_BUILDER_MAX_TOKENS")
        raw = stage_raw if stage_raw not in (None, "") else generic_raw
        if raw in (None, ""):
            return -1
        try:
            parsed = int(str(raw).strip())
        except Exception:
            return -1
        return parsed if parsed != 0 else -1

    def _rb_guard_generated_text(self, stage: str, text: str, *, min_chars: int = 1) -> str:
        candidate = str(text or "").strip()
        if len(candidate) < max(1, int(min_chars)):
            raise RuntimeError(
                f"REPORT_BUILDER[{stage}] returned {len(candidate)} chars; minimum required is {min_chars}."
            )
        for poison in self._RB_CONTROL_POISON:
            if poison and poison in candidate:
                raise RuntimeError(
                    f"REPORT_BUILDER[{stage}] rejected control/runtime packet leakage: {poison!r}"
                )
        return candidate

    def _rb_infer(
        self,
        prompt: str,
        *,
        stage: str,
        temperature: float = 0.34,
        top_p: float = 0.92,
        min_chars: int = 1,
    ) -> str:
        from eli.cognition.inference_broker import get_broker

        broker = get_broker()
        if broker is None:
            raise RuntimeError("REPORT_BUILDER cannot acquire inference broker.")

        system = (
            "You are ELI's dedicated frontier document-generation engine. "
            "Follow the stage packet exactly. Do not answer as a conversational assistant. "
            "Do not emit routing metadata, runtime audits, control packets, agent packets, "
            "or meta-commentary. Generate only the requested planning, drafting, critique, "
            "revision, or integration artifact."
        )
        response = broker.infer(
            prompt,
            system=system,
            max_tokens=self._rb_max_tokens(stage),
            temperature=float(temperature),
            top_p=float(top_p),
            retry=True,
        )
        return self._rb_guard_generated_text(stage, response, min_chars=min_chars)

    @staticmethod
    def _rb_terms(*parts: str) -> List[str]:
        stop = {
            "about", "after", "again", "against", "along", "also", "among",
            "because", "before", "being", "between", "could", "document",
            "evidence", "from", "given", "into", "itself", "material",
            "section", "should", "source", "sources", "that", "their",
            "there", "these", "this", "those", "through", "under", "using",
            "which", "with", "within", "would", "write", "title", "intent",
        }
        seen = set()
        terms: List[str] = []
        blob = " ".join(str(part or "") for part in parts)
        for token in re.findall(r"[A-Za-zΑ-Ωα-ωΞχφµμ][A-Za-z0-9Α-Ωα-ωΞχφµμ_-]{2,}", blob):
            low = token.lower()
            if low in stop or low in seen:
                continue
            seen.add(low)
            terms.append(low)
        return terms[:64]

    @staticmethod
    def _rb_windows(text: str, *, width: int = 2800, overlap: int = 300) -> List[str]:
        raw = str(text or "")
        if not raw:
            return []
        width = max(700, int(width))
        overlap = max(0, min(int(overlap), width // 2))
        step = max(1, width - overlap)
        windows: List[str] = []
        for start in range(0, len(raw), step):
            window = raw[start:start + width].strip()
            if window:
                windows.append(window)
            if start + width >= len(raw):
                break
        return windows

    def _rb_evidence_packet(
        self,
        focus_title: str,
        focus_intent: str = "",
        *,
        sources: Optional[List[Dict[str, Any]]] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        source_rows = list(sources if sources is not None else self._sources)
        if not source_rows:
            return ""

        budget = int(
            max_chars
            if max_chars is not None
            else self._rb_int_env("ELI_REPORT_BUILDER_SECTION_EVIDENCE_CHARS", 36000)
        )
        budget = max(8000, budget)
        terms = self._rb_terms(focus_title, focus_intent)

        lines = [
            "=== SOURCE INVENTORY ===",
            "| File | Kind | Size KB |",
            "| --- | --- | ---: |",
        ]
        for source in source_rows:
            lines.append(
                f"| {source.get('name', 'unknown')} | {source.get('kind', 'unknown')} | "
                f"{float(source.get('bytes', 0) or 0) / 1024.0:.1f} |"
            )

        lines.extend([
            "",
            "=== RELEVANCE-SELECTED SOURCE EVIDENCE ===",
            f"FOCUS: {focus_title}",
            f"INTENT: {focus_intent or '(none)'}",
            f"SEARCH TERMS: {', '.join(terms) if terms else '(none extracted)'}",
        ])

        candidates: List[Dict[str, Any]] = []
        for source_index, source in enumerate(source_rows):
            name = str(source.get("name", "unknown"))
            kind = str(source.get("kind", "unknown"))
            preview = str(source.get("preview", "") or "")
            windows = self._rb_windows(preview)
            if not windows and preview:
                windows = [preview[:2800]]
            for window_index, window in enumerate(windows):
                low = window.lower()
                score = sum(low.count(term) for term in terms)
                if score <= 0 and window_index == 0:
                    score = 1
                if score <= 0:
                    continue
                candidates.append({
                    "score": int(score),
                    "source_index": int(source_index),
                    "window_index": int(window_index),
                    "name": name,
                    "kind": kind,
                    "text": window,
                })

        candidates.sort(key=lambda item: (item["score"], -item["window_index"]), reverse=True)
        used = len("\n".join(lines))
        per_source: Dict[str, int] = {}
        selected = 0

        for candidate in candidates:
            name = str(candidate["name"])
            if per_source.get(name, 0) >= 4:
                continue
            block = (
                f"\n--- {name} ({candidate['kind']}; relevance={candidate['score']}) ---\n"
                f"{str(candidate['text']).strip()}\n"
            )
            if used + len(block) > budget:
                continue
            lines.append(block.rstrip())
            used += len(block)
            per_source[name] = per_source.get(name, 0) + 1
            selected += 1

        if selected == 0:
            for source in source_rows[:6]:
                excerpt = str(source.get("preview", "") or "")[:2400].strip()
                if not excerpt:
                    continue
                block = (
                    f"\n--- {source.get('name', 'unknown')} ({source.get('kind', 'unknown')}; fallback) ---\n"
                    f"{excerpt}\n"
                )
                if used + len(block) > budget:
                    break
                lines.append(block.rstrip())
                used += len(block)

        return "\n".join(lines).strip()

    def _rb_blueprint_prompt(
        self,
        *,
        title: str,
        doc_type: str,
        discipline: str,
        brief: str,
        grade_hint: str,
        doc_spec_block: str,
        format_spec_block: str,
        quality_spec_block: str,
        acceptance_test_block: str,
        contract: Dict[str, int],
        evidence_packet: str,
    ) -> str:
        return "\n".join(part for part in [
            f"TASK: Design the full long-form generation blueprint for a {doc_type} in {discipline}.",
            f"GRADE MODIFIER: {grade_hint}" if grade_hint else "",
            "",
            "DOC-TYPE SPECIFICATION:",
            doc_spec_block,
            "",
            format_spec_block,
            "",
            quality_spec_block,
            "",
            f"TITLE: {title}",
            f"AUTHOR BRIEF:\n{brief}",
            "",
            "SCALE CONTRACT:",
            f"- Finished document target: approximately {contract['target_total_words']:,}+ words unless the evidence genuinely constrains a shorter result.",
            f"- Maximum top-level section count: {contract['section_cap']}.",
            f"- Normal substantive section floor: approximately {contract['target_section_words']:,}+ words.",
            "- Compact front/back-matter sections may be shorter when structurally correct.",
            "",
            "OUTPUT SCHEMA — obey exactly:",
            "SECTION | <ordinal> | <top-level heading text> | <section purpose and evidence obligations> | <suggested target words>",
            "SUBSECTION | <ordinal.parent> | <subheading text> | <subsection purpose>",
            "",
            "RULES:",
            "1. Output only SECTION and SUBSECTION schema lines. No prose introduction. No markdown table.",
            "2. Build a structure that genuinely matches the selected document mode, not a generic article template.",
            "3. Include enough sections to support the scale contract without padding.",
            "4. Section intents must identify evidence obligations or [source needed] where evidence is missing.",
            "5. Long academic modes should include the structure needed for defensible examiner-level work.",
            "",
            acceptance_test_block,
            "",
            evidence_packet,
        ] if part)

    @staticmethod
    def _rb_parse_blueprint(blueprint_text: str) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for raw in str(blueprint_text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if "|" in line:
                parts = [piece.strip() for piece in line.split("|")]
                tag = parts[0].upper() if parts else ""
                if tag == "SECTION" and len(parts) >= 4:
                    if current is not None:
                        sections.append(current)
                    target_words = 0
                    if len(parts) >= 5:
                        match = re.search(r"\d[\d,]*", parts[4])
                        if match:
                            try:
                                target_words = int(match.group(0).replace(",", ""))
                            except Exception:
                                target_words = 0
                    current = {
                        "ordinal": parts[1] if len(parts) > 1 else str(len(sections) + 1),
                        "title": parts[2] if len(parts) > 2 else "Untitled Section",
                        "intent": parts[3] if len(parts) > 3 else "",
                        "target_words": target_words,
                        "subsections": [],
                    }
                    continue
                if tag == "SUBSECTION" and current is not None and len(parts) >= 4:
                    current.setdefault("subsections", []).append({
                        "ordinal": parts[1],
                        "title": parts[2],
                        "intent": parts[3],
                    })
                    continue

            # Fallback for a model that ignored the strict schema but did emit
            # headings. Better to recover than to throw away a viable blueprint.
            heading = re.match(
                r"^\s*(?:#{1,4}\s+|(?:\d+\.|[IVX]+\.)\s+|Chapter\s+\d+[:\.]?\s+)(.+)$",
                line,
                re.IGNORECASE,
            )
            if heading:
                if current is not None:
                    sections.append(current)
                current = {
                    "ordinal": str(len(sections) + 1),
                    "title": heading.group(1).strip(),
                    "intent": "",
                    "target_words": 0,
                    "subsections": [],
                }
                continue
            if current is not None:
                current["intent"] = (str(current.get("intent", "")) + " " + line).strip()

        if current is not None:
            sections.append(current)
        return sections[:64]

    def _rb_section_target_words(
        self,
        section: Dict[str, Any],
        *,
        section_count: int,
        contract: Dict[str, int],
    ) -> int:
        title_low = str(section.get("title", "") or "").lower()
        target = max(
            int(contract["target_section_words"]),
            int(math.ceil(float(contract["target_total_words"]) / max(1, int(section_count)))),
            int(section.get("target_words", 0) or 0),
        )
        compact_terms = (
            "abstract", "acknowledgement", "acknowledgment", "references",
            "bibliography", "evidence ledger", "source coverage",
        )
        if any(term in title_low for term in compact_terms):
            return max(450, min(1400, target // 2))
        if "conclusion" in title_low or "limitations" in title_low:
            return max(900, int(round(target * 0.72)))
        return target

    @staticmethod
    def _rb_section_map(sections: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for section in sections:
            lines.append(
                f"- {section.get('ordinal', '?')}. {section.get('title', 'Untitled')}: "
                f"{section.get('intent', '')}"
            )
            for subsection in section.get("subsections", []) or []:
                lines.append(
                    f"  - {subsection.get('ordinal', '?')} {subsection.get('title', 'Untitled')}: "
                    f"{subsection.get('intent', '')}"
                )
        return "\n".join(lines)

    @staticmethod
    def _rb_section_brief(section: Dict[str, Any]) -> str:
        lines = [
            f"SECTION ORDINAL: {section.get('ordinal', '?')}",
            f"SECTION TITLE: {section.get('title', 'Untitled Section')}",
            f"SECTION INTENT: {section.get('intent', '')}",
        ]
        subsections = section.get("subsections", []) or []
        if subsections:
            lines.append("SUBSECTIONS TO COVER:")
            for subsection in subsections:
                lines.append(
                    f"- {subsection.get('ordinal', '?')} {subsection.get('title', 'Untitled')}: "
                    f"{subsection.get('intent', '')}"
                )
        return "\n".join(lines)

    def _rb_section_prompt(
        self,
        *,
        section: Dict[str, Any],
        all_sections: List[Dict[str, Any]],
        title: str,
        doc_type: str,
        grade_hint: str,
        doc_spec_block: str,
        format_spec_block: str,
        quality_spec_block: str,
        acceptance_test_block: str,
        target_words: int,
        chunk_goal_words: int,
        evidence_packet: str,
    ) -> str:
        return "\n".join(part for part in [
            f"TASK: Write a substantive top-level section for a {doc_type}.",
            f"GRADE MODIFIER: {grade_hint}" if grade_hint else "",
            "",
            f"DOCUMENT TITLE: {title}",
            "",
            "FULL DOCUMENT BLUEPRINT:",
            self._rb_section_map(all_sections),
            "",
            "SECTION TO WRITE NOW:",
            self._rb_section_brief(section),
            "",
            "DOC-TYPE SPECIFICATION:",
            doc_spec_block,
            "",
            format_spec_block,
            "",
            quality_spec_block,
            "",
            "GENERATION CONTRACT:",
            f"- Finished target for this section: at least ~{target_words:,} words unless structurally compact front/back matter.",
            f"- This call should attempt a substantial chunk of up to ~{chunk_goal_words:,} words while remaining coherent.",
            "- If the section is complete and has met target, end with [[SECTION_COMPLETE]].",
            "- If it needs continuation, end with [[CONTINUE_SECTION]].",
            "- The marker must be the final line. Do not explain it.",
            "",
            "WRITING RULES:",
            "1. Output starts with this section's heading in the target format.",
            "2. Do not write any other top-level section.",
            "3. Do not emit an outline, synopsis, placeholder, or compressed executive summary.",
            "4. Develop the argument, derivation, method, discussion, or evidence mapping expected of this section.",
            "5. Use supplied evidence where relevant. Use [source needed] or [assumption] exactly where required.",
            "6. Preserve mathematical and technical specificity where the evidence supports it.",
            "",
            acceptance_test_block,
            "",
            evidence_packet,
        ] if part)

    def _rb_continuation_prompt(
        self,
        *,
        section: Dict[str, Any],
        existing_section: str,
        title: str,
        doc_type: str,
        format_spec_block: str,
        quality_spec_block: str,
        target_words: int,
        chunk_goal_words: int,
        continuation_index: int,
        evidence_packet: str,
    ) -> str:
        current_words = self._rb_word_count(existing_section)
        tail = str(existing_section or "")[-16000:]
        return "\n".join(part for part in [
            f"TASK: Continue the same {doc_type} section without restarting it.",
            "",
            f"DOCUMENT TITLE: {title}",
            "",
            "SECTION BEING CONTINUED:",
            self._rb_section_brief(section),
            "",
            format_spec_block,
            "",
            quality_spec_block,
            "",
            "CONTINUATION CONTRACT:",
            f"- Current assembled section length: {current_words:,} words.",
            f"- Target floor for completion: {target_words:,} words.",
            f"- This is continuation chunk {continuation_index}.",
            f"- Continue for up to ~{chunk_goal_words:,} additional words if needed.",
            "- Do NOT recap or restart the section.",
            "- Do NOT repeat the heading unless grammatically required by a truncated prior chunk.",
            "- If complete and at/above target, end with [[SECTION_COMPLETE]].",
            "- Otherwise end with [[CONTINUE_SECTION]].",
            "",
            "EXISTING SECTION TAIL — continue directly after this:",
            tail or "(empty section body)",
            "",
            evidence_packet,
        ] if part)

    @staticmethod
    def _rb_strip_marker(text: str) -> Tuple[str, str]:
        raw = str(text or "").strip()
        if raw.endswith(_ReportTab._RB_SECTION_COMPLETE):
            return raw[:-len(_ReportTab._RB_SECTION_COMPLETE)].rstrip(), "complete"
        if raw.endswith(_ReportTab._RB_CONTINUE_SECTION):
            return raw[:-len(_ReportTab._RB_CONTINUE_SECTION)].rstrip(), "continue"
        return raw, ""

    def _rb_generate_section(
        self,
        *,
        section: Dict[str, Any],
        all_sections: List[Dict[str, Any]],
        title: str,
        doc_type: str,
        grade_hint: str,
        doc_spec_block: str,
        format_spec_block: str,
        quality_spec_block: str,
        acceptance_test_block: str,
        target_words: int,
        contract: Dict[str, int],
        evidence_packet: str,
        stage_prefix: str,
    ) -> str:
        first_prompt = self._rb_section_prompt(
            section=section,
            all_sections=all_sections,
            title=title,
            doc_type=doc_type,
            grade_hint=grade_hint,
            doc_spec_block=doc_spec_block,
            format_spec_block=format_spec_block,
            quality_spec_block=quality_spec_block,
            acceptance_test_block=acceptance_test_block,
            target_words=target_words,
            chunk_goal_words=int(contract["chunk_goal_words"]),
            evidence_packet=evidence_packet,
        )
        first = self._rb_infer(
            first_prompt,
            stage=f"{stage_prefix}_draft",
            temperature=0.34,
            min_chars=500,
        )
        body, marker = self._rb_strip_marker(first)
        assembled = body.strip()
        chunks_used = 1
        max_chunks = max(1, int(contract["max_chunks_per_section"]))

        while chunks_used < max_chunks:
            words = self._rb_word_count(assembled)
            if marker == "complete" and words >= target_words:
                break
            if marker not in {"complete", "continue"} and words >= target_words:
                break
            chunks_used += 1
            continuation_prompt = self._rb_continuation_prompt(
                section=section,
                existing_section=assembled,
                title=title,
                doc_type=doc_type,
                format_spec_block=format_spec_block,
                quality_spec_block=quality_spec_block,
                target_words=target_words,
                chunk_goal_words=int(contract["chunk_goal_words"]),
                continuation_index=chunks_used,
                evidence_packet=evidence_packet,
            )
            more = self._rb_infer(
                continuation_prompt,
                stage=f"{stage_prefix}_continue_{chunks_used}",
                temperature=0.32,
                min_chars=260,
            )
            continuation, marker = self._rb_strip_marker(more)
            if continuation:
                assembled = (assembled.rstrip() + "\n\n" + continuation.lstrip()).strip()
        return assembled.strip()

    def _rb_section_review_prompt(
        self,
        *,
        section: Dict[str, Any],
        section_text: str,
        doc_type: str,
        doc_spec_block: str,
        quality_spec_block: str,
        acceptance_test_block: str,
        evidence_packet: str,
    ) -> str:
        return "\n".join(part for part in [
            f"TASK: Perform a rigorous peer-review critique of one {doc_type} section.",
            "",
            "SECTION:",
            self._rb_section_brief(section),
            "",
            "DOC-TYPE SPECIFICATION:",
            doc_spec_block,
            "",
            quality_spec_block,
            "",
            "REVIEW RULES:",
            "1. Identify unsupported claims, shallow reasoning, repetition, structure drift, missing equations or methods where warranted, and export-format hazards.",
            "2. Distinguish evidence-backed claims from [source needed] claims.",
            "3. Return a specific revision agenda; do not rewrite the section yet.",
            "",
            acceptance_test_block,
            "",
            "SECTION DRAFT:",
            section_text,
            "",
            evidence_packet,
        ] if part)

    def _rb_section_revision_prompt(
        self,
        *,
        section: Dict[str, Any],
        section_text: str,
        critique: str,
        doc_type: str,
        format_spec_block: str,
        doc_spec_block: str,
        quality_spec_block: str,
        target_words: int,
        evidence_packet: str,
    ) -> str:
        return "\n".join(part for part in [
            f"TASK: Revise this {doc_type} section using the critique, returning the complete revised section only.",
            "",
            "SECTION:",
            self._rb_section_brief(section),
            f"TARGET FLOOR: retain substantive scale; aim for at least ~{target_words:,} words unless structurally compact front/back matter.",
            "",
            "DOC-TYPE SPECIFICATION:",
            doc_spec_block,
            "",
            format_spec_block,
            "",
            quality_spec_block,
            "",
            "CRITIQUE TO APPLY:",
            critique,
            "",
            "REVISION RULES:",
            "1. Preserve valid technical content and strengthen weak passages; do not compress the section into a summary.",
            "2. Remove hallucinated claims, fake citations, fake paths, and generic filler.",
            "3. Add [source needed] or [assumption] rather than inventing support.",
            "4. Output the revised section only, in the selected format.",
            "",
            "SECTION DRAFT TO REVISE:",
            section_text,
            "",
            evidence_packet,
        ] if part)

    def _rb_review_and_revise_section(
        self,
        *,
        section: Dict[str, Any],
        section_text: str,
        doc_type: str,
        format_spec_block: str,
        doc_spec_block: str,
        quality_spec_block: str,
        acceptance_test_block: str,
        target_words: int,
        contract: Dict[str, int],
        evidence_packet: str,
        stage_prefix: str,
    ) -> str:
        if len(section_text) > int(contract["review_section_char_limit"]):
            return section_text
        critique = self._rb_infer(
            self._rb_section_review_prompt(
                section=section,
                section_text=section_text,
                doc_type=doc_type,
                doc_spec_block=doc_spec_block,
                quality_spec_block=quality_spec_block,
                acceptance_test_block=acceptance_test_block,
                evidence_packet=evidence_packet,
            ),
            stage=f"{stage_prefix}_review",
            temperature=0.20,
            min_chars=180,
        )
        revised = self._rb_infer(
            self._rb_section_revision_prompt(
                section=section,
                section_text=section_text,
                critique=critique,
                doc_type=doc_type,
                format_spec_block=format_spec_block,
                doc_spec_block=doc_spec_block,
                quality_spec_block=quality_spec_block,
                target_words=target_words,
                evidence_packet=evidence_packet,
            ),
            stage=f"{stage_prefix}_revise",
            temperature=0.28,
            min_chars=500,
        )
        original_words = max(1, self._rb_word_count(section_text))
        revised_words = self._rb_word_count(revised)
        if revised_words < int(original_words * 0.60):
            return section_text
        return revised

    def _rb_global_polish_prompt(
        self,
        *,
        full_draft: str,
        doc_type: str,
        format_spec_block: str,
        doc_spec_block: str,
        quality_spec_block: str,
    ) -> str:
        return "\n".join([
            f"TASK: Perform a final whole-document integration polish for this {doc_type}.",
            "",
            "DOC-TYPE SPECIFICATION:",
            doc_spec_block,
            "",
            format_spec_block,
            "",
            quality_spec_block,
            "",
            "INTEGRATION RULES:",
            "1. Preserve scale. Do not compress this into a summary.",
            "2. Improve transitions, heading consistency, terminology continuity, and repeated-definition handling.",
            "3. Preserve technically substantive passages unless duplicated or contradicted.",
            "4. Do not add unsupported claims; use [source needed] where support is absent.",
            "5. Output the complete integrated document only.",
            "",
            "DRAFT TO INTEGRATE:",
            full_draft,
        ])

    def _rb_maybe_global_polish(
        self,
        *,
        full_draft: str,
        doc_type: str,
        format_spec_block: str,
        doc_spec_block: str,
        quality_spec_block: str,
    ) -> str:
        max_chars = max(12000, self._rb_int_env("ELI_REPORT_BUILDER_GLOBAL_POLISH_MAX_CHARS", 36000))
        if len(full_draft) > max_chars:
            return full_draft
        polished = self._rb_infer(
            self._rb_global_polish_prompt(
                full_draft=full_draft,
                doc_type=doc_type,
                format_spec_block=format_spec_block,
                doc_spec_block=doc_spec_block,
                quality_spec_block=quality_spec_block,
            ),
            stage="global_polish",
            temperature=0.24,
            min_chars=800,
        )
        original_words = max(1, self._rb_word_count(full_draft))
        polished_words = self._rb_word_count(polished)
        if polished_words < int(original_words * 0.70):
            return full_draft
        return polished

    def _validate_generated_report(
        self,
        *,
        final_text: str,
        doc_type: str,
        section_count: int,
        contract: Dict[str, int],
    ) -> Tuple[bool, str]:
        body = str(final_text or "").strip()
        if not body:
            return False, "final document is empty"
        for poison in self._RB_CONTROL_POISON:
            if poison in body:
                return False, f"control/runtime leakage remains in final document: {poison!r}"
        low = body.lower()
        if "the documents you've provided outline" in low and self._rb_word_count(body) < 2200:
            return False, "final output collapsed into a source-summary stub"
        words = self._rb_word_count(body)
        target = max(1, int(contract["target_total_words"]))
        floor = max(1500, int(round(target * 0.55)))
        if words < floor:
            return False, (
                f"final document has {words:,} words; fail-closed floor for {doc_type} is "
                f"{floor:,} words from configured target {target:,}"
            )
        if section_count >= 3:
            heading_count = len(re.findall(r"(?m)^\s*(?:#{1,4}\s+|\\(?:chapter|section|subsection)\{)", body))
            if heading_count < max(2, section_count // 3):
                return False, "final document lost expected section-heading structure"
        return True, f"{words:,} words; configured target {target:,}"

    def _rb_manifest_path(self, title: str) -> Path:
        root = Path("artifacts/documents")
        root.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title.strip() or "eli_report").strip("_") or "eli_report"
        return root / f"{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.generation_manifest.json"

    def _rb_write_manifest(
        self,
        *,
        title: str,
        doc_type: str,
        target_format: str,
        contract: Dict[str, int],
        sections: List[Dict[str, Any]],
        final_text: str,
        validation_ok: bool,
        validation_detail: str,
        saved_path: Optional[Path],
        elapsed_seconds: float,
    ) -> Optional[Path]:
        try:
            path = self._rb_manifest_path(title)
            payload = {
                "kind": "eli_report_builder_frontier_manifest_v1",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "title": title,
                "document_type": doc_type,
                "target_format": target_format,
                "contract": contract,
                "sections": sections,
                "final_chars": len(final_text or ""),
                "final_words": self._rb_word_count(final_text or ""),
                "validation_ok": bool(validation_ok),
                "validation_detail": validation_detail,
                "saved_document": str(saved_path) if saved_path else None,
                "elapsed_seconds": round(float(elapsed_seconds), 3),
                "max_tokens_policy": "stage override env > ELI_REPORT_BUILDER_MAX_TOKENS > -1 auto/context-aware",
            }
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return path
        except Exception:
            return None
'''

parser_anchor = re.search(r"(?m)^    @staticmethod\n    def _parse_outline\(", patched)
if not parser_anchor:
    die("PATCH_ANCHOR_MISSING: existing _parse_outline method not found")
if "def _rb_contract(" not in patched:
    patched = patched[:parser_anchor.start()] + helpers.rstrip() + "\n\n" + patched[parser_anchor.start():]


# ---------------------------------------------------------------------------
# Replace full report generation method.
# ---------------------------------------------------------------------------

new_draft_method = r'''
    def _draft_full_with_eli(self):
        # Frontier direct-broker, continuation-based, fail-closed pipeline.
        if self._draft_running:
            self._status.setText("Draft pipeline already running.")
            return

        title_snapshot = self._title.text().strip() or "eli_report"
        doc_type = self._template_combo.currentText()
        target_format = self._target_format_combo.currentText()
        discipline = self._discipline.text().strip() or "general academic"
        brief = self._abstract.toPlainText().strip() or "(no brief provided)"
        grade = self._grade_combo.currentText()
        grade_hint = self._GRADE_HINTS.get(grade, "")
        spec = self._doc_spec(doc_type)
        fmt = self._format_spec(target_format)
        doc_spec_block = self._doc_spec_block(spec)
        format_spec_block = self._format_spec_block(fmt, target_format)
        quality_spec_block = self._quality_spec_block()
        acceptance_test_block = self._acceptance_test_block()
        contract = self._rb_contract(doc_type)
        sources_snapshot = [dict(source) for source in self._sources]
        run_review = bool(self._auto_review_check.isChecked()) if hasattr(self, "_auto_review_check") else True
        autosave = bool(self._autosave_check.isChecked()) if hasattr(self, "_autosave_check") else True

        def _set_status(message: str) -> None:
            try:
                self._status_sig.emit(message)
            except Exception:
                pass

        def _set_editor(text: str) -> None:
            try:
                self._editor_sig.emit(text)
            except Exception:
                pass

        self._draft_running = True
        _set_status(
            f"ELI Report Builder [frontier direct-broker]: blueprinting {doc_type}; "
            f"target≈{contract['target_total_words']:,}+ words; output budget=auto/context-aware unless overridden."
        )

        def _run_pipeline() -> None:
            started = time.perf_counter()
            saved_path: Optional[Path] = None
            sections: List[Dict[str, Any]] = []
            final = ""
            validation_ok = False
            validation_detail = "pipeline did not reach validation"

            try:
                outline_evidence = self._rb_evidence_packet(
                    title_snapshot,
                    brief,
                    sources=sources_snapshot,
                    max_chars=self._rb_int_env("ELI_REPORT_BUILDER_OUTLINE_EVIDENCE_CHARS", 48000),
                )
                blueprint_prompt = self._rb_blueprint_prompt(
                    title=title_snapshot,
                    doc_type=doc_type,
                    discipline=discipline,
                    brief=brief,
                    grade_hint=grade_hint,
                    doc_spec_block=doc_spec_block,
                    format_spec_block=format_spec_block,
                    quality_spec_block=quality_spec_block,
                    acceptance_test_block=acceptance_test_block,
                    contract=contract,
                    evidence_packet=outline_evidence,
                )
                blueprint_text = self._rb_infer(
                    blueprint_prompt,
                    stage="blueprint",
                    temperature=0.22,
                    min_chars=180,
                )
                sections = self._rb_parse_blueprint(blueprint_text)[: int(contract["section_cap"])]
                if not sections:
                    _set_editor(blueprint_text)
                    validation_detail = "blueprint was not parseable into SECTION/SUBSECTION rows"
                    _set_status(f"REPORT_BUILDER FAIL-CLOSED: {validation_detail}. Raw blueprint shown.")
                    return

                assembled_sections: List[str] = []
                for index, section in enumerate(sections, 1):
                    target_words = self._rb_section_target_words(
                        section,
                        section_count=len(sections),
                        contract=contract,
                    )
                    section["resolved_target_words"] = target_words
                    focus = (
                        f"{section.get('title', '')}\n{section.get('intent', '')}\n"
                        + "\n".join(
                            f"{sub.get('title', '')} {sub.get('intent', '')}"
                            for sub in section.get("subsections", []) or []
                        )
                    )
                    evidence_packet = self._rb_evidence_packet(
                        str(section.get("title", "")),
                        focus,
                        sources=sources_snapshot,
                    )
                    _set_status(
                        f"ELI Report Builder: drafting section {index}/{len(sections)} — "
                        f"{section.get('title', 'Untitled')} | target≈{target_words:,} words"
                    )
                    section_text = self._rb_generate_section(
                        section=section,
                        all_sections=sections,
                        title=title_snapshot,
                        doc_type=doc_type,
                        grade_hint=grade_hint,
                        doc_spec_block=doc_spec_block,
                        format_spec_block=format_spec_block,
                        quality_spec_block=quality_spec_block,
                        acceptance_test_block=acceptance_test_block,
                        target_words=target_words,
                        contract=contract,
                        evidence_packet=evidence_packet,
                        stage_prefix=f"section_{index}",
                    )
                    if run_review:
                        _set_status(
                            f"ELI Report Builder: reviewing/revising section {index}/{len(sections)} — "
                            f"{section.get('title', 'Untitled')}"
                        )
                        section_text = self._rb_review_and_revise_section(
                            section=section,
                            section_text=section_text,
                            doc_type=doc_type,
                            format_spec_block=format_spec_block,
                            doc_spec_block=doc_spec_block,
                            quality_spec_block=quality_spec_block,
                            acceptance_test_block=acceptance_test_block,
                            target_words=target_words,
                            contract=contract,
                            evidence_packet=evidence_packet,
                            stage_prefix=f"section_{index}",
                        )
                    assembled_sections.append(section_text.strip())
                    partial = "\n\n".join(block for block in assembled_sections if block).strip()
                    _set_editor(partial)

                final = "\n\n".join(block for block in assembled_sections if block).strip()
                _set_status("ELI Report Builder: attempting final integration polish when context-safe…")
                final = self._rb_maybe_global_polish(
                    full_draft=final,
                    doc_type=doc_type,
                    format_spec_block=format_spec_block,
                    doc_spec_block=doc_spec_block,
                    quality_spec_block=quality_spec_block,
                )
                validation_ok, validation_detail = self._validate_generated_report(
                    final_text=final,
                    doc_type=doc_type,
                    section_count=len(sections),
                    contract=contract,
                )
                _set_editor(final)

                if not validation_ok:
                    _set_status(
                        f"REPORT_BUILDER FAIL-CLOSED: {validation_detail}. "
                        "Draft retained in editor; not autosaved as a completed document."
                    )
                    return

                if autosave:
                    saved_path = self._autosave_report(
                        final,
                        title=title_snapshot,
                        target_format=target_format,
                    )
                elapsed = time.perf_counter() - started
                manifest_path = self._rb_write_manifest(
                    title=title_snapshot,
                    doc_type=doc_type,
                    target_format=target_format,
                    contract=contract,
                    sections=sections,
                    final_text=final,
                    validation_ok=validation_ok,
                    validation_detail=validation_detail,
                    saved_path=saved_path,
                    elapsed_seconds=elapsed,
                )
                saved_note = f" Saved: {saved_path}" if saved_path else ""
                manifest_note = f" Manifest: {manifest_path}" if manifest_path else ""
                _set_status(
                    f"ELI Report Builder delivered {self._rb_word_count(final):,} words "
                    f"across {len(sections)} sections for {doc_type}. "
                    f"{validation_detail}.{saved_note}{manifest_note}"
                )
            except Exception as exc:
                elapsed = time.perf_counter() - started
                if final:
                    _set_editor(final)
                _set_status(f"REPORT_BUILDER FAIL-CLOSED after {elapsed:.1f}s: {exc}")
            finally:
                self._draft_running = False

        threading.Thread(
            target=_run_pipeline,
            name="labs-frontier-report-builder",
            daemon=True,
        ).start()
'''

draft_pattern = re.compile(
    r"(?ms)^    def _draft_full_with_eli\(self\):.*?(?=^    def _ask_eli_expand_selection\(self\):)"
)
if not draft_pattern.search(patched):
    die("PATCH_ANCHOR_MISSING: _draft_full_with_eli method block not found")
patched, n = draft_pattern.subn(lambda _m: new_draft_method.rstrip() + "\n\n", patched, count=1)
if n != 1:
    die(f"PATCH_COUNT_BAD: _draft_full_with_eli replacement count={n}")


# ---------------------------------------------------------------------------
# Replace manual expand and manual critique so they also bypass self._eli.
# ---------------------------------------------------------------------------

new_expand_method = r'''
    def _ask_eli_expand_selection(self):
        cursor = self._editor.textCursor()
        selected = cursor.selectedText()
        if not selected:
            QMessageBox.information(
                self, "Select text",
                "Highlight a section heading or paragraph to expand."
            )
            return
        prompt = self._build_expand_prompt(selected)
        self._status.setText(
            f"ELI expanding selection through direct report broker… "
            f"({len(prompt):,} chars / ~{len(prompt)//4:,} prompt tokens)"
        )
        try:
            response = self._rb_infer(
                prompt,
                stage="manual_expand",
                temperature=0.34,
                min_chars=120,
            )
        except Exception as exc:
            QMessageBox.warning(self, "ELI Report Builder error", str(exc))
            return
        cursor.insertText(response)
        self._status.setText(f"Inserted {len(response):,} chars at cursor.")
'''

expand_pattern = re.compile(
    r"(?ms)^    def _ask_eli_expand_selection\(self\):.*?(?=^    def _ask_eli_critique\(self\):)"
)
if not expand_pattern.search(patched):
    die("PATCH_ANCHOR_MISSING: _ask_eli_expand_selection method block not found")
patched, n = expand_pattern.subn(lambda _m: new_expand_method.rstrip() + "\n\n", patched, count=1)
if n != 1:
    die(f"PATCH_COUNT_BAD: _ask_eli_expand_selection replacement count={n}")

new_critique_method = r'''
    def _ask_eli_critique(self):
        draft = self._editor.toPlainText().strip()
        if not draft:
            QMessageBox.information(self, "No draft", "Generate or paste a draft first.")
            return
        prompt = self._build_critique_prompt(draft)
        self._status.setText(
            f"ELI preparing peer-review critique through direct report broker… "
            f"({len(prompt):,} chars / ~{len(prompt)//4:,} prompt tokens)"
        )
        try:
            response = self._rb_infer(
                prompt,
                stage="manual_critique",
                temperature=0.22,
                min_chars=180,
            )
        except Exception as exc:
            QMessageBox.warning(self, "ELI Report Builder error", str(exc))
            return
        existing = self._editor.toPlainText().rstrip()
        critique_block = "\n\n---\n\n## Peer-Review Critique\n\n" + response.strip() + "\n"
        self._editor.setPlainText(existing + critique_block)
        self._status.setText(f"Peer-review critique appended ({len(response):,} chars).")
'''

critique_pattern = re.compile(
    r"(?ms)^    def _ask_eli_critique\(self\):.*?(?=^    def _export\(self, kind: str\):)"
)
if not critique_pattern.search(patched):
    die("PATCH_ANCHOR_MISSING: _ask_eli_critique method block not found")
patched, n = critique_pattern.subn(lambda _m: new_critique_method.rstrip() + "\n\n", patched, count=1)
if n != 1:
    die(f"PATCH_COUNT_BAD: _ask_eli_critique replacement count={n}")


# ---------------------------------------------------------------------------
# Sanity checks before write.
# ---------------------------------------------------------------------------

required_markers = [
    "def _rb_contract(",
    "def _rb_infer(",
    "def _rb_parse_blueprint(",
    "def _rb_generate_section(",
    "def _validate_generated_report(",
    "REPORT_BUILDER FAIL-CLOSED",
    "labs-frontier-report-builder",
    "ELI_REPORT_BUILDER_MAX_TOKENS",
    "\"Master's Thesis\": {",
    "\"PhD Dissertation\": {",
]
missing = [marker for marker in required_markers if marker not in patched]
if missing:
    die("PATCH_SANITY_MISSING_MARKERS: " + repr(missing))

draft_start = patched.index("    def _draft_full_with_eli(self):")
export_start = patched.index("    def _export(self, kind: str):", draft_start)
full_draft_surface = patched[draft_start:export_start]
if "self._eli(" in full_draft_surface:
    die("PATCH_SANITY_FAIL: self._eli(...) remains inside the full Report Builder generation surface")

TARGET.write_text(patched, encoding="utf-8")
try:
    py_compile.compile(str(TARGET), doraise=True)
    compile_status = "PY_COMPILE_OK"
except Exception as exc:
    shutil.copy2(BACKUP, TARGET)
    die(f"PY_COMPILE_FAILED_BACKUP_RESTORED: {exc}")

DIFF.write_text(
    "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile="eli/gui/labs_tab.py.before_phase21",
            tofile="eli/gui/labs_tab.py.after_phase21",
        )
    ),
    encoding="utf-8",
)

summary = f'''# Phase 21 Frontier Report Builder Engine v1

Generated: {_dt.datetime.now().isoformat(timespec="seconds")}
Root: `{ROOT}`
Target: `{TARGET}`

## Result

- {compile_status}
- Backup: `{BACKUP}`
- Diff: `{DIFF}`

## Architectural fault fixed

The old Report Builder passed outline, section, polish, critique, and revision prompts through
`self._eli(...)`. In the failed Master's Thesis run, those internal prompts re-entered the ordinary
chat/router/cognition pipeline. The log showed the revision prompt being parsed as
`NAME_SOURCE_AUDIT`, then a tiny source-summary artefact was written instead of a thesis.
This patch removes that fault from the Report Builder generation path.

## Engine installed

1. Full drafting now calls the single inference broker directly.
2. Default Report Builder generation budget is `max_tokens=-1`, which delegates to GGUF's
   context-aware remaining-output calculation instead of a tiny 128/512-style cap.
3. Large generation contracts exist for every Report Builder document mode:
   - Document
   - Article
   - Research Article
   - Review Article
   - Master's Thesis
   - PhD Dissertation
   - Peer-Review Paper
   - Literature Review
   - Research Proposal
   - Lab Report
   - Technical Report
   - Simulation Report
4. The engine blueprint step emits strict `SECTION | ...` and `SUBSECTION | ...` rows.
5. Each section receives relevance-selected source evidence, not a blind all-source dump.
6. Each substantive section can continue through multiple broker calls using:
   - `[[CONTINUE_SECTION]]`
   - `[[SECTION_COMPLETE]]`
7. Internal review is section-local. It no longer attempts a giant final "revise this whole thesis"
   pass that risks compressing a long document into a summary.
8. Whole-document polish only runs when context-safe.
9. Completed autosave fails closed if output collapses into a stub, control/audit packet, or an
   undersized pseudo-document.
10. A generation manifest is written alongside completed autosaved documents.

## Default scale contracts

- Master's Thesis: ~45,000+ words
- PhD Dissertation: ~100,000+ words
- Literature Review: ~30,000+ words
- Review Article: ~24,000+ words
- Simulation Report: ~22,000+ words
- Technical Report: ~18,000+ words

## Optional runtime overrides

```bash
export ELI_REPORT_BUILDER_MAX_TOKENS=-1
export ELI_REPORT_BUILDER_SCALE=1.0
export ELI_REPORT_BUILDER_TARGET_WORDS=50000
export ELI_REPORT_BUILDER_SECTION_WORDS=3000
export ELI_REPORT_BUILDER_CHUNK_WORDS=4500
export ELI_REPORT_BUILDER_MAX_CHUNKS_PER_SECTION=16
export ELI_REPORT_BUILDER_SECTION_EVIDENCE_CHARS=36000
export ELI_REPORT_BUILDER_OUTLINE_EVIDENCE_CHARS=48000
export ELI_REPORT_BUILDER_GLOBAL_POLISH_MAX_CHARS=36000
```

Leave `ELI_REPORT_BUILDER_TARGET_WORDS` unset to use the selected document mode's default.
'''
SUMMARY.write_text(summary, encoding="utf-8")
print(summary)
