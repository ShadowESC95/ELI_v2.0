#!/usr/bin/env python3
"""Extract an ELI fine-tuning dataset from stored conversations.

Consolidates the old models/extract_training_data*.py scripts into ONE parameterised,
model-agnostic extractor.

DESIGN — persona stays dynamic (do NOT bake it into the weights)
----------------------------------------------------------------
ELI's persona is dynamic, self-updating and lives in the RUNTIME (persona_updater +
overlay + memory brief). So this extractor trains only the STABLE layer — ELI's
*voice / manner* as expressed in its actual replies — and reads NOTHING that is state.

Two voice sources, BOTH reply-text only:
  * JSON conversation snapshots (artifacts/conversations/*.json), and
  * the `conversation_turns` table in user.sqlite3 (--from-db) — the full turn-level
    log (thousands of turns vs a few dozen snapshots).

What is DELIBERATELY NOT read (it lives in SQLite+FAISS and is retrieved fresh at
inference — baking it into weights would FREEZE it and kill the self-updating persona):
the `memories` table, `kg_entities`/`kg_relations`, `session_summaries`, `observations`,
`user_patterns`, profile, or any fixed persona system prompt. Exactly one table is read
in DB mode — `conversation_turns` (role, content) — and nothing else.

Usage:
  # richer: pull the turn log straight from the DB (voice only, state excluded)
  python training/extract_eli_dataset.py \
      --base-model Qwen/Qwen3-8B \
      --from-db artifacts/db/user.sqlite3 \
      --out training/datasets/eli_voice.jsonl
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys
from pathlib import Path

# Assistant turns matching these are NOT ELI's voice — they're bugs/leakage that have
# since been fixed (surfaced runtime errors, degenerate fragments, the world-room
# confabulation, raw shell/traceback bleed). Training on them would re-teach the model
# to emit them. Surgical on purpose: "Context window: 4096 tokens" (a legit SELF_REPORT
# line) does NOT match — only the actual error strings do. Disable with --keep-bad.
_BAD_REPLY_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"GGUF (streaming failed|unavailable)",
        r"exceeds?\s+context\s+window",
        r"Requested tokens \(",
        r"Traceback \(most recent call",
        r"\b\w+@\w+:[~/][^\s]*[$#]",      # shell prompt (user@host:path$) bleed
        r"Anomaly Room|Memory Archive",   # world-avatar rooms that leaked into chat
    )
]


def _is_bad_reply(text: str) -> bool:
    return any(p.search(text) for p in _BAD_REPLY_PATTERNS)

# JSON conversation layout: a list of {"source": "USER"|"ELI", "message": "..."}.
_DEFAULT_CONV_DIRS = [
    "artifacts/conversations",
    "eli/artifacts/conversations",
    "eli/gui/artifacts/conversations",
]


def _load_tokenizer(base_model: str):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(base_model)


def _norm_msgs(raw, min_reply_chars: int, drop_bad: bool = True) -> list:
    """raw: iterable of (role, text). Returns [{role, content}] with user/assistant only,
    dropping empty + degenerate-fragment + known-bad assistant turns. When a reply is
    dropped, its preceding user prompt is dropped too (it produced garbage), keeping the
    remaining conversation coherent."""
    msgs = []
    for role, text in raw:
        r = str(role or "").strip().lower()
        t = (text or "").strip()
        if not t:
            continue
        if r in ("user", "you"):
            msgs.append({"role": "user", "content": t})
        elif r in ("assistant", "eli"):
            bad = len(t) < max(1, min_reply_chars) or (drop_bad and _is_bad_reply(t))
            if bad:
                if msgs and msgs[-1]["role"] == "user":
                    msgs.pop()  # drop the prompt that produced the garbage reply
                continue
            msgs.append({"role": "assistant", "content": t})
    return msgs


def _tidy(msgs: list) -> list:
    """Make a turn list safe for ANY chat template: drop leading assistant turns and
    merge consecutive same-role turns (some templates reject non-alternating roles)."""
    out = []
    for m in msgs:
        if not out and m["role"] != "user":
            continue  # a conversation must open on the user
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + m["content"]
        else:
            out.append(dict(m))
    # must end on an assistant turn to be a useful (input→reply) example
    while out and out[-1]["role"] != "assistant":
        out.pop()
    return out


def _json_raw_pairs(conv):
    """Yield (role, text) from either supported JSON shape:
      * current: {"timestamp":..., "messages": [{"role","content"}, ...]}
      * legacy:  [{"source": "USER"|"ELI", "message": "..."}, ...]
    """
    if isinstance(conv, dict):
        for e in conv.get("messages", []):
            if isinstance(e, dict):
                yield (e.get("role"), e.get("content"))
    elif isinstance(conv, list):
        for e in conv:
            if isinstance(e, dict):
                yield (e.get("source") or e.get("role"), e.get("message") or e.get("content"))


def _json_message_lists(conv_dirs, min_reply_chars: int, drop_bad: bool = True) -> list:
    out = []
    for d in conv_dirs:
        if not Path(d).is_dir():
            continue
        for p in sorted(Path(d).glob("*.json")):
            try:
                conv = json.loads(p.read_text(encoding="utf-8"))
                msgs = _tidy(_norm_msgs(_json_raw_pairs(conv), min_reply_chars, drop_bad))
                if msgs:
                    out.append((p.name, msgs))
            except Exception as e:
                print(f"skip {p.name}: {e}", file=sys.stderr)
    return out


def _db_message_lists(db_paths, min_reply_chars: int, drop_bad: bool = True) -> list:
    """Pull conversation_turns grouped by session, in order. VOICE ONLY — reads exactly
    one table (conversation_turns: role, content). No memories/KG/state are touched."""
    out = []
    for db in db_paths:
        if not Path(db).is_file():
            print(f"skip db {db}: not found", file=sys.stderr)
            continue
        try:
            con = sqlite3.connect(db)
            sessions = [r[0] for r in con.execute(
                "select distinct session_id from conversation_turns order by session_id")]
            for sid in sessions:
                rows = con.execute(
                    "select role, content from conversation_turns "
                    "where session_id=? order by id", (sid,)).fetchall()
                msgs = _tidy(_norm_msgs(rows, min_reply_chars, drop_bad))
                if msgs:
                    out.append((f"{Path(db).name}:{sid}", msgs))
            con.close()
        except Exception as e:
            print(f"skip db {db}: {e}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract an ELI voice dataset (persona stays dynamic).")
    ap.add_argument("--base-model", default="Qwen/Qwen3-8B",
                    help="HF id/path whose chat template formats the examples (match the target model).")
    ap.add_argument("--out", default="training/datasets/eli_voice.jsonl")
    ap.add_argument("--from-db", nargs="*", default=None,
                    help="SQLite store(s) to pull conversation_turns from (voice only — no memories/KG/"
                         "state read). Far richer than the JSON snapshots. When given, the JSON dirs are "
                         "skipped unless --conv-dirs is also passed.")
    ap.add_argument("--conv-dirs", nargs="*", default=None,
                    help=f"JSON snapshot dirs (default: {_DEFAULT_CONV_DIRS}).")
    ap.add_argument("--min-turns", type=int, default=2, help="Skip conversations shorter than this.")
    ap.add_argument("--min-reply-chars", type=int, default=2,
                    help="Drop assistant turns shorter than this (kills degenerate '-'/'I.' fragments).")
    ap.add_argument("--system-mode", choices=["none", "voice"], default="none",
                    help="'none' = teach voice from replies only (recommended; keeps persona dynamic). "
                         "'voice' = prepend a SHORT stable voice tag (no memory/state).")
    ap.add_argument("--keep-bad", action="store_true",
                    help="Keep replies matching the bad-pattern filter (error leakage, confab, "
                         "shell/traceback bleed). Default OFF — those are bugs, not ELI's voice.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Count + sample without loading the tokenizer or writing output.")
    args = ap.parse_args()
    _drop_bad = not args.keep_bad

    # Source selection: DB if --from-db given (richer), else JSON dirs. Both if both passed.
    message_lists = []
    if args.from_db:
        message_lists += _db_message_lists(args.from_db, args.min_reply_chars, _drop_bad)
        if args.conv_dirs:
            message_lists += _json_message_lists(args.conv_dirs, args.min_reply_chars, _drop_bad)
    else:
        message_lists += _json_message_lists(args.conv_dirs or _DEFAULT_CONV_DIRS, args.min_reply_chars, _drop_bad)

    # Drop conversations below the turn floor up front.
    message_lists = [(lbl, m) for (lbl, m) in message_lists if len(m) >= args.min_turns]
    if not message_lists:
        print("No conversation data found (checked DB and/or JSON dirs).", file=sys.stderr)
        return 1

    if args.dry_run:
        turns = sum(len(m) for _, m in message_lists)
        repl = sum(1 for _, m in message_lists for x in m if x["role"] == "assistant")
        print(f"[dry-run] {len(message_lists)} conversations, {turns} turns "
              f"({repl} ELI replies). Source={'db' if args.from_db else 'json'}. No tokenizer loaded.")
        for lbl, m in message_lists[:2]:
            print(f"  e.g. {lbl}: {len(m)} turns | first reply: "
                  f"{next((x['content'][:70] for x in m if x['role']=='assistant'), '')!r}")
        return 0

    tok = _load_tokenizer(args.base_model)

    # A short, STABLE voice tag — manner only, no persona state. Used only with --system-mode voice.
    _VOICE_TAG = ("You are ELI: direct, dry, a little sardonic; transparent; first-person; never "
                  "corporate. State facts plainly; never claim an action you did not perform.")

    examples, skipped, seen = [], 0, set()
    for label, msgs in message_lists:
        if args.system_mode == "voice":
            msgs = [{"role": "system", "content": _VOICE_TAG}] + msgs
        try:
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        except Exception as e:
            skipped += 1
            print(f"skip {label}: {e}", file=sys.stderr)
            continue
        key = hash(text)
        if key in seen:  # dedup identical conversations across sources
            skipped += 1
            continue
        seen.add(key)
        examples.append({"text": text})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"✅ {len(examples)} examples → {out}  (skipped {skipped}; "
          f"source={'db' if args.from_db else 'json'}; memory-state injection: EXCLUDED; "
          f"system-mode={args.system_mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
