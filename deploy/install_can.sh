#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install_can.sh [--dry-run] [--activate] [--enable-service]

  --dry-run         Validate and print generated files; write nothing.
  --activate        Rename connected, DOWN gs_usb interfaces and start CAN only.
  --enable-service  Enable piper-can.service for future boots (never starts ROS).
EOF
}

dry_run=false
activate=false
enable_service=false
while (($#)); do
  case "$1" in
    --dry-run) dry_run=true ;;
    --activate) activate=true ;;
    --enable-service) enable_service=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ! $dry_run && ((EUID != 0)); then
  echo 'ERROR: installation requires root; use --dry-run for an unprivileged check' >&2
  exit 1
fi

for command in awk basename grep install ip mktemp readlink systemctl udevadm; do
  command -v "$command" >/dev/null || { echo "ERROR: missing command: $command" >&2; exit 1; }
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
conf=${PIPER_CAN_CONF:-$script_dir/piper-can.conf}
up_script=$script_dir/piper-can-up.sh
service_file=$script_dir/piper-can.service
for file in "$conf" "$up_script" "$service_file"; do
  [[ -f "$file" ]] || { echo "ERROR: missing file: $file" >&2; exit 1; }
done

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
  [[ $serial =~ ^[0-9A-F]{24}$ ]] || { echo "ERROR: invalid serial at $conf:$line_no: $serial" >&2; exit 1; }
  [[ $name =~ ^[a-z][a-z0-9_]*$ ]] || { echo "ERROR: invalid interface name at $conf:$line_no: $name" >&2; exit 1; }
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

tmp_dir=$(mktemp -d /tmp/piper-can-install.XXXXXX)
trap 'rm -rf "$tmp_dir"' EXIT
rules=$tmp_dir/70-piper-can.rules
{
  echo '# Generated from piper-can.conf by install_can.sh; do not edit.'
  for index in "${!serials[@]}"; do
    printf 'SUBSYSTEM=="net", ACTION=="add", KERNEL=="can*", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="606f", ATTRS{serial}=="%s", NAME="%s"\n' \
      "${serials[$index]}" "${names[$index]}"
  done
} > "$rules"

declare -a current_ifaces=()
if $activate; then
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
    [[ ${#matches[@]} -eq 1 ]] || { echo "ERROR: serial $expected_serial expected once, found ${#matches[@]}" >&2; exit 1; }
    current=${matches[0]}
    current_ifaces+=("$current")
    if [[ $current != "$expected_name" ]]; then
      [[ ! -e /sys/class/net/$expected_name ]] || { echo "ERROR: target interface already exists: $expected_name" >&2; exit 1; }
      if ip -o link show dev "$current" | grep -q '<[^>]*UP'; then
        echo "ERROR: refusing to rename UP interface $current" >&2
        exit 1
      fi
    fi
  done
fi

echo '== validated CAN configuration =='
printf 'BITRATE=%s\n' "$bitrate"
for index in "${!serials[@]}"; do
  printf '%s -> %s\n' "${serials[$index]}" "${names[$index]}"
done
echo '== generated /etc/udev/rules.d/70-piper-can.rules =='
cat "$rules"
echo '== installation targets =='
printf '%s\n' \
  "$conf -> /etc/piper/piper-can.conf (0644)" \
  "$rules -> /etc/udev/rules.d/70-piper-can.rules (0644)" \
  "$up_script -> /usr/local/sbin/piper-can-up (0755)" \
  "$service_file -> /etc/systemd/system/piper-can.service (0644)"
if $activate; then
  for index in "${!serials[@]}"; do
    printf 'activate: %s -> %s\n' "${current_ifaces[$index]}" "${names[$index]}"
  done
fi
$enable_service && echo 'enable: piper-can.service (without ROS or arm enable)'

if $dry_run; then
  echo 'DRY RUN: no files, interfaces, udev state, or systemd state changed.'
  exit 0
fi

install -d -m 0755 /etc/piper /etc/udev/rules.d /usr/local/sbin /etc/systemd/system
install -m 0644 "$conf" /etc/piper/piper-can.conf
install -m 0644 "$rules" /etc/udev/rules.d/70-piper-can.rules
install -m 0755 "$up_script" /usr/local/sbin/piper-can-up
install -m 0644 "$service_file" /etc/systemd/system/piper-can.service
systemctl daemon-reload
udevadm control --reload-rules

if $activate; then
  for index in "${!serials[@]}"; do
    current=${current_ifaces[$index]}
    expected=${names[$index]}
    [[ $current == "$expected" ]] || ip link set dev "$current" name "$expected"
  done
  systemctl restart piper-can.service
fi
$enable_service && systemctl enable piper-can.service

echo 'Installed CAN network configuration. No ROS node or arm enable command was run.'
