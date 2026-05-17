# ELI Image Engine v2 Clean Install

This zip intentionally contains no `__pycache__` files.

Install from your existing tool directory:

```bash
cd "${ELI_PROJECT_ROOT:-$(pwd)}/eli/tools/image_engine"
unzip -o ~/Downloads/image_engine_eli_visual_subsystem_v2_clean.zip -d .
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete
python -m pip install -r requirements.txt
python -m image_engine --help
```

Expected CLI commands:

```text
generate
plot
profile
find
jobs
run
```
