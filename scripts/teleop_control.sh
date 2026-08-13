#!/usr/bin/env bash
# shellcheck disable=SC1091
set -eo pipefail

action=${1:-help}
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash
source "$repo/install/setup.bash"
export ROS_DOMAIN_ID=${PIPER_ROS_DOMAIN_ID:-231}
export ROS_LOCALHOST_ONLY=1
cd "$repo"

call_enable() {
  local side=$1 request=$2 output
  if ! output=$(timeout 10 ros2 service call "/follower_${side}/enable_srv" \
      piper_msgs/srv/Enable "{enable_request: ${request}}" 2>&1); then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
  grep -Eqi 'enable_response[=:][[:space:]]*true' <<< "$output"
}

call_arm() {
  local request=$1 output
  if ! output=$(timeout 10 ros2 service call /dual_arm_teleop/arm \
      std_srvs/srv/SetBool "{data: ${request}}" 2>&1); then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
  grep -Eqi 'success[=:][[:space:]]*true' <<< "$output"
}

enable_both() {
  if call_enable left true && call_enable right true; then
    echo 'Both followers enabled. Masters must remain still before arm.'
    return 0
  fi
  echo 'Enable failed; rolling both followers back to disabled.' >&2
  call_enable left false >/dev/null 2>&1 || true
  call_enable right false >/dev/null 2>&1 || true
  return 1
}

disable_both() {
  local result=0
  call_enable left false || result=1
  call_enable right false || result=1
  return "$result"
}

case "$action" in
  status)
    ./scripts/can_status.sh || true
    echo '--- ROS nodes ---'
    timeout 5 ros2 node list 2>/dev/null | sort || true
    echo '--- teleop parameters ---'
    for parameter in publish_hz alignment_speed_percent speed_percent \
      alignment_timeout_sec alignment_settle_sec; do
      timeout 5 ros2 param get /dual_arm_teleop "$parameter" 2>/dev/null || true
    done
    ;;
  enable)
    enable_both
    ;;
  arm)
    echo 'Arming starts real 100% frozen-target alignment if followers are enabled.'
    call_arm true
    ;;
  disarm)
    call_arm false
    ;;
  disable)
    disable_both
    ;;
  stop)
    call_arm false || true
    disable_both
    ;;
  help|-h|--help)
    echo "usage: $0 {status|enable|arm|disarm|disable|stop}"
    ;;
  *)
    echo "unknown action: $action" >&2
    echo "usage: $0 {status|enable|arm|disarm|disable|stop}" >&2
    exit 2
    ;;
esac
