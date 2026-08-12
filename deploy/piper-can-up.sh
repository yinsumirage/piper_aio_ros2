#!/usr/bin/env bash
set -euo pipefail

((EUID == 0)) || { echo 'ERROR: CAN configuration requires root' >&2; exit 1; }
for command in awk basename grep ip readlink udevadm; do
  command -v "$command" >/dev/null || { echo "ERROR: missing command: $command" >&2; exit 1; }
done

conf=${PIPER_CAN_CONF:-/etc/piper/piper-can.conf}
[[ -f "$conf" ]] || { echo "ERROR: missing config: $conf" >&2; exit 1; }

bitrate=
declare -a serials=()
declare -a names=()
declare -A seen_serial=()
declare -A seen_name=()
line_no=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line_no=$((line_no + 1))
  line=${line%%#*}
  read -r -a fields <<< "$line"
  ((${#fields[@]})) || continue
  if [[ ${fields[0]} == BITRATE=* ]]; then
    [[ ${#fields[@]} -eq 1 && -z "$bitrate" ]] || { echo "ERROR: invalid BITRATE at $conf:$line_no" >&2; exit 1; }
    bitrate=${fields[0]#BITRATE=}
    continue
  fi
  [[ ${#fields[@]} -eq 2 ]] || { echo "ERROR: expected SERIAL NAME at $conf:$line_no" >&2; exit 1; }
  serial=${fields[0]}
  name=${fields[1]}
  [[ $serial =~ ^[0-9A-F]{24}$ ]] || { echo "ERROR: invalid serial: $serial" >&2; exit 1; }
  [[ $name =~ ^[a-z][a-z0-9_]*$ ]] || { echo "ERROR: invalid interface name: $name" >&2; exit 1; }
  ((${#name} <= 15)) || { echo "ERROR: interface name exceeds 15 characters: $name" >&2; exit 1; }
  [[ -z ${seen_serial[$serial]:-} ]] || { echo "ERROR: duplicate serial: $serial" >&2; exit 1; }
  [[ -z ${seen_name[$name]:-} ]] || { echo "ERROR: duplicate interface name: $name" >&2; exit 1; }
  seen_serial[$serial]=1
  seen_name[$name]=1
  serials+=("$serial")
  names+=("$name")
done < "$conf"
[[ $bitrate == 1000000 ]] || { echo "ERROR: BITRATE must be 1000000, got ${bitrate:-unset}" >&2; exit 1; }
[[ ${#serials[@]} -eq 4 ]] || { echo "ERROR: expected 4 CAN mappings, got ${#serials[@]}" >&2; exit 1; }

# Validate every device before changing any interface.
for index in "${!serials[@]}"; do
  name=${names[$index]}
  expected_serial=${serials[$index]}
  [[ -e /sys/class/net/$name ]] || { echo "ERROR: missing interface: $name" >&2; exit 1; }
  [[ -e /sys/class/net/$name/device/driver ]] || { echo "ERROR: $name has no driver" >&2; exit 1; }
  driver=$(basename "$(readlink -f "/sys/class/net/$name/device/driver")")
  [[ $driver == gs_usb ]] || { echo "ERROR: $name uses $driver, expected gs_usb" >&2; exit 1; }
  actual_serial=$(udevadm info --query=property --path="/sys/class/net/$name" | awk -F= '$1 == "ID_SERIAL_SHORT" {print $2; exit}')
  [[ $actual_serial == "$expected_serial" ]] || { echo "ERROR: $name serial is ${actual_serial:-unset}, expected $expected_serial" >&2; exit 1; }
done

for index in "${!names[@]}"; do
  name=${names[$index]}
  details=$(ip -details link show dev "$name")
  current_bitrate=$(awk '/ bitrate / {for (i=1; i<=NF; i++) if ($i == "bitrate") {print $(i+1); exit}}' <<< "$details")
  if [[ $current_bitrate == "$bitrate" ]] && ip -o link show dev "$name" | grep -q '<[^>]*UP'; then
    echo "$name already UP at $bitrate bit/s"
    continue
  fi
  ip link set dev "$name" down
  ip link set dev "$name" type can bitrate "$bitrate"
  ip link set dev "$name" up
  echo "$name is UP at $bitrate bit/s"
done
