# Source from ELI launchers:  # shellcheck source=scripts/eli_isolate_env.sh
#   ROOT=...; # shellcheck disable=SC1091
#   source "$ROOT/scripts/eli_isolate_env.sh"
#   eli_isolate_env "$ROOT"
#
# Forces THIS checkout's tree + .venv, and strips foreign ELI portable paths
# from PYTHONPATH / VIRTUAL_ENV so a leftover 2.4.23 env cannot shadow 2.4.24+.
eli_isolate_env() {
  local root="${1:?eli_isolate_env requires install root}"
  root="$(cd "$root" && pwd)"

  unset VIRTUAL_ENV PYTHONHOME 2>/dev/null || true
  # Do not inherit another checkout's data/config dirs.
  unset ELI_PROJECT_ROOT ELI_DATA_DIR ELI_CONFIG_DIR ELI_MODELS_DIR ELI_CACHE_DIR 2>/dev/null || true

  export ELI_PROJECT_ROOT="$root"
  export ELI_DATA_DIR="${ELI_DATA_DIR:-$root/artifacts}"
  export ELI_CONFIG_DIR="${ELI_CONFIG_DIR:-$root/config}"
  export ELI_MODELS_DIR="${ELI_MODELS_DIR:-$root/models}"
  export ELI_CACHE_DIR="${ELI_CACHE_DIR:-$root/cache}"

  # PYTHONPATH: this root ONLY (never append prior paths — they pull old trees).
  export PYTHONPATH="$root"

  # Drop other ELI .venv/bin entries from PATH so `python` / `pip` cannot leak.
  if [ -n "${PATH:-}" ]; then
    local _new_path="" _part
    local _ifs="$IFS"
    IFS=':'
    # shellcheck disable=SC2086
    for _part in $PATH; do
      IFS="$_ifs"
      case "$_part" in
        */ELI_v2-*/.venv/bin|*/ELI_v2-*/.venv/Scripts|*/ELI_MKXI*/.venv/bin)
          if [ "$_part" = "$root/.venv/bin" ] || [ "$_part" = "$root/.venv/Scripts" ]; then
            _new_path="${_new_path:+$_new_path:}$_part"
          fi
          ;;
        *)
          _new_path="${_new_path:+$_new_path:}$_part"
          ;;
      esac
      IFS=':'
    done
    IFS="$_ifs"
    export PATH="$_new_path"
  fi

  # Prefer this venv on PATH when present.
  if [ -d "$root/.venv/bin" ]; then
    export PATH="$root/.venv/bin:$PATH"
  elif [ -d "$root/.venv/Scripts" ]; then
    export PATH="$root/.venv/Scripts:$PATH"
  fi
}

# True when this install's Python environment can run ELI. A system upgrade that replaces
# the Python it was built with leaves it starting and finding no packages, and every launch
# ended in "No module named ...". Say what happened, mend it when that needs no download
# (scripts/eli_env.py repair), and otherwise say what rebuilds it.
eli_env_ready() {
  local root="${1:?eli_env_ready requires install root}"
  local py="$root/.venv/bin/python"
  if [ -x "$py" ] && "$py" -c 'import os,sys;sys.exit(0 if any("site-packages" in p and os.path.isdir(p) and os.path.realpath(p).startswith(os.path.realpath(sys.prefix)) for p in sys.path) else 1)' >/dev/null 2>&1; then
    return 0
  fi
  local helper="${ELI_ENV_HELPER:-$root/scripts/eli_env.py}" any_py="" cand
  for cand in python3 python "$py"; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys' >/dev/null 2>&1; then
      any_py="$cand"
      break
    fi
  done
  if [ -n "$any_py" ] && [ -f "$helper" ]; then
    "$any_py" "$helper" repair "$root" && return 0
  else
    echo "[ELI] ELI's Python environment cannot start. Run  bash install.sh  in $root  to rebuild it."
    echo "[ELI] Your models, memory and settings are not touched."
  fi
  command -v notify-send >/dev/null 2>&1 && \
    notify-send "ELI" "ELI's Python environment needs rebuilding. In $root run: bash install.sh" 2>/dev/null || true
  return 1
}
