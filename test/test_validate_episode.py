import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from piper_aio_ros2.episode import EpisodeBuffer, RGB_SHAPE
from piper_aio_ros2.validate_episode import validate


class ValidateEpisodeTest(unittest.TestCase):
    def _episode(self, directory):
        cameras = ["cam_high", "cam_left_wrist", "cam_right_wrist"]
        observation = {
            "qpos": np.arange(14),
            "qvel": np.zeros(14),
            "effort": np.zeros(14),
            "eef_pose": np.arange(14),
            "images": {name: np.zeros(RGB_SHAPE, dtype=np.uint8) for name in cameras},
        }
        buffer = EpisodeBuffer(cameras)
        buffer.append(
            observation,
            np.ones(14),
            frame_ns=1_000_000_000,
            source_ns={"rgb_front": 1_000_000_000, "leader_action_left": 999_000_000},
        )
        return buffer.save(Path(directory) / "episode.hdf5")

    def test_valid_intent_only_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(validate(self._episode(directory))["ok"])

    def test_action_contract_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._episode(directory)
            with h5py.File(path, "r+") as root:
                root["/action"][0, 0] = 123
            report = validate(path)
            self.assertFalse(report["ok"])
            self.assertIn("/action does not equal /actions/intent", report["errors"])


if __name__ == "__main__":
    unittest.main()
