import os
import json
import sqlite3
from pathlib import Path

from eli.kernel.pipeline import get_pipeline_description
from eli.core.paths import get_paths

def _eli_path_get(obj, key, default=None):
    """
    Compatibility helper for ELI path containers.
    Accepts both dict-style path maps and object/namespace-style path maps.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class IntrospectionAgent:
    def get_pipeline(self) -> str:
        return "\n".join(get_pipeline_description())

    def get_memory_stats(self) -> str:
        paths = get_paths()
        user_db = paths.user_db
        memory_db = _eli_path_get(paths, "memory_db")

        turn_count = 0
        mem_count = 0

        if user_db.exists():
            conn = sqlite3.connect(user_db)
            try:
                cur = conn.execute("SELECT COUNT(*) FROM conversation_turns")
                row = cur.fetchone()
                turn_count = row[0] if row else 0
            finally:
                conn.close()

        if memory_db.exists():
            conn = sqlite3.connect(memory_db)
            try:
                cur = conn.execute("SELECT COUNT(*) FROM memories")
                row = cur.fetchone()
                mem_count = row[0] if row else 0
            finally:
                conn.close()

        return f"Total conversation turns: {turn_count}\nTotal stored memories: {mem_count}"

    def get_runtime(self) -> str:
        snapshot = {}
        settings = {}

        try:
            snap_path = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
            if snap_path.exists():
                snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except Exception:
            snapshot = {}

        try:
            from eli.core import runtime_settings as _rs
            settings = _rs.load_settings() or {}
        except Exception:
            settings = {}

        def _pick(*values):
            for v in values:
                if v not in (None, "", [], {}, ()):
                    return v
            return "unknown"

        provider = _pick(
            snapshot.get("provider"),
            settings.get("provider"),
            os.environ.get("ELI_PROVIDER"),
        )
        model = _pick(
            snapshot.get("model_name"),
            settings.get("selected_model"),
            os.environ.get("ELI_GGUF_MODEL"),
            os.environ.get("ELI_MODEL"),
        )
        model_path = _pick(
            snapshot.get("model_path"),
            settings.get("gguf_model_path"),
            settings.get("model_path"),
            settings.get("custom_model_path"),
            settings.get("bundled_model_path"),
        )
        ctx = _pick(
            snapshot.get("n_ctx"),
            settings.get("n_ctx"),
            os.environ.get("ELI_GGUF_N_CTX"),
            os.environ.get("ELI_CONTEXT"),
        )
        gpu = _pick(
            snapshot.get("n_gpu_layers"),
            settings.get("n_gpu_layers"),
            settings.get("gpu_layers"),
            os.environ.get("ELI_GGUF_N_GPU_LAYERS"),
            os.environ.get("ELI_GPU_LAYERS"),
        )
        batch = _pick(
            snapshot.get("n_batch"),
            settings.get("batch_size"),
            os.environ.get("ELI_GGUF_N_BATCH"),
            os.environ.get("ELI_BATCH"),
        )
        threads = _pick(
            snapshot.get("n_threads"),
            settings.get("n_threads"),
            settings.get("cpu_threads"),
            os.environ.get("ELI_GGUF_THREADS"),
            os.environ.get("ELI_THREADS"),
        )
        loaded = snapshot.get("loaded")

        lines = [
            f"Provider: {provider}",
            f"Model: {model}",
            f"Context size: {ctx}",
            f"GPU-layer parameter: {gpu}",
            f"Batch size: {batch}",
            f"Threads: {threads}",
        ]
        if model_path != "unknown":
            lines.append(f"Model path: {model_path}")
        if loaded is not None:
            lines.append(f"Loaded in process: {loaded}")

        return "\n".join(lines)

    def run_audit(self) -> str:
        from eli.execution.executor_enhanced import _audit_python_file

        # Path(__file__).parents[2] resolves to the project root
        # (eli/cognition/introspection_agent.py -> eli -> project_root).
        # We then descend back into eli/ for actual source files.
        root = get_paths().project_root
        eli_dir = root / "eli"
        files = [
            str(eli_dir / "kernel" / "engine.py"),
            str(eli_dir / "cognition" / "gguf_inference.py"),
            str(eli_dir / "cognition" / "agent_bus.py"),
            str(eli_dir / "cognition" / "orchestrator.py"),
            str(eli_dir / "cognition" / "inference_broker.py"),
            str(eli_dir / "cognition" / "output_governor.py"),
            str(eli_dir / "memory" / "memory.py"),
            str(eli_dir / "memory" / "__init__.py"),
            str(eli_dir / "memory" / "vector_store.py"),
            str(eli_dir / "execution" / "router_enhanced.py"),
            str(eli_dir / "execution" / "executor_enhanced.py"),
            str(eli_dir / "planning" / "proactive_daemon.py"),
            str(eli_dir / "core" / "paths.py"),
            str(eli_dir / "core" / "runtime_settings.py"),
        ]

        results = []
        for f in files:
            entry = _audit_python_file(f)
            status = entry.get("status", "?")
            issues = entry.get("issues", [])
            results.append(f"{status} {f}")
            for issue in issues:
                results.append(
                    f"  - line {issue.get('line')} [{issue.get('type')}] {issue.get('message')}"
                )

        return "\n".join(results)
