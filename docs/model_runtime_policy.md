# ELI Model Runtime Policy

ELI separates runtime models, trainable bases, and adapters.

## Runtime-selectable models

Only `.gguf` files are selectable by `elix`.

Allowed runtime locations:

- `models/*.gguf`
- `models/gguf/runtime/*.gguf`
- `models/gguf/eli_phi/*.gguf`

## Non-runtime model assets

These are not selectable by the GGUF runtime picker:

- `models/hf/**`
- `models/lora/**`
- `models/embeddings/**`

## Phi rule

Phi training assets stay in:

- `models/hf/Phi-3-mini-4k-instruct`
- `models/lora/adapters/eli-lora-adapter-phi3*`

Phi only becomes a normal runtime model after it is merged/converted/quantized into GGUF and placed under:

- `models/gguf/eli_phi/*.gguf`

The runtime picker must not confuse HF bases, LoRA adapters, embeddings, or code with GGUF runtime models.
