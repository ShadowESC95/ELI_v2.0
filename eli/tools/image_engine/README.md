# ELI Image Engine

Brand-neutral local image subsystem for ELI. It can generate procedural images, optionally use a local diffusion backend, generate plots/charts from data, create project visual profiles, score outputs, and index everything in a local SQLite visual memory.

**What ELI itself uses.** The desktop app's Image Studio tab, and an image request typed in the desktop chat, go through `gui_bridge.generate_images()`, which renders with `visual_core` (procedural or diffusion, per the Backend chosen in Image Studio, defaulting to Settings → Identity → Image Render Backend) and writes the images to the engine's outputs folder. The job service described below — job folders, manifests, scoring, plots, project profiles and the SQLite visual memory (`find`, `jobs`) — is reached through its CLI and Python API only; ELI's chat, executor and web server do not call it.

## Install

The three dependencies (`pillow`, `numpy`, `matplotlib`) come with a full ELI install. In a bare environment:

```bash
cd "${ELI_PROJECT_ROOT:-$(pwd)}/eli/tools/image_engine"
python -m pip install -r requirements.txt
```

Optional local diffusion backend (also part of a full ELI install):

```bash
python -m pip install torch diffusers transformers accelerate safetensors
```

Weights are not shipped. Fetch a diffusers model explicitly — a deliberate network action, several GB — with `python -m eli.tools.image_engine.fetch_model segmind/SSD-1B models/image/ssd-1b` (those are the defaults). See `models/image/README.md`.

The commands below run from `eli/tools/image_engine` with ELI's `.venv` active (the package imports `eli`). From the repository root the same CLI is `python -m eli.tools.image_engine.image_engine`.

## Image generation

Old command style still works:

```bash
python -m image_engine --query "cinematic floating island with crystals" --count 6 --sheet
```

ELI-native command style:

```bash
python -m image_engine generate \
  --query "mythic AI OS command center, radiant interface, dark cinematic light" \
  --type poster \
  --style cinematic \
  --count 4 \
  --sheet \
  --name-from-prompt
```

`--backend procedural|diffusion|auto` (default `procedural`) with `--model <path>` picks the renderer; `--preset` takes a JSON file or a name from `presets/` (`chart_dark`, `cinematic_dark`, `fantasy_island`, `mythic_os`, `neon_poster`, `product_luxury`).

Outputs are written to ELI's artifacts folder (`artifacts/image_engine/` in a source checkout; `--out` overrides):

```text
artifacts/image_engine/outputs/jobs/<job_id>/
  best.png
  manifest.json
  prompt_plan.json
  image_engine_000_*.png
  image_engine_000_*.json
  image_engine_contact_sheet.jpg      # when more than one image
```

## Plot / chart generation

CSV:

```bash
python -m image_engine plot \
  --data ./projects/metrics.csv \
  --kind line \
  --x date \
  --y revenue,cost \
  --title "Revenue vs Cost"
```

Inline JSON:

```bash
python -m image_engine plot \
  --json '[{"month":"Jan","sales":12},{"month":"Feb","sales":19},{"month":"Mar","sales":15}]' \
  --kind bar \
  --x month \
  --y sales \
  --title "Monthly Sales"
```

Supported plot kinds:

```text
auto, line, bar, scatter, area, hist, histogram, pie
```

Supported data formats:

```text
.csv, .json, .jsonl, inline JSON list/object
```

## Project visual profile

```bash
python -m image_engine profile --project ./projects/my_project
```

This creates a `project_visual_profile.json` (in a new `profile_*` job folder) containing project colors, tags, file samples, and style hints.

## Visual memory

Everything the service produces is indexed in:

```text
artifacts/image_engine/logs/image_index.sqlite
```

(`--logs` or `--memory-db` move it; `--no-memory` skips indexing for one run.)

Search artifacts:

```bash
python -m image_engine find cyberpunk --type image
python -m image_engine find revenue --type plot
```

List jobs:

```bash
python -m image_engine jobs --limit 10
```

`python -m image_engine run '<JSON request>'` (or a path to a JSON file) runs a raw job request.

## Python API

```python
from eli.tools.image_engine.image_engine import ImageEngine

engine = ImageEngine()

result = engine.run({
    "task": "generate_image",
    "prompt": "mythic AI operating system core",
    "intent": "poster",
    "count": 4
})

plot = engine.run({
    "task": "generate_plot",
    "title": "CPU Load",
    "data": [
        {"t": "10:00", "load": 0.52},
        {"t": "10:05", "load": 0.71}
    ],
    "options": {"kind": "line", "x": "t", "y": "load"}
})
```

Indexing into visual memory is on by default (`EngineConfig.save_memory`).

## Internal modules

```text
eli/tools/image_engine/
  gui_bridge.py          what the desktop app calls (generate_images, model discovery, presets)
  runtime_paths.py       where outputs, logs and the index live
  fetch_model.py         explicit diffusers weight download
  config/image_engine.json
  presets/
  image_engine/
    cli.py
    service.py
    contracts.py
    memory.py
    prompt_compiler.py
    project_analyzer.py
    plotting.py
    quality.py
    visual_core.py
```

`visual_core.py` holds the procedural renderers and the diffusion backend. The service layer wraps it into ELI-style jobs, manifests, quality scores, and visual memory.
