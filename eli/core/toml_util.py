"""Load TOML on Python 3.10+ (tomli backport) and 3.11+ (stdlib tomllib)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Union


def loads_toml(data: bytes) -> Dict[str, Any]:
    try:
        import tomllib
        return tomllib.loads(data.decode("utf-8"))
    except ImportError:
        import tomli
        return tomli.loads(data)


def load_toml(path: Union[str, Path]) -> Dict[str, Any]:
    return loads_toml(Path(path).read_bytes())
