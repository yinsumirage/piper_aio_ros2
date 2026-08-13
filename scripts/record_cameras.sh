#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "usage: $0 OUTPUT_BAG_DIR [DURATION_SECONDS] [CAMERA_CONFIG]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$1"
duration="${2:-}"
config="$root/config/camera_record_topics.yaml"
camera_config="${3:-$root/config/cameras.yaml}"
[[ ! -e "$output" ]] || { echo "refusing to overwrite: $output" >&2; exit 2; }

# This enforces serial presence/uniqueness/current device membership and the
# exact topic/type/encoding/shape/publisher contract. Rate/gap stay warnings.
ros2 run piper_aio_ros2 camera_status --config "$camera_config" --sample-seconds 3
ros2 run piper_aio_ros2 bag_preflight --config "$config" --output-dir "$output"
mapfile -t topics < <(ros2 run piper_aio_ros2 bag_preflight --config "$config" --list-topics)

record=(ros2 bag record --output "$output" --compression-mode file --compression-format zstd "${topics[@]}")
if [[ -n "$duration" ]]; then
  [[ "$duration" =~ ^[1-9][0-9]*$ ]] || { echo "duration must be a positive integer" >&2; exit 2; }
  set +e
  timeout --signal=INT --kill-after=10s "${duration}s" "${record[@]}"
  rc=$?
  set -e
  [[ $rc -eq 0 || $rc -eq 124 ]] || exit "$rc"
else
  echo "recording until Ctrl+C: $output" >&2
  "${record[@]}"
fi

ros2 run piper_aio_ros2 bag_inspect "$output" --config "$config"
