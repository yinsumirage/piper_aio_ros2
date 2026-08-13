#!/usr/bin/env bash
set -euo pipefail

action=${1:-start}
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
session=${PIPER_TELEOP_SESSION:-piper-teleop}
pane="$repo/scripts/teleop_pane.sh"
control="$repo/scripts/teleop_control.sh"

require_tmux() {
  command -v tmux >/dev/null || {
    echo 'ERROR: tmux is not installed' >&2
    exit 1
  }
}

case "$action" in
  start)
    require_tmux
    if tmux has-session -t "$session" 2>/dev/null; then
      exec tmux attach-session -t "$session"
    fi
    "$repo/scripts/can_status.sh"
    process_pattern='(/opt/ros/humble/bin/ros2 launch piper_aio_ros2 (four_arm|teleop)\.launch\.py|/piper_read_slave_joint |/piper_single_ctrl |/piper_aio_ros2/lib/piper_aio_ros2/teleop )'
    existing=$(pgrep -af "$process_pattern" || true)
    if [[ -n $existing ]]; then
      echo 'ERROR: existing four-arm/teleop processes are outside this tmux session:' >&2
      printf '%s\n' "$existing" >&2
      echo 'Stop them safely before starting the managed session.' >&2
      exit 3
    fi
    tmux new-session -d -s "$session" -n teleop "$pane driver"
    cleanup_partial_session() {
      tmux kill-session -t "$session" 2>/dev/null || true
    }
    trap cleanup_partial_session ERR
    tmux split-window -h -t "$session:teleop.0" "$pane teleop"
    tmux split-window -v -t "$session:teleop.1" "$pane control"
    tmux set-window-option -t "$session:teleop" main-pane-width 30%
    tmux select-layout -t "$session:teleop" main-vertical >/dev/null
    tmux set-option -t "$session" mouse on
    tmux set-window-option -t "$session:teleop" remain-on-exit on
    tmux set-window-option -t "$session:teleop" pane-border-status top
    tmux set-window-option -t "$session:teleop" pane-border-format ' #{pane_title} '
    tmux select-pane -t "$session:teleop.0" -T DRIVER
    tmux select-pane -t "$session:teleop.1" -T TELEOP
    tmux select-pane -t "$session:teleop.2" -T CONTROL
    tmux select-pane -t "$session:teleop.2"
    trap - ERR
    exec tmux attach-session -t "$session"
    ;;
  attach)
    require_tmux
    exec tmux attach-session -t "$session"
    ;;
  status)
    require_tmux
    tmux list-panes -t "$session:teleop" \
      -F '#{pane_index} #{pane_title}: #{pane_current_command} dead=#{pane_dead}' 2>/dev/null \
      || echo "tmux session '$session' is not running"
    "$control" status
    ;;
  stop)
    require_tmux
    "$control" stop || true
    if tmux has-session -t "$session" 2>/dev/null; then
      tmux kill-session -t "$session"
    fi
    ;;
  help|-h|--help)
    echo "usage: $0 {start|attach|status|stop}"
    ;;
  *)
    echo "unknown action: $action" >&2
    echo "usage: $0 {start|attach|status|stop}" >&2
    exit 2
    ;;
esac
