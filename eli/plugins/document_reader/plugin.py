# eli/plugins/document_reader/plugin.py
from __future__ import annotations

from pathlib import Path
from eli.plugins.base import Plugin

_TEXT_SUFFIXES = {
    ".txt", ".md", ".rst", ".log", ".csv", ".json",
    ".yaml", ".yml", ".py", ".js", ".ts", ".html",
    ".xml", ".toml", ".ini", ".cfg", ".sh", ".bat",
}


class DocumentReaderPlugin(Plugin):
    name = "document_reader"
    description = "Read and optionally index local documents (txt, md, PDF, docx)."

    def __init__(self):
        self.actions = {
            "read": self.read,
            "index_document": self.index_document_action,
        }
        super().__init__()

    def is_available(self) -> bool:
        return True

    # ── Public actions ──────────────────────────────────────────────────────

    def read(self, args: dict) -> dict:
        path = (args.get("path") or args.get("file") or args.get("filename") or "").strip()
        if not path:
            return {"ok": False, "error": "No path provided.", "content": "Provide a file path.", "response": "Provide a file path."}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": "not_found", "content": f"File not found: {p}", "response": f"File not found: {p}"}
        suffix = p.suffix.lower()
        try:
            if suffix == ".pdf":
                return self._read_pdf(p)
            elif suffix in (".docx", ".doc"):
                return self._read_docx(p)
            elif suffix in _TEXT_SUFFIXES or p.stat().st_size < 2_000_000:
                text = p.read_text(encoding="utf-8", errors="ignore")
                truncated = len(text) > 8000
                return {
                    "ok": True, "content": text[:8000], "response": text[:8000],
                    "path": str(p), "length": len(text), "truncated": truncated,
                }
            else:
                return {"ok": False, "error": "unsupported_format",
                        "content": f"Unsupported file type: {suffix}",
                        "response": f"Cannot read {suffix} files."}
        except Exception as e:
            return {"ok": False, "error": str(e), "content": str(e), "response": str(e), "path": str(p)}

    def index_document_action(self, args: dict) -> dict:
        path = args.get("path") or args.get("file") or ""
        return self.index_document(str(path))

    def index_document(self, path: str) -> dict:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": "not_found", "path": str(p)}
        result = self.read({"path": str(p)})
        if not result.get("ok"):
            return result
        try:
            from eli.memory import get_search_memory
            mem = get_search_memory()
            mem.store_memory(
                f"Document: {p.name}\n\n{result['content'][:3000]}",
                tags=["document", p.suffix.lstrip(".")],
                source="document_reader",
                kind="document",
            )
            result["indexed"] = True
            result["backend"] = "eli_memory"
        except Exception as e:
            result["indexed"] = False
            result["index_error"] = str(e)
        return result

    # ── Private readers ─────────────────────────────────────────────────────

    def _read_pdf(self, p: Path) -> dict:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(p))
            pages = [page.extract_text() or "" for page in reader.pages[:20]]
            text = "\n".join(pages)
            truncated = len(text) > 8000
            return {
                "ok": True, "content": text[:8000], "response": text[:8000],
                "path": str(p), "pages": len(reader.pages), "truncated": truncated,
            }
        except ImportError:
            pass
        try:
            import pdfplumber
            with pdfplumber.open(str(p)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages[:20]]
            text = "\n".join(pages)
            return {"ok": True, "content": text[:8000], "response": text[:8000], "path": str(p)}
        except ImportError:
            pass
        return {
            "ok": False,
            "error": "PDF reading requires pypdf or pdfplumber.",
            "content": "Install PDF support: pip install pypdf",
            "response": "PDF support not installed. Run: pip install pypdf",
        }

    def _read_docx(self, p: Path) -> dict:
        try:
            import docx
            doc = docx.Document(str(p))
            text = "\n".join(para.text for para in doc.paragraphs)
            truncated = len(text) > 8000
            return {
                "ok": True, "content": text[:8000], "response": text[:8000],
                "path": str(p), "truncated": truncated,
            }
        except ImportError:
            return {
                "ok": False,
                "error": "DOCX reading requires python-docx.",
                "content": "Install DOCX support: pip install python-docx",
                "response": "DOCX support not installed. Run: pip install python-docx",
            }


PluginClass = DocumentReaderPlugin
