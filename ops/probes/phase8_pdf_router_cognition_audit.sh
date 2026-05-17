#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$PWD}"
cd "$ROOT" || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase8_pdf_router_cognition_audit_${STAMP}"
mkdir -p "$OUT"

PDF1="/home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf"
PDF2="/home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf"

{
  echo "# Phase 8 PDF / Router / Cognition Audit"
  echo
  echo "Date: $(date)"
  echo "Root: $ROOT"
  echo "HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo no-git)"
  echo
} > "$OUT/SUMMARY.md"

echo "=== Git status ===" | tee "$OUT/git_status.txt"
git status --short 2>&1 | tee -a "$OUT/git_status.txt" || true

echo "=== Runtime snapshot ===" > "$OUT/runtime_snapshot.txt"
cat artifacts/runtime_snapshot.json >> "$OUT/runtime_snapshot.txt" 2>&1 || true

echo "=== PDF existence ===" | tee "$OUT/pdf_existence.txt"
for p in "$PDF1" "$PDF2"; do
  if [[ -f "$p" ]]; then
    ls -lh "$p" | tee -a "$OUT/pdf_existence.txt"
  else
    echo "MISSING: $p" | tee -a "$OUT/pdf_existence.txt"
  fi
done

echo "=== Candidate files ===" | tee "$OUT/candidate_files.txt"
CANDIDATES=(
  "eli/execution/router_enhanced.py"
  "eli/execution/executor_enhanced.py"
  "eli/perception/analyze_pdfs.py"
  "eli/cognition/engine.py"
  "eli/cognition/orchestrator.py"
  "eli/cognition/gguf_inference.py"
  "eli/cognition/output_governor.py"
  "eli/cognition/response_governance.py"
  "eli/cognition/reasoning_modes.py"
  "eli/cognition/hyde.py"
  "eli/memory/vector_store.py"
  "eli/memory/sqlite_memory.py"
  "eli/memory/memory_service.py"
  "eli/memory/memory_adapter.py"
  "eli/memory/memory_truth.py"
  "eli/gui/eli_pro_audio_gui_MKI.py"
)

for f in "${CANDIDATES[@]}"; do
  if [[ -f "$f" ]]; then
    stat -c "%y %s %n" "$f" | tee -a "$OUT/candidate_files.txt"
  else
    echo "MISSING: $f" | tee -a "$OUT/candidate_files.txt"
  fi
done

echo "=== Router media/PDF/audit grep ===" | tee "$OUT/router_grep.txt"
grep -RInE "PLAY_MEDIA|spotify|youtube|ANALYZE_PDF|PDF|pdf|implied_song_by_artist|EXPLAIN_MEMORY_RUNTIME|CODEBASE_AUDIT|audit" \
  eli/execution eli/cognition eli/perception 2>/dev/null | tee -a "$OUT/router_grep.txt" || true

echo "=== analyze_pdfs.py ===" > "$OUT/analyze_pdfs_source.txt"
sed -n '1,260p' eli/perception/analyze_pdfs.py >> "$OUT/analyze_pdfs_source.txt" 2>&1 || true

echo "=== path extraction probe ===" > "$OUT/path_extraction_probe.txt"
python3 - <<'PY' >> "$OUT/path_extraction_probe.txt"
import re
from pathlib import Path

samples = [
    "read and summarise /home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf and /home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf",
    "analyse and talk to me about [PDF content — Exergetic_Coherence_Revoloution.pdf]: Exergetic Cosmology...",
    "/Exergetic_Coherence_Revoloution.pdf",
]

# Proposed robust absolute/relative PDF path matcher.
pdf_re = re.compile(
    r'(?P<path>(?:~|/|\.{1,2}/)[^\n\r\t"\047<>]*?\.pdf)\b',
    re.IGNORECASE,
)

for s in samples:
    print("INPUT:", s[:180])
    matches = [m.group("path").strip() for m in pdf_re.finditer(s)]
    print("MATCHES:", matches)
    print()

# Basename detector for bracketed PDF content.
name_re = re.compile(r'(?P<name>[A-Za-z0-9_. -]+\.pdf)\b', re.IGNORECASE)
for s in samples:
    print("BASENAMES:", [m.group("name").strip() for m in name_re.finditer(s)])
PY

echo "=== PDF text extraction probe ===" > "$OUT/pdf_extract_probe.txt"
python3 - <<PY >> "$OUT/pdf_extract_probe.txt"
from pathlib import Path

paths = [
    Path("$PDF1"),
    Path("$PDF2"),
]

def extract_with_available_lib(path):
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text = []
        for i, page in enumerate(reader.pages[:5]):
            text.append(page.extract_text() or "")
        return len(reader.pages), "\\n".join(text)
    except Exception as e1:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(path))
            text = []
            for i, page in enumerate(reader.pages[:5]):
                text.append(page.extract_text() or "")
            return len(reader.pages), "\\n".join(text)
        except Exception as e2:
            return None, f"EXTRACT_FAILED: pypdf={e1!r}; PyPDF2={e2!r}"

for p in paths:
    print("=" * 80)
    print("PDF:", p)
    print("exists:", p.exists())
    if p.exists():
        pages, text = extract_with_available_lib(p)
        print("pages:", pages)
        print("chars_first_5_pages:", len(text))
        print("preview:")
        print(text[:3000])
PY

echo "=== Compile check ===" | tee "$OUT/compile_check.txt"
python3 -m compileall -q eli 2>&1 | tee -a "$OUT/compile_check.txt" || true

{
  echo
  echo "## Findings to check"
  echo
  echo "1. If router_grep shows PLAY_MEDIA rules before ANALYZE_PDF/document/audit guards, route priority is wrong."
  echo "2. If ANALYZE_PDF receives only one path, the route contract lacks multi-PDF support."
  echo "3. If /home/jay/Desktop/... becomes /Exergetic..., path extraction is stripping directories."
  echo "4. If executor ok=False still reaches normal GGUF synthesis, failure contracts are leaking."
  echo "5. If audit prompts route to EXPLAIN_MEMORY_RUNTIME, memory route precedence is too broad."
  echo
  echo "## Report files"
  find "$OUT" -maxdepth 1 -type f -printf '%f\n' | sort
} >> "$OUT/SUMMARY.md"

echo
echo "REPORT: $OUT"
cat "$OUT/SUMMARY.md"
