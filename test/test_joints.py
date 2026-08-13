import math
from types import SimpleNamespace
import unittest

from piper_aio_ros2.joints import (
    JOINT_ORDER,
    LEGACY_JOINT_ORDER,
    canonical_joint_state,
    canonical_values,
)


class CanonicalJointTest(unittest.TestCase):
    def test_seven_dimensional_and_unordered(self):
        names = list(reversed(JOINT_ORDER))
        values = list(reversed(range(7)))
        self.assertEqual(canonical_values(names, values, "position"), tuple(float(i) for i in range(7)))

    def test_legacy_zero_based_names_are_mapped_and_unordered(self):
        names = ("joint6", "joint2", "joint0", "joint5", "joint1", "joint4", "joint3")
        by_name = {name: float(index + 10) for index, name in enumerate(LEGACY_JOINT_ORDER)}
        values = [by_name[name] for name in names]
        self.assertEqual(canonical_values(names, values, "position"), tuple(float(i) for i in range(10, 17)))
        with self.assertRaisesRegex(ValueError, "does not match"):
            canonical_values((), range(7), "position")

    def test_nine_dimensional_gripper_pair_wins_over_placeholder(self):
        message = SimpleNamespace(
            name=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper", "joint7", "joint8"],
            position=[1, 2, 3, 4, 5, 6, 0, -0.021, 0.021],
            velocity=[],
            effort=[1, 2, 3, 4, 5, 6, 999, 4, -4],
        )
        result = canonical_joint_state(message)
        self.assertAlmostEqual(result["position"][6], 0.042)
        self.assertEqual(result["velocity"], (0.0,) * 7)
        self.assertEqual(result["effort"][6], 8.0)

    def test_seven_dimensional_position_normalizes_negative_gripper(self):
        values = (0.0,) * 6 + (-0.04,)
        self.assertEqual(canonical_values(JOINT_ORDER, values, "position")[6], 0.04)

    def test_missing_required_and_non_finite_position(self):
        with self.assertRaisesRegex(ValueError, "missing joint6"):
            canonical_values(JOINT_ORDER[:-2] + ("gripper",), range(6), "position")
        values = [0.0] * 7
        values[2] = math.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            canonical_values(JOINT_ORDER, values, "position")

    def test_optional_field_partial_names_are_zero_filled(self):
        values = canonical_values(JOINT_ORDER, [1.0, 2.0], "velocity", allow_missing=True)
        self.assertEqual(values, (1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def test_length_mismatch(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            canonical_values(JOINT_ORDER, [0.0], "position")


if __name__ == "__main__":
    unittest.main()
