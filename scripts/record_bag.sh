#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 OUTPUT_BAG_DIR [STREAM_CONFIG]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$1"
config="${2:-$root/config/record_topics.yaml}"
[[ ! -e "$output" ]] || { echo "refusing to overwrite: $output" >&2; exit 2; }

ros2 run piper_aio_ros2 bag_preflight --config "$config" --output-dir "$output"
mapfile -t topics < <(ros2 run piper_aio_ros2 bag_preflight --config "$config" --list-topics)
(( ${#topics[@]} > 0 )) || { echo "empty topic whitelist" >&2; exit 2; }
mkdir -p -- "$(dirname -- "$output")"

exec ros2 bag record \
  --output "$output" \
  --compression-mode message \
  --compression-format zstd \
  "${topics[@]}"
