#!/usr/bin/env bash
set -euo pipefail
exec ros2 run piper_aio_ros2 camera_status "$@"
