"""A real specification for a custom agent — objective, prompt, triggers, measures.

What a custom agent used to be: a `.py` file dropped in a directory, exec'd at
import, with a `name`, a `timeout_s`, and an optional free-text "persona". Nothing
recorded what the agent was FOR, nothing defined when it should fire, and nothing
could tell whether it worked. An agent you cannot evaluate is an agent you cannot
trust, improve, or debug — it either seems fine or it does not.

A spec fixes the four things that were missing:

  objective          one sentence on what this agent is responsible for. Required,
                     and checked for substance — "does stuff" is refused.
  system_prompt      the actual instruction text the model receives. Required.
  triggers           when it runs. An agent that fires on everything is not an
                     agent, it is overhead on every turn.
  success_criteria   how you would know it worked, as checks that can actually be
                     RUN against an output — not prose. This is what makes
                     `evaluate()` possible and what the wizard's test step uses.

Specs are data, not code. They are validated, hashed, and stored as JSON, so an
agent can be reviewed, diffed, signed and shared without executing anything.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

SPEC_VERSION = 1

TRIGGER_KEYWORD = "keyword"
TRIGGER_REGEX = "regex"
TRIGGER_ACTION = "action"
TRIGGER_ALWAYS = "always"
TRIGGER_KINDS = (TRIGGER_KEYWORD, TRIGGER_REGEX, TRIGGER_ACTION, TRIGGER_ALWAYS)

CHECK_CONTAINS = "contains"
CHECK_NOT_CONTAINS = "not_contains"
CHECK_REGEX = "regex"
CHECK_MIN_LENGTH = "min_length"
CHECK_MAX_LENGTH = "max_length"
CHECK_NON_EMPTY = "non_empty"
CHECK_JSON = "is_json"
CHECK_KINDS = (CHECK_CONTAINS, CHECK_NOT_CONTAINS, CHECK_REGEX, CHECK_MIN_LENGTH,
               CHECK_MAX_LENGTH, CHECK_NON_EMPTY, CHECK_JSON)

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")

# Text that parses as an objective but says nothing. Rejected so a spec cannot be
# waved through with placeholder content the author never filled in.
_PLACEHOLDERS = {
    "todo", "tbd", "n/a", "na", "none", "test", "testing", "asdf", "xxx",
    "does stuff", "does things", "helper", "helps", "agent", "my agent",
    "description", "objective", "placeholder", "lorem ipsum", "...",
}

MIN_OBJECTIVE_CHARS = 25
MIN_PROMPT_CHARS = 40


@dataclass
class Trigger:
    kind: str = TRIGGER_KEYWORD
    value: str = ""
    case_sensitive: bool = False

    def matches(self, text: str, action: str = "") -> bool:
        if self.kind == TRIGGER_ALWAYS:
            return True
        if self.kind == TRIGGER_ACTION:
            return str(action or "").upper() == self.value.upper()
        haystack = text if self.case_sensitive else str(text or "").lower()
        needle = self.value if self.case_sensitive else str(self.value or "").lower()
        if self.kind == TRIGGER_KEYWORD:
            return bool(needle) and needle in haystack
        if self.kind == TRIGGER_REGEX:
            try:
                return bool(re.search(self.value, text,
                                      0 if self.case_sensitive else re.IGNORECASE))
            except re.error:
                return False
        return False


@dataclass
class SuccessCheck:
    """One runnable assertion about an agent's output."""
    kind: str = CHECK_NON_EMPTY
    value: str = ""
    description: str = ""

    def run(self, output: str) -> Dict[str, Any]:
        text = str(output or "")
        ok, detail = False, ""
        try:
            if self.kind == CHECK_NON_EMPTY:
                ok = bool(text.strip())
                detail = "output is empty" if not ok else "output present"
            elif self.kind == CHECK_CONTAINS:
                ok = self.value.lower() in text.lower()
                detail = f"{'found' if ok else 'missing'}: {self.value!r}"
            elif self.kind == CHECK_NOT_CONTAINS:
                ok = self.value.lower() not in text.lower()
                detail = f"{'absent' if ok else 'present'}: {self.value!r}"
            elif self.kind == CHECK_REGEX:
                ok = bool(re.search(self.value, text, re.IGNORECASE))
                detail = f"pattern {self.value!r} {'matched' if ok else 'did not match'}"
            elif self.kind == CHECK_MIN_LENGTH:
                ok = len(text.strip()) >= int(self.value or 0)
                detail = f"length {len(text.strip())} vs minimum {self.value}"
            elif self.kind == CHECK_MAX_LENGTH:
                ok = len(text.strip()) <= int(self.value or 0)
                detail = f"length {len(text.strip())} vs maximum {self.value}"
            elif self.kind == CHECK_JSON:
                json.loads(text)
                ok, detail = True, "output parses as JSON"
            else:
                detail = f"unknown check kind {self.kind!r}"
        except json.JSONDecodeError as exc:
            ok, detail = False, f"not valid JSON: {exc.msg}"
        except Exception as exc:
            ok, detail = False, f"check failed: {exc}"
        return {"ok": ok, "kind": self.kind, "value": self.value,
                "description": self.description, "detail": detail}


@dataclass
class Example:
    """An input and what a good answer looks like. Drives evaluate()."""
    input: str = ""
    expect: List[SuccessCheck] = field(default_factory=list)
    note: str = ""


@dataclass
class AgentSpec:
    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    author: str = ""
    objective: str = ""
    system_prompt: str = ""
    triggers: List[Trigger] = field(default_factory=list)
    success_criteria: List[SuccessCheck] = field(default_factory=list)
    examples: List[Example] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    timeout_s: float = 8.0
    max_tokens: int = 512
    temperature: float = 0.4
    enabled: bool = False          # created off; enabling is a separate decision
    created: str = ""
    notes: str = ""

    # ── serialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["spec_version"] = SPEC_VERSION
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSpec":
        d = dict(data or {})
        d.pop("spec_version", None)
        triggers = [Trigger(**t) if isinstance(t, dict) else t
                    for t in (d.pop("triggers", None) or [])]
        criteria = [SuccessCheck(**c) if isinstance(c, dict) else c
                    for c in (d.pop("success_criteria", None) or [])]
        examples = []
        for e in (d.pop("examples", None) or []):
            if isinstance(e, dict):
                expect = [SuccessCheck(**c) if isinstance(c, dict) else c
                          for c in (e.get("expect") or [])]
                examples.append(Example(input=e.get("input", ""), expect=expect,
                                        note=e.get("note", "")))
            else:
                examples.append(e)
        known = {f for f in cls.__dataclass_fields__}
        d = {k: v for k, v in d.items() if k in known}
        return cls(triggers=triggers, success_criteria=criteria, examples=examples, **d)

    def content_hash(self) -> str:
        """Stable hash of the spec's meaning.

        Excludes fields that change without changing behaviour (created, enabled),
        so re-saving a spec does not invalidate a trust grant while a real edit does.
        """
        d = self.to_dict()
        d.pop("created", None)
        d.pop("enabled", None)
        return hashlib.sha256(
            json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    # ── behaviour ─────────────────────────────────────────────────────────────
    def should_run(self, user_input: str, action: str = "") -> bool:
        return any(t.matches(user_input, action) for t in self.triggers)

    def evaluate(self, output: str) -> Dict[str, Any]:
        """Score one output against the spec's success criteria."""
        results = [c.run(output) for c in self.success_criteria]
        passed = sum(1 for r in results if r["ok"])
        return {"ok": passed == len(results) and bool(results),
                "passed": passed, "total": len(results), "checks": results,
                "score": round(passed / len(results), 3) if results else 0.0}


# ── validation ─────────────────────────────────────────────────────────────────

def _is_placeholder(text: str) -> bool:
    t = re.sub(r"[^a-z ]", "", str(text or "").lower()).strip()
    return (not t) or t in _PLACEHOLDERS or len(set(t.replace(" ", ""))) <= 2


def validate(spec: AgentSpec) -> Dict[str, Any]:
    """Refuse specs that cannot produce a working, evaluable agent.

    Every rule here exists because its absence produced an agent that loaded and
    then did nothing useful: no objective to judge it by, a prompt too thin to
    steer anything, no trigger so it never ran (or ran on everything), or no
    criteria so nobody could tell whether it worked.
    """
    problems: List[str] = []
    warnings: List[str] = []

    if not _ID_RE.match(str(spec.id or "")):
        problems.append("id must be 3-40 characters: lowercase letters, digits and "
                        "underscores, starting with a letter.")
    if not str(spec.name or "").strip():
        problems.append("name is required.")

    obj = str(spec.objective or "").strip()
    if len(obj) < MIN_OBJECTIVE_CHARS:
        problems.append(f"objective must be at least {MIN_OBJECTIVE_CHARS} characters — "
                        f"say what this agent is responsible for.")
    elif _is_placeholder(obj):
        problems.append("objective looks like placeholder text. Describe what the agent "
                        "actually does.")

    prompt = str(spec.system_prompt or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        problems.append(f"system_prompt must be at least {MIN_PROMPT_CHARS} characters. "
                        f"This is the instruction the model actually receives.")
    elif _is_placeholder(prompt):
        problems.append("system_prompt looks like placeholder text.")

    if not spec.triggers:
        problems.append("at least one trigger is required — otherwise the agent never runs.")
    for i, t in enumerate(spec.triggers, 1):
        if t.kind not in TRIGGER_KINDS:
            problems.append(f"trigger {i}: unknown kind {t.kind!r}.")
        elif t.kind != TRIGGER_ALWAYS and not str(t.value or "").strip():
            problems.append(f"trigger {i}: a {t.kind} trigger needs a value.")
        if t.kind == TRIGGER_REGEX:
            try:
                re.compile(t.value)
            except re.error as exc:
                problems.append(f"trigger {i}: invalid regular expression ({exc}).")
    if any(t.kind == TRIGGER_ALWAYS for t in spec.triggers):
        warnings.append("An 'always' trigger runs this agent on every single turn, which "
                        "costs latency on turns it cannot help with.")

    if not spec.success_criteria:
        problems.append("at least one success criterion is required — without one there is "
                        "no way to tell whether the agent worked.")
    for i, c in enumerate(spec.success_criteria, 1):
        if c.kind not in CHECK_KINDS:
            problems.append(f"success criterion {i}: unknown check {c.kind!r}.")
        if c.kind in (CHECK_CONTAINS, CHECK_NOT_CONTAINS, CHECK_REGEX) and not c.value:
            problems.append(f"success criterion {i}: a {c.kind} check needs a value.")
        if c.kind == CHECK_REGEX:
            try:
                re.compile(c.value)
            except re.error as exc:
                problems.append(f"success criterion {i}: invalid regex ({exc}).")
        if c.kind in (CHECK_MIN_LENGTH, CHECK_MAX_LENGTH):
            try:
                int(c.value)
            except Exception:
                problems.append(f"success criterion {i}: {c.kind} needs a number.")

    if not spec.examples:
        warnings.append("No examples given, so the agent cannot be tested before it goes "
                        "live. Adding one input is usually enough to catch a broken prompt.")

    try:
        from eli.plugins.permissions import ALL_CAPABILITIES
        unknown = [p for p in spec.permissions if p not in ALL_CAPABILITIES]
        if unknown:
            problems.append(f"unknown permissions: {', '.join(unknown)}")
    except Exception:
        warnings.append("Could not check the permission names against this build's "
                        "capability list.")

    if not (0.1 <= float(spec.timeout_s) <= 300):
        problems.append("timeout_s must be between 0.1 and 300 seconds.")
    if not (0.0 <= float(spec.temperature) <= 2.0):
        problems.append("temperature must be between 0 and 2.")
    if int(spec.max_tokens) < 1:
        problems.append("max_tokens must be at least 1.")

    return {"ok": not problems, "problems": problems, "warnings": warnings}


def prefill_from_legacy_wizard(
    name_purpose: str,
    triggers_data: str,
    persona_output: str,
) -> dict:
    """Map the old three-question chat wizard into an AgentSpec-shaped dict."""
    raw_name = re.split(r"[—\-]", str(name_purpose or ""), maxsplit=1)[0].strip()
    slug = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    if not slug or len(slug) < 3:
        slug = "custom_agent"
    if len(slug) > 40:
        slug = slug[:40].rstrip("_")

    purpose = str(name_purpose or "").strip()
    objective = purpose if len(purpose) >= 25 else (
        f"Assist the user with {raw_name or 'custom tasks'} using focused, "
        f"evidence-grounded replies."
    )

    triggers_part = str(triggers_data or "")
    if triggers_part.lower().startswith("keywords:"):
        triggers_part = triggers_part.split(":", 1)[1]
    trigger_words = [
        w.strip().lower()
        for w in re.split(r"[,;]", triggers_part.replace(" ", ","))
        if len(w.strip()) > 2
    ]
    triggers = [{"kind": "keyword", "value": w} for w in trigger_words[:8]]
    if not triggers:
        triggers = [{"kind": "keyword", "value": slug.replace("_", " ")}]

    persona = str(persona_output or "concise, helpful, plain text").strip()
    system_prompt = (
        f"You are a specialist assistant for: {objective}\n\n"
        f"Output style: {persona}\n\n"
        "Stay inside what the user asked. Be concrete. Do not invent facts."
    )

    return {
        "id": slug,
        "name": raw_name or slug.replace("_", " ").title(),
        "objective": objective,
        "system_prompt": system_prompt,
        "triggers": triggers,
        "success_criteria": [
            {"kind": "non_empty"},
            {"kind": "min_length", "value": "40"},
        ],
        "permissions": ["model_access"],
        "timeout_s": 8.0,
        "max_tokens": 512,
        "temperature": 0.4,
    }


# ── storage ────────────────────────────────────────────────────────────────────

def specs_dir() -> Path:
    """Where agent specs live. In the DATA dir, never the installation — a packaged
    build mounts its own tree read-only."""
    import os
    override = os.environ.get("ELI_AGENT_SPECS_DIR")
    if override:
        return Path(override).expanduser()
    from eli.core.paths import data_dir
    return Path(data_dir()) / "agents"


def save_spec(spec: AgentSpec) -> Dict[str, Any]:
    check = validate(spec)
    if not check["ok"]:
        return {"ok": False, "problems": check["problems"], "warnings": check["warnings"]}
    if not spec.created:
        spec.created = time.strftime("%Y-%m-%dT%H:%M:%S")
    d = specs_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{spec.id}.agent.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(spec.to_json(), encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "path": str(path), "hash": spec.content_hash(),
            "problems": [], "warnings": check["warnings"]}


def load_spec(path: Any) -> Optional[AgentSpec]:
    try:
        return AgentSpec.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except Exception:
        return None


def load_spec_by_id(agent_id: str) -> Optional[AgentSpec]:
    """Load one saved spec by its id (filename stem)."""
    if not str(agent_id or "").strip():
        return None
    return load_spec(specs_dir() / f"{agent_id}.agent.json")


def list_specs() -> List[AgentSpec]:
    d = specs_dir()
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.agent.json")):
        spec = load_spec(f)
        if spec is not None:
            out.append(spec)
    return out


def delete_spec(agent_id: str) -> Dict[str, Any]:
    path = specs_dir() / f"{agent_id}.agent.json"
    if not path.is_file():
        return {"ok": False, "problems": [f"No spec for {agent_id!r}."]}
    path.unlink()
    return {"ok": True, "problems": []}


__all__ = [
    "AgentSpec", "Trigger", "SuccessCheck", "Example", "validate",
    "save_spec", "load_spec", "load_spec_by_id", "list_specs", "delete_spec", "specs_dir",
    "prefill_from_legacy_wizard",
    "TRIGGER_KINDS", "CHECK_KINDS", "SPEC_VERSION",
    "TRIGGER_KEYWORD", "TRIGGER_REGEX", "TRIGGER_ACTION", "TRIGGER_ALWAYS",
    "CHECK_CONTAINS", "CHECK_NOT_CONTAINS", "CHECK_REGEX", "CHECK_MIN_LENGTH",
    "CHECK_MAX_LENGTH", "CHECK_NON_EMPTY", "CHECK_JSON",
]
