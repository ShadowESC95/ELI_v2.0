#!/usr/bin/env python3
"""
Migrate diagnostic print() calls to log.debug() / log.error() across eli/.

Rules:
  - Only converts print() calls whose first string argument starts with '[' (bracket-tagged diagnostics).
  - print(..., file=sys.stderr) with a bracket tag → log.error(...)
  - All other print() calls (user-facing CLI, banners, input prompts) are LEFT ALONE.
  - Adds logger setup boilerplate to each modified file if not already present.
  - Idempotent: safe to run multiple times.

Files excluded from conversion (intentional user-facing output):
  - eli/cli/headless.py
  - eli/__main__.py
  - eli/tools/mic_diag.py
  - scripts/ and tests/ directories

Run from repo root:
    python3 scripts/migrate_prints_to_logger.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

PROJECT = Path(__file__).parent.parent
ELI_ROOT = PROJECT / "eli"

EXCLUDE_FILES = {
    "eli/cli/headless.py",
    "eli/__main__.py",
    "eli/tools/mic_diag.py",
}

LOGGER_IMPORT = "from eli.utils.log import get_logger"
LOGGER_SETUP = 'log = get_logger(__name__)'

LOGGER_BLOCK = f"{LOGGER_IMPORT}\n{LOGGER_SETUP}\n"

# Matches a complete single-line print(  ...  ) or print(\n...\n) call.
# We process the file as text and use a state machine for multi-line.

STDERR_RE = re.compile(r',\s*file\s*=\s*sys\.stderr\s*')


def has_bracket_tag(first_arg: str) -> bool:
    """Return True if the first string argument starts with a [ tag."""
    stripped = first_arg.strip().lstrip('f').lstrip("'\"").lstrip('f').strip('"\'')
    # Handle f"[TAG]..." or "[TAG]..." or f'[TAG]...' etc
    for quote in ('f"', "f'", '"', "'"):
        if first_arg.strip().startswith(quote):
            content = first_arg.strip()[len(quote):]
            return content.startswith('[')
    # Handle multi-line: look for [ in the first non-whitespace content
    return first_arg.strip().startswith('[') or '[' in first_arg[:20]


def extract_print_body(lines: list[str], start: int) -> tuple[int, str] | None:
    """
    Given lines and start index of a print( call, return (end_line_index, full_call_text).
    Returns None if it can't be parsed safely.
    """
    depth = 0
    body = []
    for i in range(start, min(start + 30, len(lines))):  # max 30 lines per print
        line = lines[i]
        body.append(line)
        depth += line.count('(') - line.count(')')
        if depth <= 0:
            return i, ''.join(body)
    return None  # unclosed or too complex


def logger_already_present(src: str) -> bool:
    return LOGGER_IMPORT in src or 'get_logger' in src or ("log = logging.getLogger" in src)


def add_logger_setup(src: str, filepath: Path) -> str:
    """Insert logger boilerplate after the last top-level import block."""
    lines = src.splitlines(keepends=True)

    # Find insertion point: after the last import line at module level
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(('import ', 'from ')) and not line.startswith(' '):
            last_import_idx = i

    if last_import_idx == -1:
        # No imports found, insert after module docstring or at top
        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip().startswith(('"""', "'''")):
                # Skip docstring
                for j in range(i + 1, len(lines)):
                    if '"""' in lines[j][1:] or "'''" in lines[j][1:]:
                        insert_at = j + 1
                        break
                break
    else:
        insert_at = last_import_idx + 1
        # If the import at last_import_idx is a multi-line import (open paren),
        # skip forward until the closing paren line.
        paren_depth = 0
        for k in range(last_import_idx, min(last_import_idx + 50, len(lines))):
            paren_depth += lines[k].count('(') - lines[k].count(')')
            if paren_depth <= 0:
                insert_at = k + 1
                break

    # Skip blank lines after imports
    while insert_at < len(lines) and lines[insert_at].strip() == '':
        insert_at += 1

    insertion = f"\n{LOGGER_BLOCK}\n"
    lines.insert(insert_at, insertion)
    return ''.join(lines)


def migrate_file(filepath: Path) -> tuple[int, int]:
    """
    Migrate diagnostic prints in a file.
    Returns (prints_converted, prints_skipped).
    """
    src = filepath.read_text(encoding='utf-8', errors='replace')
    lines = src.splitlines(keepends=True)

    converted = 0
    skipped = 0
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Find print( at any indentation
        m = re.match(r'^(\s*)print\(', line)
        if not m:
            new_lines.append(line)
            i += 1
            continue

        indent = m.group(1)

        # Extract full call
        result = extract_print_body(lines, i)
        if result is None:
            # Too complex, skip
            new_lines.append(line)
            i += 1
            skipped += 1
            continue

        end_idx, call_text = result

        # Determine if first arg has a bracket tag
        # Strip the "print(" prefix and trailing ")"
        inner = call_text.strip()
        if inner.startswith('print('):
            inner_args = inner[6:]  # remove 'print('
        else:
            new_lines.append(line)
            i += 1
            skipped += 1
            continue

        # Check first meaningful content after print(
        first_content = inner_args.strip()

        # Check for stderr
        is_stderr = bool(STDERR_RE.search(call_text))

        # Check bracket tag
        is_diagnostic = (
            first_content.startswith('[') or
            first_content.startswith('f"[') or
            first_content.startswith("f'[") or
            first_content.startswith('"[') or
            first_content.startswith("'[") or
            first_content.startswith('\n') and '[' in first_content[:30]
        )

        if not is_diagnostic:
            # Not a diagnostic print — leave alone
            for j in range(i, end_idx + 1):
                new_lines.append(lines[j])
            i = end_idx + 1
            skipped += 1
            continue

        # Convert: replace print( with log.debug( or log.error(
        log_fn = 'log.error' if is_stderr else 'log.debug'

        # Remove file=sys.stderr if present
        converted_call = re.sub(r',\s*file\s*=\s*sys\.stderr', '', call_text)
        # Remove flush=True if present (not valid for logger)
        converted_call = re.sub(r',\s*flush\s*=\s*True', '', converted_call)
        # Replace print( with log.debug( or log.error(
        converted_call = re.sub(r'^(\s*)print\(', rf'\1{log_fn}(', converted_call, count=1)

        new_lines.append(converted_call)
        converted += 1
        i = end_idx + 1

    new_src = ''.join(new_lines)

    if converted > 0:
        # Add logger setup if not already present
        if not logger_already_present(new_src):
            new_src = add_logger_setup(new_src, filepath)

    return new_src, converted, skipped


def should_skip(filepath: Path) -> bool:
    rel = str(filepath.relative_to(PROJECT)).replace('\\', '/')
    if rel in EXCLUDE_FILES:
        return True
    if any(part in ('tests', 'scripts', 'build', '__pycache__', 'packaging', 'training')
           for part in filepath.parts):
        return True
    return False


def main():
    print(f"{'DRY RUN — ' if DRY_RUN else ''}Migrating diagnostic prints in {ELI_ROOT}")
    print()

    files = sorted(ELI_ROOT.rglob('*.py'))
    total_converted = 0
    total_skipped = 0
    files_modified = 0

    for fp in files:
        if should_skip(fp):
            continue

        try:
            new_src, converted, skipped = migrate_file(fp)
        except Exception as e:
            print(f"  ERROR processing {fp.relative_to(PROJECT)}: {e}")
            continue

        if converted > 0:
            rel = fp.relative_to(PROJECT)
            print(f"  {rel}: {converted} converted, {skipped} skipped")
            total_converted += converted
            total_skipped += skipped
            files_modified += 1

            if not DRY_RUN:
                fp.write_text(new_src, encoding='utf-8')

    print()
    print(f"{'[DRY RUN] Would modify' if DRY_RUN else 'Modified'} {files_modified} files")
    print(f"  Converted: {total_converted} print() → log.debug()/log.error()")
    print(f"  Left alone: {total_skipped} (non-diagnostic or complex)")
    if DRY_RUN:
        print()
        print("Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
