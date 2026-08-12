from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py

from piper_aio_ros2.export_lerobot import CAMERAS, export


class ExportLeRobotTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def episode(self, name, action_source):
        path = self.root / name
        with h5py.File(path, "w") as root:
            root.attrs["action_source"] = action_source
            root.attrs["fps"] = 30.0
            images = root.create_group("observations").create_group("images")
            for camera in CAMERAS:
                images.create_group(camera)
        return path

    def test_mixed_action_sources_are_rejected_when_intent_is_allowed(self):
        executed = self.episode("executed.hdf5", "executed")
        intent = self.episode("intent.hdf5", "intent")
        with patch("piper_aio_ros2.export_lerobot.version", return_value="0.6.0"), patch(
            "piper_aio_ros2.export_lerobot.validate", return_value={"ok": True, "errors": []}
        ):
            with self.assertRaisesRegex(ValueError, "same action_source"):
                export([executed, intent], self.root / "output", "local/test", "test", True)


if __name__ == "__main__":
    unittest.main()
