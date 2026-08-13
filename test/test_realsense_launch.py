from pathlib import Path
import unittest

import yaml

from piper_aio_ros2.cameras import CAMERA_SPECS


class RealSenseLaunchContractTest(unittest.TestCase):
    def test_launch_has_stable_rgb_contract_and_no_depth(self):
        launch_text = (Path(__file__).parents[1] / "launch" / "three_realsense.launch.py").read_text(
            encoding="utf-8"
        )
        for value in (
            '"camera_namespace": ""',
            '"rgb_camera.color_profile": "640x480x30"',
            '"rgb_camera.color_format": "RGB8"',
            '"enable_depth": "false"',
            '"pointcloud.enable": "false"',
            '"align_depth.enable": "false"',
        ):
            with self.subTest(value=value):
                self.assertIn(value, launch_text)

    def test_expected_topics_match_record_whitelist(self):
        root = Path(__file__).parents[1]
        record = yaml.safe_load((root / "config" / "record_topics.yaml").read_text(encoding="utf-8"))
        record_rgb = {spec["topic"] for spec in record["streams"].values() if spec["kind"] == "rgb"}
        self.assertEqual(record_rgb, {spec["topic"] for spec in CAMERA_SPECS.values()})


if __name__ == "__main__":
    unittest.main()
