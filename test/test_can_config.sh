#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
installer=$repo/deploy/install_can.sh
tmp_dir=$(mktemp -d /tmp/piper-can-test.XXXXXX)
trap 'rm -rf "$tmp_dir"' EXIT

output=$(PIPER_CAN_CONF=$repo/deploy/piper-can.conf "$installer" --dry-run)
[[ $(grep -c '^SUBSYSTEM=="net"' <<< "$output") -eq 4 ]]
grep -q '002300374148570D20343133.*can_slave_l' <<< "$output"
grep -q '003400204148570A20343133.*can_slave_r' <<< "$output"
grep -q '004400314148570C20343133.*can_master_l' <<< "$output"
grep -q '003B00234148570A20343133.*can_master_r' <<< "$output"
grep -q '/etc/udev/rules.d/70-piper-can.rules' <<< "$output"
grep -q '/usr/local/sbin/piper-can-up' <<< "$output"
grep -q '/etc/systemd/system/piper-can.service' <<< "$output"
grep -q 'DRY RUN: no files, interfaces, udev state, or systemd state changed.' <<< "$output"

if ((EUID != 0)); then
  set +e
  root_output=$(PIPER_CAN_CONF=$repo/deploy/piper-can.conf "$installer" 2>&1)
  root_rc=$?
  set -e
  [[ $root_rc -ne 0 ]]
  grep -q 'installation requires root' <<< "$root_output"
else
  echo 'root gate check skipped because test already runs as root'
fi

expect_fail() {
  local conf=$1
  if PIPER_CAN_CONF=$conf "$installer" --dry-run >/dev/null 2>&1; then
    echo "ERROR: invalid config passed: $conf" >&2
    exit 1
  fi
}

cat > "$tmp_dir/duplicate-serial.conf" <<'EOF'
BITRATE=1000000
002300374148570D20343133 can_slave_l
002300374148570D20343133 can_slave_r
004400314148570C20343133 can_master_l
003B00234148570A20343133 can_master_r
EOF
expect_fail "$tmp_dir/duplicate-serial.conf"

cat > "$tmp_dir/duplicate-name.conf" <<'EOF'
BITRATE=1000000
002300374148570D20343133 can_slave_l
003400204148570A20343133 can_slave_l
004400314148570C20343133 can_master_l
003B00234148570A20343133 can_master_r
EOF
expect_fail "$tmp_dir/duplicate-name.conf"

cat > "$tmp_dir/long-name.conf" <<'EOF'
BITRATE=1000000
002300374148570D20343133 can_name_is_longer
003400204148570A20343133 can_slave_r
004400314148570C20343133 can_master_l
003B00234148570A20343133 can_master_r
EOF
expect_fail "$tmp_dir/long-name.conf"

cat > "$tmp_dir/bad-bitrate.conf" <<'EOF'
BITRATE=500000
002300374148570D20343133 can_slave_l
003400204148570A20343133 can_slave_r
004400314148570C20343133 can_master_l
003B00234148570A20343133 can_master_r
EOF
expect_fail "$tmp_dir/bad-bitrate.conf"

echo 'CAN config parser tests: PASS'
