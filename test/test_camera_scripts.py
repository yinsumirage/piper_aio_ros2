from pathlib import Path
import unittest

import yaml


class CameraRecordingScriptTest(unittest.TestCase):
    def test_camera_only_recording_is_exact_three_topic_whitelist(self):
        root = Path(__file__).parents[1]
        config = yaml.safe_load((root / "config" / "camera_record_topics.yaml").read_text(encoding="utf-8"))
        topics = {entry["topic"] for entry in config["streams"].values()}
        self.assertEqual(
            topics,
            {
                "/camera_f/color/image_raw",
                "/camera_l/color/image_raw",
                "/camera_r/color/image_raw",
            },
        )
        script = (root / "scripts" / "record_cameras.sh").read_text(encoding="utf-8")
        self.assertIn("camera_status", script)
        self.assertIn("bag_preflight", script)
        self.assertIn("--compression-format zstd", script)
        self.assertIn("bag_inspect", script)
        self.assertNotIn("record -a", script)


if __name__ == "__main__":
    unittest.main()
