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

## Any GGUF

Nothing here is written for one model. What ELI needs from a model it reads from the file or
measures on the loaded model:

- **Split files** (`name-00001-of-00003.gguf`): one model. The picker lists the first part, sizing
  and offload count every part, and a missing part is named before the load (`core/gguf_sizes.py`).
- **Not a language model**: a file with no tokenizer (a projector, an embedder's weights, an image
  or speech model) is not offered for chat (`model_load_diagnostics.not_a_chat_model`).
- **Chat template**: the model's own, with what it does to the system turn found by rendering it
  (`cognition/chat_template.py`). Control tokens to strip come from its vocabulary
  (`model_output_tokens.learn_control_tokens`).
- **Choosing actions**: each model file is quizzed once in the background with ordinary remarks and
  ordinary commands, through the same resolver it would use (`cognition/action_trust.py`). A model
  that picks actions for talk gets the rules and chat only, and never the 165-action resolver.
  The verdict is kept in `runtime/action_trust.json`. `ELI_MODEL_CHOOSES_ACTIONS=1` or `0` decides
  it by hand.
- **Not stopping**: a reply that reads as going nowhere is ended (`gguf_inference.reads_as_runaway`,
  measured on real replies; the numbers are beside the constant). A reply can still run to the
  budget without tripping it. It is not a judgement of quality: a broken quantisation can still
  write nonsense that varies.
- **Vision**: any vision model with a projector, through llama.cpp's generic handler. The projector
  is recognised by its metadata and paired with its model by name (`perception/vision.py`).

## The runtime

`packaging/llama_source.py` builds every bundle and GPU pack from upstream llama-cpp-python with a
newer llama.cpp, so architectures upstream's release cannot load do load. Its version is in
`packaging/llama_cpp_constraints.txt`. A model newer than the runtime fails with an explanation
from `explain_load_failure`, which names the architecture. Installs from source take upstream's
release from PyPI, so they load fewer of the newest architectures until upstream catches up.
