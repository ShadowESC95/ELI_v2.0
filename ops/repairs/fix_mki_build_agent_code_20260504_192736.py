from pathlib import Path
import ast
import py_compile
import shutil
import subprocess
import time
import traceback

ROOT = Path.cwd()
MKI = ROOT / "eli/gui/eli_pro_audio_gui_MKI.py"
REL = "eli/gui/eli_pro_audio_gui_MKI.py"
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.fix_mki_build_agent_code"
BACKUP.mkdir(parents=True, exist_ok=True)

def backup_file(path: Path):
    dst = BACKUP / path.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)
    print(f"BACKUP {path.relative_to(ROOT)} -> {dst}")

def compile_rc(path: Path):
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {path.relative_to(ROOT)}")
        return 0
    except py_compile.PyCompileError as exc:
        err = exc.exc_value
        print(f"COMPILE_BAD line={getattr(err, 'lineno', None)} msg={err}")
        return 1
    except Exception as exc:
        print(f"COMPILE_BAD_UNKNOWN {type(exc).__name__}: {exc}")
        return 2

def git_head_text() -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{REL}"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"GIT_SHOW_RC={proc.returncode}")
    if proc.returncode != 0:
        print(proc.stderr)
        raise RuntimeError("Could not read donor MKI from git HEAD")
    return proc.stdout

def get_donor_method_chunk(donor: str, method_name: str):
    tree = ast.parse(donor)
    lines = donor.splitlines(keepends=True)

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        body = cls.body
        for i, node in enumerate(body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
                start = node.lineno
                if node.decorator_list:
                    start = min([start] + [d.lineno for d in node.decorator_list])
                end = node.end_lineno

                next_name = None
                next_start = None
                for nxt in body[i + 1:]:
                    if isinstance(nxt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        next_name = nxt.name
                        next_start = nxt.lineno
                        if nxt.decorator_list:
                            next_start = min([next_start] + [d.lineno for d in nxt.decorator_list])
                        break

                print(f"DONOR_METHOD class={cls.name} method={method_name} lines={start}-{end} next={next_name} next_start={next_start}")
                return "".join(lines[start - 1:end]), next_name

    raise RuntimeError(f"Could not find donor method {method_name}")

def find_current_method_bounds(src: str, method_name: str, next_method_name: str | None):
    start_token = f"    def {method_name}("
    start = src.find(start_token)
    if start < 0:
        raise RuntimeError(f"Could not find current method start: {start_token}")

    if next_method_name:
        next_token = f"\n    def {next_method_name}("
        next_pos = src.find(next_token, start + len(start_token))
        if next_pos >= 0:
            end = next_pos + 1
            print(f"CURRENT_METHOD method={method_name} start={start} end={end} via_next={next_method_name}")
            return start, end

    # Fallback: scan line starts for the next class-level method.
    lines = src.splitlines(keepends=True)
    char = 0
    start_line = None
    for i, line in enumerate(lines):
        if char == start:
            start_line = i
            break
        char += len(line)

    if start_line is None:
        # start may point inside line because find did not include previous newline
        running = 0
        for i, line in enumerate(lines):
            if running <= start < running + len(line):
                start_line = i
                break
            running += len(line)

    if start_line is None:
        raise RuntimeError("Could not map current method start to line")

    end_line = len(lines)
    for j in range(start_line + 1, len(lines)):
        line = lines[j]
        if line.startswith("    def ") or line.startswith("    async def ") or line.startswith("    @"):
            end_line = j
            break

    start_char = sum(len(x) for x in lines[:start_line])
    end_char = sum(len(x) for x in lines[:end_line])
    print(f"CURRENT_METHOD_FALLBACK method={method_name} lines={start_line+1}-{end_line} chars={start_char}-{end_char}")
    return start_char, end_char

try:
    backup_file(MKI)

    print("=== BEFORE COMPILE ===")
    before = compile_rc(MKI)

    donor = git_head_text()
    donor_chunk, next_name = get_donor_method_chunk(donor, "_build_agent_code")

    src = MKI.read_text(encoding="utf-8", errors="replace")
    start, end = find_current_method_bounds(src, "_build_agent_code", next_name)

    new_src = src[:start] + donor_chunk
    if not donor_chunk.endswith("\n"):
        new_src += "\n"
    new_src += src[end:]

    MKI.write_text(new_src, encoding="utf-8")
    print("PATCHED eli/gui/eli_pro_audio_gui_MKI.py::_build_agent_code")

    print("=== AFTER COMPILE ===")
    after = compile_rc(MKI)

    print(f"BACKUP={BACKUP}")
    print(f"BEFORE_RC={before}")
    print(f"AFTER_RC={after}")

except Exception:
    traceback.print_exc()
