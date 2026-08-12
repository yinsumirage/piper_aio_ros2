#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_name="${LEROBOT_ENV_NAME:-lerobot-piper}"
python_version="${LEROBOT_PYTHON_VERSION:-3.12}"
conda_channel="${LEROBOT_CONDA_CHANNEL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge}"
pip_index="${LEROBOT_PYPI_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
  conda_exe="$CONDA_EXE"
elif command -v conda >/dev/null 2>&1; then
  conda_exe="$(command -v conda)"
elif [[ -x /home/engram/miniconda3/bin/conda ]]; then
  conda_exe=/home/engram/miniconda3/bin/conda
else
  echo "conda executable not found" >&2
  exit 2
fi

report() {
  "$conda_exe" run -n "$env_name" --no-capture-output python -c '
import json
import platform
from importlib.metadata import version

import h5py
import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset

lerobot_version = version("lerobot")
print(json.dumps({
    "python": platform.python_version(),
    "lerobot": lerobot_version,
    "h5py": h5py.__version__,
    "torch": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_device_count": torch.cuda.device_count(),
    "LeRobotDataset_import": True,
}, sort_keys=True))
if lerobot_version != "0.6.0":
    raise SystemExit("expected lerobot 0.6.0")
'
}

env_path="$("$conda_exe" env list | awk -v name="$env_name" '$1 == name {print $NF; exit}')"
if [[ -n "$env_path" ]]; then
  echo "Conda environment already exists; no packages will be installed: $env_path"
  report
  exit 0
fi

echo "Creating Conda environment: $env_name"
"$conda_exe" create -y -n "$env_name" --override-channels -c "$conda_channel" \
  "python=$python_version" pip
"$conda_exe" run -n "$env_name" --no-capture-output python -m pip install \
  --index-url "$pip_index" -r "$root/requirements/lerobot.txt"
report
