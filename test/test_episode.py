import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from piper_aio_ros2.episode import DEPTH_SHAPE, RGB_SHAPE, EpisodeBuffer, next_episode_index
from piper_aio_ros2.replay import main as replay_main
from piper_aio_ros2.validate_episode import validate


class EpisodeTest(unittest.TestCase):
    def test_schema_and_save(self):
        cameras = ["cam_high", "cam_left_wrist", "cam_right_wrist"]
        buffer = EpisodeBuffer(cameras, use_depth=True)
        observation = {
            "qpos": np.arange(14),
            "qvel": np.arange(14) / 10,
            "effort": np.arange(14) / 100,
            "eef_pose": np.arange(14) / 1000,
            "images": {name: np.zeros(RGB_SHAPE, dtype=np.uint8) for name in cameras},
            "images_depth": {name: np.zeros(DEPTH_SHAPE, dtype=np.uint16) for name in cameras},
        }
        buffer.append(
            observation,
            np.arange(14) + 1,
            frame_ns=1_000_000_000,
            source_ns={"rgb_front": 1_001_000_000, "leader_action_left": 999_000_000},
        )
        buffer.append(
            observation,
            np.arange(14) + 2,
            frame_ns=1_033_333_333,
            source_ns={"rgb_front": 1_034_000_000, "leader_action_left": 1_032_000_000},
        )

        with tempfile.TemporaryDirectory() as directory:
            path = buffer.save(Path(directory) / "episode_0.hdf5")
            with h5py.File(path, "r") as root:
                self.assertEqual(root["/observations/qpos"].shape, (2, 14))
                self.assertEqual(root["/observations/qvel"].shape, (2, 14))
                self.assertEqual(root["/observations/effort"].shape, (2, 14))
                self.assertEqual(root["/observations/eef_pose"].shape, (2, 14))
                self.assertEqual(root["/action"].shape, (2, 14))
                self.assertEqual(root.attrs["schema_version"], "1")
                self.assertEqual(root.attrs["action_source"], "intent")
                self.assertEqual(root["/actions/intent"].shape, (2, 14))
                self.assertEqual(root["/actions/executed"].shape, (2, 14))
                self.assertFalse(root["/actions/executed_valid"][:].any())
                np.testing.assert_array_equal(root["/action"][:], root["/actions/intent"][:])
                np.testing.assert_array_equal(
                    root["/sync_delta_ns/rgb_front"][:], [1_000_000, 666_667]
                )
                self.assertEqual(root["/collect"].asstr()[()].tolist(), ["teleop", "teleop"])
                for camera in cameras:
                    self.assertEqual(root[f"/observations/images/{camera}"].shape, (2,) + RGB_SHAPE)
                    self.assertEqual(root[f"/observations/images_depth/{camera}"].shape, (2,) + DEPTH_SHAPE)
            self.assertTrue(validate(path)["ok"])
            self.assertEqual(next_episode_index(directory), 1)
            with self.assertRaises(FileExistsError):
                buffer.save(path)

    def test_executed_actions_are_canonical_action(self):
        cameras = ["cam_high", "cam_left_wrist", "cam_right_wrist"]
        buffer = EpisodeBuffer(cameras)
        observation = {
            "qpos": np.arange(14),
            "qvel": np.arange(14),
            "effort": np.arange(14),
            "eef_pose": np.arange(14),
            "images": {name: np.zeros(RGB_SHAPE, dtype=np.uint8) for name in cameras},
        }
        buffer.append(observation, np.ones(14), executed=np.full(14, 2.0), frame_ns=1)
        with tempfile.TemporaryDirectory() as directory:
            path = buffer.save(Path(directory) / "episode.hdf5")
            with h5py.File(path, "r") as root:
                self.assertEqual(root.attrs["action_source"], "executed")
                np.testing.assert_array_equal(root["/action"][:], np.full((1, 14), 2.0))

    def test_replay_is_dry_run_and_execute_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode_0.hdf5"
            with h5py.File(path, "w") as root:
                root.create_dataset("action", data=np.zeros((2, 14)))
                observations = root.create_group("observations")
                observations.create_dataset("eef_pose", data=np.zeros((2, 14)))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                replay_main([str(path), "--mode", "joint"])
            self.assertIn("DRY RUN", output.getvalue())
            self.assertIn("no hardware command was sent", output.getvalue())

            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                replay_main([str(path), "--execute"])


if __name__ == "__main__":
    unittest.main()
