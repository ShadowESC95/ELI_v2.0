"""Load TOML on Python 3.10+ (tomli backport) and 3.11+ (stdlib tomllib)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Union


def loads_toml(data: bytes) -> Dict[str, Any]:
    text = data.decode("utf-8")
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        import tomli
        return tomli.loads(text)


def load_toml(path: Union[str, Path]) -> Dict[str, Any]:
    return loads_toml(Path(path).read_bytes())
