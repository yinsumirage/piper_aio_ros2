#!/usr/bin/env bash
set -euo pipefail

for command in awk basename grep ip readlink udevadm; do
  command -v "$command" >/dev/null || { echo "ERROR: missing command: $command" >&2; exit 1; }
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
conf=${PIPER_CAN_CONF:-$script_dir/../deploy/piper-can.conf}
[[ -f "$conf" ]] || { echo "ERROR: missing config: $conf" >&2; exit 1; }

bitrate=
declare -a serials=()
declare -a names=()
declare -A seen_serial=()
declare -A seen_name=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line=${line%%#*}
  read -r -a fields <<< "$line"
  ((${#fields[@]})) || continue
  if [[ ${fields[0]} == BITRATE=* ]]; then
    [[ ${#fields[@]} -eq 1 && -z "$bitrate" ]] || { echo 'ERROR: invalid or duplicate BITRATE' >&2; exit 1; }
    bitrate=${fields[0]#BITRATE=}
    continue
  fi
  [[ ${#fields[@]} -eq 2 ]] || { echo 'ERROR: expected SERIAL NAME' >&2; exit 1; }
  serial=${fields[0]}
  name=${fields[1]}
  [[ $serial =~ ^[0-9A-F]{24}$ ]] || { echo "ERROR: invalid serial: $serial" >&2; exit 1; }
  [[ $name =~ ^[a-z][a-z0-9_]*$ && ${#name} -le 15 ]] || { echo "ERROR: invalid interface name: $name" >&2; exit 1; }
  [[ -z ${seen_serial[$serial]:-} ]] || { echo "ERROR: duplicate serial: $serial" >&2; exit 1; }
  [[ -z ${seen_name[$name]:-} ]] || { echo "ERROR: duplicate interface name: $name" >&2; exit 1; }
  seen_serial[$serial]=1
  seen_name[$name]=1
  serials+=("$serial")
  names+=("$name")
done < "$conf"
[[ $bitrate == 1000000 && ${#serials[@]} -eq 4 ]] || { echo 'ERROR: expected BITRATE=1000000 and 4 mappings' >&2; exit 1; }

printf '%-24s %-13s %-8s %-9s %-8s\n' SERIAL STABLE RAW BITRATE STATE
status=0
for index in "${!serials[@]}"; do
  expected_serial=${serials[$index]}
  expected_name=${names[$index]}
  matches=()
  for net_path in /sys/class/net/*; do
    [[ -e "$net_path/device/driver" ]] || continue
    [[ $(basename "$(readlink -f "$net_path/device/driver")") == gs_usb ]] || continue
    actual_serial=$(udevadm info --query=property --path="$net_path" | awk -F= '$1 == "ID_SERIAL_SHORT" {print $2; exit}')
    [[ $actual_serial == "$expected_serial" ]] && matches+=("$(basename "$net_path")")
  done
  if [[ ${#matches[@]} -ne 1 ]]; then
    printf '%-24s %-13s %-8s %-9s %-8s\n' "$expected_serial" "$expected_name" missing unset MISSING
    status=1
    continue
  fi
  raw=${matches[0]}
  details=$(ip -details link show dev "$raw")
  actual_bitrate=$(awk '/ bitrate / {for (i=1; i<=NF; i++) if ($i == "bitrate") {print $(i+1); exit}}' <<< "$details")
  actual_bitrate=${actual_bitrate:-unset}
  if ip -o link show dev "$raw" | grep -q '<[^>]*UP'; then
    state=UP
  else
    state=DOWN
  fi
  printf '%-24s %-13s %-8s %-9s %-8s\n' "$expected_serial" "$expected_name" "$raw" "$actual_bitrate" "$state"
  [[ $raw == "$expected_name" && $actual_bitrate == "$bitrate" && $state == UP ]] || status=1
done
exit "$status"
