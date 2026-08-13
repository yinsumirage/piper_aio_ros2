#!/usr/bin/env bash
# shellcheck disable=SC1091
set -eo pipefail

role=${1:-}
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash
source "$repo/install/setup.bash"
export ROS_DOMAIN_ID=${PIPER_ROS_DOMAIN_ID:-231}
export ROS_LOCALHOST_ONLY=1
cd "$repo"

case "$role" in
  driver)
    exec ros2 launch piper_aio_ros2 four_arm.launch.py
    ;;
  teleop)
    exec ros2 launch piper_aio_ros2 teleop.launch.py
    ;;
  control)
    printf '\nPiper teleop control (startup never enables or arms hardware)\n\n'
    printf '  ./scripts/teleop_control.sh status\n'
    printf '  ./scripts/teleop_control.sh enable   # explicit hardware enable\n'
    printf '  ./scripts/teleop_control.sh arm      # starts frozen-target alignment\n'
    printf '  ./scripts/teleop_control.sh stop     # disarm, then disable both followers\n\n'
    printf 'Mouse is enabled: click a pane to switch; Ctrl-b d detaches tmux.\n\n'
    exec bash --norc -i
    ;;
  *)
    echo "usage: $0 {driver|teleop|control}" >&2
    exit 2
    ;;
esac
