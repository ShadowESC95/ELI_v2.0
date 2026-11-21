Local image diffusion models for ELI belong here.

Recommended:
- Put a full local model folder here, for example an SDXL or FLUX directory containing `model_index.json`.
- Or put a single-file checkpoint here such as `your_model.safetensors` or `your_model.ckpt`.
- Or fetch one explicitly (a deliberate download of several GB; these are the defaults):
  `python -m eli.tools.image_engine.fetch_model segmind/SSD-1B models/image/ssd-1b`

Examples:
- `models/image/sdxl-base-1.0/`
- `models/image/flux-dev/`
- `models/image/juggernaut-xl.safetensors`

How ELI uses this:
- Open `ELI -> Settings -> Identity -> Image Render Backend`
- Set `Backend` to `diffusion` (`auto` also renders with diffusion once a model path is set)
- Choose or paste the model path (`Browse…`, or `Detect Local Models`, which looks here, in ELI's models folder and in `~/models` for `model_index.json` folders and `.safetensors` / `.ckpt` files)
- Then use `Image Studio` or an explicit chat image request

Notes:
- Text LoRA adapter files are not valid image checkpoints for this feature.
- Photoreal / 3D-style output requires a real diffusion model here.
- A model folder without downloaded weights is reported as such; ELI does not quietly fall back to a procedural image.
- While a diffusion model renders, the chat model is unloaded and reloaded afterwards, since both may not fit in GPU memory together.
