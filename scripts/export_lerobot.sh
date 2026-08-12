#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_name="${LEROBOT_ENV_NAME:-lerobot-piper}"
if [[ -n "${CONDA_EXE:-}" && -x "$CONDA_EXE" ]]; then
  conda_exe="$CONDA_EXE"
elif command -v conda >/dev/null 2>&1; then
  conda_exe="$(command -v conda)"
elif [[ -x /home/engram/miniconda3/bin/conda ]]; then
  conda_exe=/home/engram/miniconda3/bin/conda
else
  echo "conda executable not found" >&2
  exit 2
fi

cd "$root"
exec "$conda_exe" run -n "$env_name" --no-capture-output \
  python -m piper_aio_ros2.export_lerobot "$@"
