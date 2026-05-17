#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase18_restore_embedder_asset_license_manifest_${STAMP}"
BACKUP="$OUT/backups"

EMBED_DIR="$ROOT/models/embeddings"
EMBED_FILE="$EMBED_DIR/nomic-embed-text-v1.5.Q4_K_M.gguf"
EMBED_URL="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf?download=true"
EMBED_SHA256="d4e388894e09cf3816e8b0896d81d265b55e7a9fff9ab03fe8bf4ef5e11295ac"

PACKAGING_DIR="$ROOT/packaging"
ASSET_MANIFEST="$PACKAGING_DIR/runtime_asset_manifest.json"
VOICE_REVIEW="$PACKAGING_DIR/VOICE_LICENSE_REVIEW.md"
EMBED_SOURCE_DOC="$EMBED_DIR/SOURCE_nomic-embed-text-v1.5.Q4_K_M.md"

mkdir -p "$OUT" "$BACKUP" "$EMBED_DIR" "$PACKAGING_DIR"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 18 — Restore Embedder + Asset/License Manifest"
echo "ROOT : $ROOT"
echo "OUT  : $OUT"
echo "TIME : $(date -Is)"
echo "======================================================================"
echo

if [ ! -d "$ROOT/eli" ] || [ ! -f "$ROOT/bin/elix" ]; then
  echo "FATAL: not an ELI project root:"
  echo "  $ROOT"
  false
fi

{
  echo "# Phase 18 — Restore Embedder + Asset/License Manifest"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 0. Back up existing generated asset-policy files where present ==="
for path in \
  "$ASSET_MANIFEST" \
  "$VOICE_REVIEW" \
  "$EMBED_SOURCE_DOC"
do
  if [ -f "$path" ]; then
    rel="${path#$ROOT/}"
    dst="$BACKUP/$rel"
    mkdir -p "$(dirname "$dst")"
    cp -a "$path" "$dst"
    echo "BACKUP $rel"
  else
    echo "NO PRIOR FILE $path"
  fi
done
echo

echo "=== 1. Download or verify official Nomic Q4_K_M embedder ==="
if [ -f "$EMBED_FILE" ]; then
  EXISTING_SHA="$(sha256sum "$EMBED_FILE" | awk '{print $1}')"
  echo "Existing embedder found:"
  echo "  $EMBED_FILE"
  echo "Existing SHA256:"
  echo "  $EXISTING_SHA"

  if [ "$EXISTING_SHA" = "$EMBED_SHA256" ]; then
    echo "EMBEDDER_SHA_OK: existing file matches expected official SHA256."
  else
    BAD="$BACKUP/nomic-embed-text-v1.5.Q4_K_M.bad_${STAMP}.gguf"
    mkdir -p "$(dirname "$BAD")"
    mv "$EMBED_FILE" "$BAD"
    echo "EMBEDDER_SHA_MISMATCH: moved mismatched file to:"
    echo "  $BAD"
  fi
fi

if [ ! -f "$EMBED_FILE" ]; then
  TMP="$OUT/nomic-embed-text-v1.5.Q4_K_M.gguf.part"

  echo "Downloading official embedder to temporary file:"
  echo "  $TMP"

  if command -v curl >/dev/null 2>&1; then
    curl -fL \
      --retry 4 \
      --retry-delay 3 \
      --connect-timeout 20 \
      -o "$TMP" \
      "$EMBED_URL"
  elif command -v wget >/dev/null 2>&1; then
    wget \
      --tries=4 \
      --waitretry=3 \
      -O "$TMP" \
      "$EMBED_URL"
  else
    echo "FATAL: neither curl nor wget is available."
    false
  fi

  DOWNLOADED_SHA="$(sha256sum "$TMP" | awk '{print $1}')"
  echo "Downloaded SHA256:"
  echo "  $DOWNLOADED_SHA"

  if [ "$DOWNLOADED_SHA" != "$EMBED_SHA256" ]; then
    echo "FATAL: downloaded embedder SHA256 mismatch."
    echo "Expected: $EMBED_SHA256"
    echo "Actual  : $DOWNLOADED_SHA"
    false
  fi

  mv "$TMP" "$EMBED_FILE"
  chmod 0644 "$EMBED_FILE"
  echo "EMBEDDER_INSTALLED:"
  echo "  $EMBED_FILE"
fi

FINAL_SHA="$(sha256sum "$EMBED_FILE" | awk '{print $1}')"
FINAL_BYTES="$(stat -c '%s' "$EMBED_FILE")"

{
  echo "path=$EMBED_FILE"
  echo "sha256=$FINAL_SHA"
  echo "bytes=$FINAL_BYTES"
  echo "expected_sha256=$EMBED_SHA256"
} | tee "$OUT/01_embedder_restore.txt"

if [ "$FINAL_SHA" != "$EMBED_SHA256" ]; then
  echo "FATAL: final embedder SHA256 mismatch after restore."
  false
fi
echo

echo "=== 2. Write embedder provenance/source documentation ==="
cat > "$EMBED_SOURCE_DOC" <<EOF
# Nomic Embed GGUF Asset Source

- Asset: \`nomic-embed-text-v1.5.Q4_K_M.gguf\`
- Local path: \`models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf\`
- Upstream repository: \`nomic-ai/nomic-embed-text-v1.5-GGUF\`
- Upstream filename: \`nomic-embed-text-v1.5.Q4_K_M.gguf\`
- SHA-256: \`$EMBED_SHA256\`
- Observed local byte size: \`$FINAL_BYTES\`
- License listed by upstream model repository: Apache-2.0
- Packaging note: retain upstream license/attribution review in any commercial redistribution workflow.
EOF

echo "WROTE:"
echo "  $EMBED_SOURCE_DOC"
echo

echo "=== 3. Generate runtime asset manifest and voice-license classification ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" "$ASSET_MANIFEST" "$VOICE_REVIEW" "$EMBED_SHA256" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
asset_manifest_path = Path(sys.argv[3]).resolve()
voice_review_path = Path(sys.argv[4]).resolve()
embed_expected_sha = sys.argv[5].strip()

embed_path = root / "models" / "embeddings" / "nomic-embed-text-v1.5.Q4_K_M.gguf"
tts_root = root / "tts_piper" / "piper"

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def rel(path: Path) -> str:
    return str(path.resolve().relative_to(root))

voice_policy = {
    "en_US-ryan-high": {
        "commercial_distribution_default": "exclude",
        "risk": "Upstream MODEL_CARD dataset license is CC BY-NC-SA 4.0.",
        "status": "noncommercial_risk",
    },
    "en_US-lessac-high": {
        "commercial_distribution_default": "manual_review",
        "risk": "Upstream MODEL_CARD points to the Blizzard 2013 Lessac dataset license; commercial redistribution requires explicit review.",
        "status": "license_review_required",
    },
    "en_GB-cori-high": {
        "commercial_distribution_default": "manual_review",
        "risk": "Upstream model card identifies a public-domain LibriVox dataset; still retain upstream model-card/license evidence before shipping.",
        "status": "review_before_ship",
    },
}

voices = []
if tts_root.exists():
    for onnx in sorted(tts_root.glob("*.onnx")):
        voice_id = onnx.name[:-5]
        cfg = tts_root / f"{voice_id}.onnx.json"
        rule = voice_policy.get(
            voice_id,
            {
                "commercial_distribution_default": "manual_review",
                "risk": "No local classification rule. Review upstream MODEL_CARD before bundling.",
                "status": "unclassified_review_required",
            },
        )

        voices.append(
            {
                "id": voice_id,
                "onnx_path": rel(onnx),
                "onnx_json_path": rel(cfg) if cfg.exists() else None,
                "onnx_exists": onnx.exists(),
                "onnx_json_exists": cfg.exists(),
                "onnx_bytes": onnx.stat().st_size if onnx.exists() else None,
                "onnx_sha256": sha256_file(onnx) if onnx.exists() else None,
                **rule,
            }
        )

manifest = {
    "schema": "eli.runtime_asset_manifest.v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "project_root_policy": "all paths are project-relative; no user-specific absolute paths are distributable metadata",
    "embedding_assets": [
        {
            "id": "embedding.nomic-embed-text-v1.5.Q4_K_M",
            "path": rel(embed_path),
            "exists": embed_path.exists(),
            "sha256": sha256_file(embed_path) if embed_path.exists() else None,
            "expected_sha256": embed_expected_sha,
            "bytes": embed_path.stat().st_size if embed_path.exists() else None,
            "upstream_repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
            "upstream_filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
            "upstream_license_reported": "Apache-2.0",
            "bundle_policy": "required_for_full_vector_recall_profile",
        }
    ],
    "tts_voice_assets": voices,
    "commercial_bundle_exclusions_default": [
        voice["id"]
        for voice in voices
        if voice["commercial_distribution_default"] == "exclude"
    ],
    "manual_license_review_required": [
        voice["id"]
        for voice in voices
        if voice["commercial_distribution_default"] == "manual_review"
    ],
}

asset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
asset_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

review_lines = [
    "# ELI Piper Voice License Review",
    "",
    "This report is packaging guidance, not a replacement for formal legal review.",
    "",
    "## Current packaged voice assets detected",
    "",
]

for voice in voices:
    review_lines.extend(
        [
            f"### `{voice['id']}`",
            "",
            f"- ONNX: `{voice['onnx_path']}`",
            f"- Config present: `{voice['onnx_json_exists']}`",
            f"- Classification: **{voice['status']}**",
            f"- Commercial bundle default: **{voice['commercial_distribution_default']}**",
            f"- Reason: {voice['risk']}",
            "",
        ]
    )

review_lines.extend(
    [
        "## Packaging rule",
        "",
        "- Do **not** automatically include voices classified `exclude` in a commercial distribution bundle.",
        "- Do **not** assume repository-level metadata resolves dataset/model-card licensing conflicts.",
        "- Retain MODEL_CARD/license evidence for any voice approved for shipping.",
        "",
        "## Immediate implication",
        "",
        "- `en_US-ryan-high` should be excluded from a commercial redistribution bundle by default unless you obtain independent legal clearance.",
        "- `en_US-lessac-high` requires review of the Blizzard/LESSAC dataset license referenced by its upstream model card.",
        "- `en_GB-cori-high` appears materially lower risk from the available upstream card, but it should still be documented before shipping.",
        "",
    ]
)

voice_review_path.parent.mkdir(parents=True, exist_ok=True)
voice_review_path.write_text("\n".join(review_lines), encoding="utf-8")

(out / "02_runtime_asset_manifest_summary.txt").write_text(
    "\n".join(
        [
            f"asset_manifest={asset_manifest_path}",
            f"voice_review={voice_review_path}",
            f"voices_detected={len(voices)}",
            f"commercial_bundle_exclusions={manifest['commercial_bundle_exclusions_default']}",
            f"manual_license_review_required={manifest['manual_license_review_required']}",
        ]
    )
    + "\n",
    encoding="utf-8",
)

print(f"WROTE {asset_manifest_path}")
print(f"WROTE {voice_review_path}")
print(f"voices_detected={len(voices)}")
print(f"commercial_bundle_exclusions={manifest['commercial_bundle_exclusions_default']}")
print(f"manual_license_review_required={manifest['manual_license_review_required']}")
PY
echo

echo "=== 4. Vector-store embedder smoke test ==="
env -u PYTHONPATH ELI_PROJECT_ROOT="$ROOT" python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root))

payload = {
    "vector_store_import": None,
    "faiss_available": None,
    "llama_cpp_available": None,
    "embedder_ready": None,
    "embedder_error": None,
    "embedding_probe_shape": None,
    "error": None,
}

try:
    try:
        import llama_cpp  # noqa: F401
        payload["llama_cpp_available"] = True
    except Exception:
        payload["llama_cpp_available"] = False

    from eli.memory import vector_store as vsmod

    payload["vector_store_import"] = "OK"
    payload["faiss_available"] = bool(getattr(vsmod, "FAISS_AVAILABLE", False))

    store = vsmod.VectorStore()
    payload["embedder_ready"] = store._embedder is not None
    payload["embedder_error"] = store._embedder_error

    if store._embedder is not None:
        vec = store._embed("phase18 embedding smoke test")
        if vec is not None:
            payload["embedding_probe_shape"] = list(vec.shape)

except Exception as exc:
    payload["error"] = f"{type(exc).__name__}: {exc}"

(out / "03_vector_store_embedder_smoke.json").write_text(
    json.dumps(payload, indent=2),
    encoding="utf-8",
)

for key, value in payload.items():
    print(f"{key}={value!r}")
PY
echo

echo "=== 5. Packaging presence snapshot after asset restoration ==="
{
  echo "Embedder:"
  ls -lh "$EMBED_FILE"
  sha256sum "$EMBED_FILE"
  echo
  echo "Asset manifest:"
  ls -lh "$ASSET_MANIFEST"
  echo
  echo "Voice license review:"
  ls -lh "$VOICE_REVIEW"
  echo
  echo "Embedding source doc:"
  ls -lh "$EMBED_SOURCE_DOC"
} | tee "$OUT/04_asset_presence_snapshot.txt"
echo

echo "=== 6. Git status ==="
{
  git status --short 2>/dev/null || true
} | tee "$OUT/05_git_status.txt"
echo

{
  echo "## Repairs performed"
  echo
  echo "1. Restored the official Nomic GGUF embedding model required by ELI's vector store."
  echo "2. Verified the model against the expected SHA-256 digest."
  echo "3. Wrote asset provenance for the restored embedder."
  echo "4. Generated a project-relative runtime asset manifest."
  echo "5. Generated a Piper voice licensing review report."
  echo "6. Marked \`en_US-ryan-high\` as excluded from commercial redistribution by default in the generated policy manifest."
  echo "7. Ran a live vector-store embedder smoke test."
  echo
  echo "## Read these first"
  echo
  echo "- \`01_embedder_restore.txt\`"
  echo "- \`02_runtime_asset_manifest_summary.txt\`"
  echo "- \`03_vector_store_embedder_smoke.json\`"
  echo "- \`04_asset_presence_snapshot.txt\`"
  echo "- \`$ASSET_MANIFEST\`"
  echo "- \`$VOICE_REVIEW\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 18 COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/03_vector_store_embedder_smoke.json"
echo "  $PACKAGING_DIR/runtime_asset_manifest.json"
echo "  $PACKAGING_DIR/VOICE_LICENSE_REVIEW.md"
echo "======================================================================"
