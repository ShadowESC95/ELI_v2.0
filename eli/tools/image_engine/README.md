# ELI Image Engine

Brand-neutral local image subsystem for ELI. It can generate procedural images, optionally use a local diffusion backend, generate plots/charts from data, create project visual profiles, score outputs, and index everything in a local SQLite visual memory.

## Install

```bash
cd "${ELI_PROJECT_ROOT:-$(pwd)}/eli/tools/image_engine"
python -m pip install -r requirements.txt
```

Optional local diffusion backend:

```bash
python -m pip install torch diffusers transformers accelerate safetensors
```

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

Outputs are written to:

```text
outputs/jobs/<job_id>/
  best.png
  manifest.json
  prompt_plan.json
  image_engine_000_*.png
  image_engine_000_*.json
  image_engine_contact_sheet.jpg
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

This creates a `project_visual_profile.json` containing project colors, tags, file samples, and style hints.

## Visual memory

Everything is indexed in:

```text
logs/image_index.sqlite
```

Search artifacts:

```bash
python -m image_engine find cyberpunk --type image
python -m image_engine find revenue --type plot
```

List jobs:

```bash
python -m image_engine jobs --limit 10
```

## Python API

```python
from image_engine import ImageEngine

engine = ImageEngine()

result = engine.run({
    "task": "generate_image",
    "prompt": "mythic AI operating system core",
    "intent": "poster",
    "count": 4,
    "memory": True
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

## Internal modules

```text
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

`visual_core.py` holds the procedural renderers. The service layer wraps it into ELI-style jobs, manifests, quality scores, and visual memory.
