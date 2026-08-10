# eli/plugins/document_reader/plugin.py
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from eli.plugins.base import Plugin

_TEXT_SUFFIXES = {
    ".txt", ".md", ".rst", ".log", ".csv", ".json",
    ".yaml", ".yml", ".py", ".js", ".ts", ".html",
    ".xml", ".toml", ".ini", ".cfg", ".sh", ".bat",
}

# ODT and EPUB are both zip containers. Neither is in _TEXT_SUFFIXES, so before
# they were dispatched here any such file under the 2MB threshold fell through
# to the plain-text branch and came back as decoded zip bytes with ok=True —
# mojibake presented as the document's contents rather than an honest refusal.
_MAX_CHARS = 8000


def _localname(tag: str) -> str:
    """`{urn:...:text:1.0}p` -> `p`. ODF tags are always namespaced."""
    return tag.rsplit("}", 1)[-1]


# Paragraph-ish blocks, and what must not be absorbed into one.
_ODT_BLOCK = ("p", "h")
_ODT_NESTED = {"p", "h", "note"}


def _odt_paragraph_text(el) -> str:
    """Text of a single ODF paragraph, excluding anything that is its own block.

    A plain ``itertext()`` is wrong here, and silently so. LibreOffice writes a
    footnote as ``text:note > text:note-body > text:p`` *inside* the paragraph
    that references it, and puts the marker in ``text:note-citation``; text
    boxes (``draw:frame``) nest ``text:p`` the same way. itertext() on the outer
    paragraph swallowed all of that, and the main walk then emitted the very
    same footnote paragraph again — so footnote text landed in the output twice
    with the citation number spliced into the middle of the sentence.

    Nested blocks are skipped here and emitted in their own right by the caller.
    The child's ``tail`` is always kept: that is the sentence continuing after
    the footnote marker.
    """
    parts = [el.text or ""]
    for child in el:
        if _localname(child.tag) not in _ODT_NESTED:
            parts.append(_odt_paragraph_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


class _TextExtractor(HTMLParser):
    """Minimal XHTML -> text. stdlib only; ebooklib/bs4 are not on the shipped stack."""

    _SKIP = {"script", "style", "head"}
    _BREAK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._depth:
            self._depth -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._depth:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        lines = [ln.strip() for ln in joined.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        pass
    return parser.text()


class DocumentReaderPlugin(Plugin):
    name = "document_reader"
    description = "Read and optionally index local documents (txt, md, PDF, docx, odt, epub)."

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
            elif suffix == ".odt":
                return self._read_odt(p)
            elif suffix == ".epub":
                return self._read_epub(p)
            elif suffix in _TEXT_SUFFIXES or p.stat().st_size < 2_000_000:
                raw = p.read_bytes()
                # Only known-text suffixes get the benefit of the doubt. Anything
                # else that carries NULs early is binary, and decoding it would
                # hand back garbage under ok=True instead of saying so.
                if suffix not in _TEXT_SUFFIXES and b"\x00" in raw[:4096]:
                    return {"ok": False, "error": "unsupported_format",
                            "content": f"Unsupported binary file type: {suffix}",
                            "response": f"Cannot read {suffix} files.", "path": str(p)}
                text = raw.decode("utf-8", errors="ignore")
                return self._text_result(p, text)
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

    def _text_result(self, p: Path, text: str) -> dict:
        return {
            "ok": True, "content": text[:_MAX_CHARS], "response": text[:_MAX_CHARS],
            "path": str(p), "length": len(text), "truncated": len(text) > _MAX_CHARS,
        }

    def _bad_container(self, p: Path, why: str) -> dict:
        return {"ok": False, "error": why, "content": why, "response": why, "path": str(p)}

    def _read_odt(self, p: Path) -> dict:
        """OpenDocument text: a zip whose content.xml carries the body.

        Deliberately stdlib — odfpy would be a new runtime dependency on the
        shipped stack for what ElementTree does in a dozen lines.
        """
        import zipfile
        from xml.etree import ElementTree as ET

        try:
            with zipfile.ZipFile(str(p)) as z:
                xml = z.read("content.xml")
        except zipfile.BadZipFile:
            return self._bad_container(p, "Not a valid OpenDocument file (bad zip container).")
        except KeyError:
            return self._bad_container(p, "Not a valid OpenDocument file (no content.xml).")

        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            return self._bad_container(p, f"Malformed OpenDocument content.xml: {e}")

        # Every paragraph/heading in document order. Footnote and text-box
        # paragraphs are nested inside others and are emitted once, on their own,
        # by _odt_paragraph_text skipping them in the parent — see that docstring.
        lines = []
        for el in root.iter():
            if _localname(el.tag) in _ODT_BLOCK:
                # Collapse the whitespace that pretty-printed XML introduces.
                line = " ".join(_odt_paragraph_text(el).split())
                if line:
                    lines.append(line)
        return self._text_result(p, "\n".join(lines))

    def _read_epub(self, p: Path) -> dict:
        """EPUB: a zip of XHTML read in spine order, which is reading order.

        Falls back to sorted filenames when the OPF is unreadable — a mangled
        spine should degrade to out-of-order text, not to no text at all.
        """
        import zipfile

        try:
            with zipfile.ZipFile(str(p)) as z:
                parts = []
                for name in self._epub_documents(z)[:50]:
                    try:
                        raw = z.read(name)
                    except KeyError:
                        continue
                    chunk = _html_to_text(raw.decode("utf-8", errors="ignore"))
                    if chunk:
                        parts.append(chunk)
                        if sum(len(x) for x in parts) > _MAX_CHARS:
                            break
        except zipfile.BadZipFile:
            return self._bad_container(p, "Not a valid EPUB file (bad zip container).")

        return self._text_result(p, "\n\n".join(parts))

    def _epub_documents(self, z) -> list:
        """Content document names in spine order, or sorted names as a fallback.

        Two things real EPUBs do that a naive join gets wrong: hrefs are URL-
        encoded (``chapter%201.xhtml``), and Calibre routinely puts the OPF in
        ``OEBPS/`` while pointing at ``../Text/``. Unresolved names then raise
        KeyError on read, and because the spine list was still non-empty the
        fallback never fired — the reader returned EMPTY text under ok=True.
        So resolved names are checked against the archive before being trusted.
        """
        import posixpath
        from urllib.parse import unquote
        from xml.etree import ElementTree as ET

        present = set(z.namelist())

        def _fallback():
            return sorted(
                n for n in present
                if n.lower().endswith((".xhtml", ".html", ".htm"))
            )

        def _resolve(base: str, href: str) -> str:
            # Strip any fragment, decode %XX, then normalise ../ against the OPF dir.
            href = unquote(href.split("#", 1)[0])
            return posixpath.normpath(posixpath.join(base, href)) if base else href

        try:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = ""
            for el in container.iter():
                if _localname(el.tag) == "rootfile":
                    opf_path = el.get("full-path") or ""
                    break
            if not opf_path:
                return _fallback()

            opf = ET.fromstring(z.read(opf_path))
            base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""

            hrefs, spine = {}, []
            for el in opf.iter():
                tag = _localname(el.tag)
                if tag == "item" and el.get("id"):
                    hrefs[el.get("id")] = el.get("href") or ""
                elif tag == "itemref" and el.get("idref"):
                    spine.append(el.get("idref"))

            names = []
            for idref in spine:
                href = hrefs.get(idref)
                if not href:
                    continue
                # OPF hrefs are relative to the OPF's own directory.
                resolved = _resolve(base, href)
                if resolved in present:
                    names.append(resolved)
            # A spine that resolved to nothing real is no better than no spine.
            return names or _fallback()
        except Exception:
            return _fallback()

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
