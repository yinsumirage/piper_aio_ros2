import tempfile
from pathlib import Path
import unittest

import yaml

from piper_aio_ros2.cameras import (
    CameraConfigError,
    CameraInventoryError,
    discover_devices,
    load_camera_config,
    parse_inventory,
    require_online,
)


class CameraConfigTest(unittest.TestCase):
    def write_config(self, cameras):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "cameras.yaml"
        path.write_text(yaml.safe_dump({"cameras": cameras}), encoding="utf-8")
        return path

    def test_valid_serial_role_mapping(self):
        path = self.write_config(
            [
                {"serial": "F123", "role": "front"},
                {"serial": "L123", "role": "left"},
                {"serial": "R123", "role": "right"},
            ]
        )
        self.assertEqual(load_camera_config(path), {"front": "F123", "left": "L123", "right": "R123"})

    def test_empty_serial_fails_closed(self):
        path = self.write_config(
            [
                {"serial": "", "role": "front"},
                {"serial": "L123", "role": "left"},
                {"serial": "R123", "role": "right"},
            ]
        )
        with self.assertRaisesRegex(CameraConfigError, "front serial is empty"):
            load_camera_config(path)

    def test_duplicate_serial_fails_closed(self):
        path = self.write_config(
            [
                {"serial": "SAME", "role": "front"},
                {"serial": "SAME", "role": "left"},
                {"serial": "R123", "role": "right"},
            ]
        )
        with self.assertRaisesRegex(CameraConfigError, "serials must be unique"):
            load_camera_config(path)

    def test_missing_or_duplicate_role_fails_closed(self):
        path = self.write_config(
            [
                {"serial": "F123", "role": "front"},
                {"serial": "L123", "role": "left"},
                {"serial": "R123", "role": "left"},
            ]
        )
        with self.assertRaisesRegex(CameraConfigError, "duplicate camera role"):
            load_camera_config(path)

    def test_inventory_and_online_set(self):
        text = """
Device info:
    Name                          : Intel RealSense D435
    Serial Number                 : F123
    Firmware Version              : 5.16.0.1
    Physical Port                 : /sys/devices/pci0000:00/usb1/1-2
    Usb Type Descriptor           : 3.2
Device info:
    Name                          : Intel RealSense D455
    Serial Number                 : L123
    Firmware Version              : 5.16.0.1
    Physical Port                 : /sys/devices/pci0000:00/usb2/2-1
    Usb Type Descriptor           : 3.2
"""
        devices = parse_inventory(text)
        self.assertEqual([device["serial"] for device in devices], ["F123", "L123"])
        self.assertEqual(devices[0]["usb_type"], "3.2")
        with self.assertRaisesRegex(RuntimeError, r"missing=\['R123'\]"):
            require_online({"front": "F123", "left": "L123", "right": "R123"}, devices)

    def test_inventory_timeout_must_be_positive(self):
        with self.assertRaisesRegex(CameraInventoryError, "timeout must be positive"):
            discover_devices(0)


if __name__ == "__main__":
    unittest.main()
