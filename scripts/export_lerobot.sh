#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
exec conda run -n lerobot-piper --no-capture-output python -m piper_aio_ros2.export_lerobot "$@"
