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
