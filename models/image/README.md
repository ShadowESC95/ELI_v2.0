Local image diffusion models for ELI belong here.

Recommended:
- Put a full local model folder here, for example an SDXL or FLUX directory containing `model_index.json`.
- Or put a single-file checkpoint here such as `your_model.safetensors` or `your_model.ckpt`.

Examples:
- `models/image/sdxl-base-1.0/`
- `models/image/flux-dev/`
- `models/image/juggernaut-xl.safetensors`

How ELI uses this:
- Open `ELI -> Settings -> Identity -> Image Render Backend`
- Set `Backend` to `diffusion`
- Choose or paste the model path
- Then use `Image Studio` or an explicit chat image request

Notes:
- Text LoRA adapter files are not valid image checkpoints for this feature.
- Photoreal / 3D-style output requires a real diffusion model here.
