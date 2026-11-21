# ELI Image Engine v2 Clean Install

The engine ships inside ELI at `eli/tools/image_engine/`; there is no separate archive to
unpack, and a full ELI install already has its dependencies.

To reinstall its dependencies and check the CLI, run from that folder with ELI's `.venv`
active (the package imports `eli`):

```bash
cd "${ELI_PROJECT_ROOT:-$(pwd)}/eli/tools/image_engine"
bash install_check.sh
```

`install_check.sh` copies the `image_engine/` package to `image_engine_backup_<timestamp>/`
beside it, removes stale `__pycache__` / `.pyc` files, installs `requirements.txt`, prints
the CLI help and checks that `generate`, `plot` and `find` are among the subcommands.
Delete the backup folder afterwards: git does not ignore it, and the claims suite compiles
every `eli/**/*.py`.

The same steps by hand:

```bash
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete
python -m pip install -r requirements.txt
python -m image_engine --help
```

A leading flag is read in the old `generate` style, so `--help` prints the options of
`generate`; `python -m image_engine plot --help` and so on show the others.

Expected CLI commands:

```text
generate
plot
profile
find
jobs
run
```
