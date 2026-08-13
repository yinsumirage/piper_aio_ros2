#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"

bash -n scripts/teleop_session.sh scripts/teleop_control.sh scripts/teleop_pane.sh
[[ $(bash scripts/teleop_session.sh help) == *'{start|attach|status|stop}'* ]]
[[ $(bash scripts/teleop_control.sh help) == *'{status|enable|arm|disarm|disable|stop}'* ]]
if bash scripts/teleop_pane.sh invalid >/dev/null 2>&1; then
  echo 'teleop_pane accepted an invalid role' >&2
  exit 1
fi
grep -q 'startup never enables or arms hardware' scripts/teleop_pane.sh
grep -q 'piper_single_ctrl' scripts/teleop_session.sh
grep -q 'main-pane-width 30%' scripts/teleop_session.sh
grep -q 'call_arm false' scripts/teleop_control.sh
grep -q 'disable_both' scripts/teleop_control.sh
echo 'teleop tmux/control script tests: PASS'
