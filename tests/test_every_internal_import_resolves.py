"""Every `import eli.x` / `from eli.x import y` in the tree names a module or package that exists.

Most of these sit inside try/except, so a wrong path never raises: the feature quietly does nothing.
`eli.runtime.proposal_queue` (it lives in eli.planning) meant goal proposals were never queued.
"""
import ast
import functools
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _exists(mod: str) -> bool:
    p = ROOT / mod.replace(".", "/")
    return p.with_suffix(".py").is_file() or p.is_dir()


def _internal(mod: str) -> bool:
    return mod == "eli" or mod.startswith("eli.")


def test_every_internal_import_resolves():
    missing = []
    for f in list((ROOT / "eli").rglob("*.py")) + list((ROOT / "api").rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and _internal(n.module):
                if not _exists(n.module):
                    missing.append(f"{f.relative_to(ROOT)}: {n.module}")
                    continue
                pkg = ROOT / n.module.replace(".", "/")
                init = pkg / "__init__.py"
                if pkg.is_dir() and init.is_file():
                    text = init.read_text(encoding="utf-8", errors="ignore")
                    for a in n.names:
                        if a.name != "*" and a.name not in text and not _exists(f"{n.module}.{a.name}"):
                            missing.append(f"{f.relative_to(ROOT)}: {n.module}.{a.name}")
            elif isinstance(n, ast.Import):
                missing += [f"{f.relative_to(ROOT)}: {a.name}" for a in n.names
                            if _internal(a.name) and not _exists(a.name)]
    assert not missing, "imports of modules that do not exist:\n" + "\n".join(sorted(set(missing)))


@functools.lru_cache(maxsize=None)
def _defined(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(text)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names |= {y.id for x in targets for y in ast.walk(x) if isinstance(y, ast.Name)}
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in n.names}
    dynamic = "import *" in text or "globals()[" in text or "__getattr__" in text or "setattr(" in text
    return names, dynamic


def test_every_name_imported_from_an_internal_module_is_defined_there():
    missing = []
    for f in list((ROOT / "eli").rglob("*.py")) + list((ROOT / "api").rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and _internal(n.module)):
                continue
            target = ROOT / (n.module.replace(".", "/") + ".py")
            if not target.is_file() or target.with_suffix("").is_dir():
                continue
            names, dynamic = _defined(target)
            if not dynamic:
                missing += [f"{f.relative_to(ROOT)}: {n.module}.{a.name}" for a in n.names
                            if a.name != "*" and a.name not in names]
    assert not missing, "imports of names that module does not define:\n" + "\n".join(sorted(set(missing)))
