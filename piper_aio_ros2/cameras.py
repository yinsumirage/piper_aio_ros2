"""Strict RealSense role configuration and read-only device inventory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


CAMERA_SPECS = {
    "front": {"name": "camera_f", "topic": "/camera_f/color/image_raw"},
    "left": {"name": "camera_l", "topic": "/camera_l/color/image_raw"},
    "right": {"name": "camera_r", "topic": "/camera_r/color/image_raw"},
}
INVENTORY_KEYS = {
    "name": "model",
    "serial number": "serial",
    "firmware version": "firmware",
    "physical port": "physical_port",
    "usb type descriptor": "usb_type",
}


class CameraConfigError(ValueError):
    pass


class CameraInventoryError(RuntimeError):
    pass


def load_camera_config(path):
    path = Path(path).expanduser()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CameraConfigError(f"cannot read camera config {path}: {exc}") from exc
    entries = raw.get("cameras") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise CameraConfigError("camera config must contain a 'cameras' list")
    cameras = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("role"), str):
            raise CameraConfigError("each camera entry must contain role and serial")
        role = entry["role"].strip()
        if role in cameras:
            raise CameraConfigError(f"duplicate camera role: {role}")
        cameras[role] = entry
    missing = sorted(set(CAMERA_SPECS) - set(cameras))
    extra = sorted(set(cameras) - set(CAMERA_SPECS))
    if missing or extra:
        raise CameraConfigError(f"roles must be exactly front,left,right; missing={missing}, extra={extra}")
    serials = {}
    for role in CAMERA_SPECS:
        entry = cameras[role]
        serial = entry.get("serial") if isinstance(entry, dict) else None
        if not isinstance(serial, str) or not serial.strip():
            raise CameraConfigError(f"{role} serial is empty")
        serials[role] = serial.strip()
    if len(set(serials.values())) != len(serials):
        raise CameraConfigError("front, left, and right serials must be unique")
    return serials


def parse_inventory(text):
    """Parse ``rs-enumerate-devices -S`` key/value device blocks."""
    devices = []
    current = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("device info"):
            if current.get("serial"):
                devices.append(current)
            current = {}
            continue
        match = re.match(r"^([^:]+?)\s*:\s*(.*?)\s*$", stripped)
        if not match:
            continue
        target = INVENTORY_KEYS.get(" ".join(match.group(1).lower().split()))
        if target:
            current[target] = match.group(2).strip()
    if current.get("serial"):
        devices.append(current)
    return devices


def discover_devices(timeout=10.0):
    if timeout <= 0:
        raise CameraInventoryError("inventory timeout must be positive")
    command = ["rs-enumerate-devices", "-S", "--no-eth"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise CameraInventoryError("rs-enumerate-devices is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CameraInventoryError(f"device inventory timed out after {timeout:g}s") from exc
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    devices = parse_inventory(output)
    if result.returncode != 0 or not devices:
        detail = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "no device detected")
        raise CameraInventoryError(f"RealSense inventory failed: {detail}")
    serials = [device["serial"] for device in devices]
    if len(serials) != len(set(serials)):
        raise CameraInventoryError("inventory returned duplicate serial numbers")
    return devices


def require_online(serials, devices, *, exact=False):
    online = {device["serial"] for device in devices}
    configured = set(serials.values())
    missing = sorted(configured - online)
    extra = sorted(online - configured)
    if missing or (exact and extra):
        raise CameraInventoryError(f"configured/current serial mismatch: missing={missing}, extra={extra}")
    return extra


def _print_inventory(devices):
    print("serial\tmodel\tfirmware\tusb_type\tphysical_port")
    for device in devices:
        print("\t".join(device.get(key, "") for key in ("serial", "model", "firmware", "usb_type", "physical_port")))


def inventory_main(argv=None):
    parser = argparse.ArgumentParser(description="List attached RealSense identity and USB topology")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        devices = discover_devices(args.timeout)
    except CameraInventoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(devices, indent=2, sort_keys=True))
    else:
        _print_inventory(devices)
    return 0


def _write_config(path, serials):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"cameras": [{"serial": serials[role], "role": role} for role in CAMERA_SPECS]}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        yaml.safe_dump(data, handle, sort_keys=False)
        temporary = handle.name
    os.replace(temporary, path)


def assign_main(argv=None):
    parser = argparse.ArgumentParser(description="Assign three currently attached RealSense serials to physical roles")
    parser.add_argument("--config", required=True)
    parser.add_argument("--front")
    parser.add_argument("--left")
    parser.add_argument("--right")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--yes", action="store_true", help="skip the final WRITE confirmation")
    args = parser.parse_args(argv)
    try:
        devices = discover_devices(args.timeout)
        if len(devices) != 3:
            raise CameraInventoryError(f"assignment requires exactly 3 attached RealSense devices, found {len(devices)}")
        _print_inventory(devices)
        serials = {role: getattr(args, role) for role in CAMERA_SPECS}
        supplied = [value is not None for value in serials.values()]
        if any(supplied) and not all(supplied):
            raise CameraConfigError("provide all of --front, --left, and --right, or none for interactive mode")
        if not any(supplied):
            print("Identify roles from physical placement or a serial-selected preview; never use USB/list order.")
            for role in CAMERA_SPECS:
                serials[role] = input(f"{role} serial: ").strip()
        if any(not value for value in serials.values()):
            raise CameraConfigError("all three serials are required")
        if len(set(serials.values())) != 3:
            raise CameraConfigError("front, left, and right serials must be unique")
        require_online(serials, devices, exact=True)
        for role in CAMERA_SPECS:
            print(f"{role:>5} -> {serials[role]} -> {CAMERA_SPECS[role]['topic']}")
        if not args.yes and input("Type WRITE to save this mapping: ").strip() != "WRITE":
            print("not written", file=sys.stderr)
            return 2
        _write_config(args.config, serials)
        load_camera_config(args.config)
    except (CameraConfigError, CameraInventoryError, EOFError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"wrote validated mapping: {Path(args.config).expanduser()}")
    return 0


if __name__ == "__main__":
    sys.exit(inventory_main())
