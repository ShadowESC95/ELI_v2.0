# ELI Model Runtime Policy

ELI separates runtime models, trainable bases, and adapters.

## Runtime-selectable models

Only `.gguf` files are selectable. Each place that lists them searches its own folders:

- `bin/elix`, the terminal picker: `models/*.gguf` and `models/<folder>/*.gguf` (one level down;
  `ELIX_MODEL_DIR` replaces `models/` for these two), plus everything under
  `models/gguf/runtime/` and `models/gguf/eli_phi/`.
- The app's model lists (the startup window's GGUF list and the Settings models table,
  `discover_gguf_models` in `eli/gui/eli_pro_audio_gui_v2_0.py`): every `.gguf`, at any depth,
  under the program's own `models/` and `<config dir>/models`. Settings → Model's "Bundled GGUF"
  list shows the ones under `models/gguf/base/`.
- Model discovery for the hardware recommendation, the first-run wizard and the terminal setup
  (`eli/gui/app.py --setup`, which also offers the saved model wherever it is)
  (`hardware_profile.discover_models`): every `.gguf`, at any depth, under `paths.models_dir()`
  (`ELI_MODELS_DIR`, else `models/` in a source checkout and `<data dir>/models` in an install,
  where `eli.core.model_download` saves) and the program's own `models/`. Until 2.5.36 it searched
  only the program's `models/`.

## Non-runtime model assets

These are not selectable by the GGUF runtime picker:

- `models/hf/**`
- `models/lora/**`
- `models/embeddings/**`

`bin/elix` skips them by folder (any `hf/`, `lora/`, `adapters/` or `embeddings/` folder) and any
file name containing `embed`. Model discovery skips the embedder by folder and name
(`hardware_profile._is_embedder_path`). Both the app and model discovery also go by the file's
own metadata (`model_load_diagnostics.not_a_chat_model`, below): model discovery leaves such a file
out, and the startup window lists it as "not a chat model" and does not let it be picked.

## Phi rule

Phi training assets stay in:

- `models/hf/Phi-3-mini-4k-instruct`
- `models/lora/adapters/eli-lora-adapter-phi3*`

Phi only becomes a normal runtime model after it is merged, converted and quantized into a GGUF.
`training/merge_and_convert.py` does all three for an adapter and installs the result in `models/`
(`--models-dir`); `bin/elix` also looks in:

- `models/gguf/eli_phi/*.gguf`

The runtime picker must not confuse HF bases, LoRA adapters, embeddings, or code with GGUF runtime models.

## Any GGUF

Nothing here is written for one model. What ELI needs from a model it reads from the file or
measures on the loaded model:

- **Split files** (`name-00001-of-00003.gguf`): one model. The app's lists and model discovery show
  the first part, sizing and offload count every part (`core/gguf_sizes.py`), and a load that fails
  names any part missing beside the first before anything else
  (`model_load_diagnostics.explain_load_failure`).
- **Not a language model**, read from the file's metadata: a speculative-decoding draft head, a
  vision projector (architecture `clip`), an embedding model (it pools its output) or a file with
  no tokenizer (an image, video or audio model) is not offered for chat
  (`model_load_diagnostics.not_a_chat_model`).
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
- **Vision**: any vision model with a projector, through llama.cpp's generic handler
  (`MTMDChatHandler`; a build without it falls back to the named handlers, chosen by architecture,
  then file name). The projector is recognised by its metadata and paired with its model by name,
  or with the only language model beside it (`perception/vision.py`).

## The runtime

`packaging/llama_source.py` builds every bundle and GPU pack from upstream llama-cpp-python with a
newer llama.cpp, so architectures upstream's release cannot load do load. Its version is in
`packaging/llama_cpp_constraints.txt` (0.3.36.1). A model newer than the runtime fails with an
explanation from `explain_load_failure`, which names the architecture. Installs from source take
upstream's release from PyPI, so they load fewer of the newest architectures until upstream catches
up. Every install source asks for 0.3.35 or later (the `requirements*.txt` files, the
`pyproject.toml` `llm` extra, `install.sh`, `install.ps1`): the first release whose llama.cpp can
simulate a load, which the load planner needs (`core/load_plan.py`); on an older build it would
only estimate.
