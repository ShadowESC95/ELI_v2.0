#!/usr/bin/env bash
# The assets every build bundles and the release's test job tests against: the Piper voices from the
# project's local-assets release, and the text embedder for semantic memory. Needs GH_TOKEN and
# GITHUB_REPOSITORY (set in GitHub Actions).
set -euo pipefail

mkdir -p tts_piper/piper
# The release asset API occasionally answers 5xx mid-download; retry with backoff.
voice_ok=0
for attempt in 1 2 3 4 5; do
  if gh release download local-assets-v2.1 --repo "$GITHUB_REPOSITORY" --clobber \
      --pattern "*.onnx" --pattern "*.onnx.json" --dir tts_piper/piper; then
    voice_ok=1
    break
  fi
  echo "::warning::voice asset download attempt ${attempt}/5 failed — retrying in $((attempt * 5))s"
  sleep $((attempt * 5))
done
[ "$voice_ok" -eq 1 ] || { echo "::error::could not download voices from the local-assets-v2.1 release after 5 attempts"; exit 1; }
count=$(ls tts_piper/piper/*.onnx 2>/dev/null | wc -l)
echo "voices downloaded: $count"
[ "$count" -ge 1 ] || { echo "::error::no .onnx voices present after download"; exit 1; }

# Straight to the repo-relative path ELI.spec bundles from, not through model_download, whose
# models_dir() is a runtime data folder that differs per OS.
dest="models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
url="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf"
mkdir -p models/embeddings
curl -fL --retry 3 --retry-delay 5 -o "$dest" "$url" \
  || { echo "::error::embedder download failed from $url"; exit 1; }
# a model file starts with the GGUF magic; an error page saved under the name does not
[ "$(head -c 4 "$dest")" = "GGUF" ] \
  || { echo "::error::$dest is not a GGUF file — the download did not return the model"; exit 1; }
echo "embedder: $(( $(wc -c < "$dest") / 1048576 )) MiB at $dest"
