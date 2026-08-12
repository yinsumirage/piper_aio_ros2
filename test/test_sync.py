from types import SimpleNamespace
import unittest

from piper_aio_ros2.sync import (
    DuplicateImageSelection,
    build_sync_plan,
    message_time_ns,
    select_index,
)


class SyncTest(unittest.TestCase):
    def test_nearest_tie_prefers_past_and_tolerance(self):
        self.assertEqual(select_index([90, 110], 100, 10), 0)
        self.assertIsNone(select_index([90, 110], 100, 9))

    def test_causal_action_never_selects_future(self):
        self.assertEqual(select_index([90, 101], 100, 20, causal=True), 0)
        self.assertIsNone(select_index([101], 100, 20, causal=True))

    def test_header_preferred_and_receive_fallback(self):
        stamped = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=2, nanosec=3)))
        zero = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0)))
        no_header = SimpleNamespace()
        self.assertEqual(message_time_ns(stamped, 10), (2_000_000_003, "header"))
        self.assertEqual(message_time_ns(zero, 10), (10, "receive"))
        self.assertEqual(message_time_ns(no_header, 11), (11, "receive"))

    def test_plan_uses_causal_action(self):
        streams = {
            "rgb_front": [1_000_000_000, 1_033_333_333],
            "state": [999_000_000, 1_034_000_000],
            "leader_action": [995_000_000, 1_001_000_000, 1_032_000_000],
        }
        kinds = {"rgb_front": "rgb", "state": "state", "leader_action": "intent"}
        plan = build_sync_plan(streams, kinds, list(streams), fps=30)
        self.assertEqual(plan["valid_frames"][0]["indices"]["leader_action"], 0)
        self.assertLessEqual(plan["valid_frames"][0]["sync_delta_ns"]["leader_action"], 0)

    def test_duplicate_image_selection_is_rejected(self):
        streams = {
            "rgb_front": [1_000_000_000, 1_050_000_000],
            "state": [1_000_000_000, 1_016_666_667, 1_033_333_333, 1_050_000_000],
            "leader_action": [1_000_000_000, 1_016_666_667, 1_033_333_333, 1_050_000_000],
        }
        kinds = {"rgb_front": "rgb", "state": "state", "leader_action": "intent"}
        with self.assertRaises(DuplicateImageSelection):
            build_sync_plan(streams, kinds, list(streams), fps=60)


if __name__ == "__main__":
    unittest.main()
