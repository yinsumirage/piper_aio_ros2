import math
import unittest

from piper_aio_ros2.joints import JOINT_ORDER
from piper_aio_ros2.teleop_core import (
    MASTER_ARM_ORDER,
    MASTER_GRIPPER_ORDER,
    TeleopLimits,
    TeleopSafety,
    command_payload,
    master_values,
)


def seed(safety, left=(0.0,) * 6, right=(0.0,) * 6, now=0.0, nine_dimensional=True):
    for side, joints in (("left", left), ("right", right)):
        if nine_dimensional:
            names = MASTER_GRIPPER_ORDER
            position = joints + (0.0, 0.01, -0.01)
        else:
            names = MASTER_ARM_ORDER
            position = joints
        safety.update_master(side, names, position, now)
        safety.update_follower(side, JOINT_ORDER, joints + (0.02,), now)


class TeleopMappingTest(unittest.TestCase):
    def test_six_dimensional_master_is_strict_and_unordered(self):
        names = tuple(reversed(MASTER_ARM_ORDER))
        values = tuple(reversed((1.0, 2.0, 3.0, 4.0, 5.0, 6.0)))
        self.assertEqual(master_values(names, values), ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0), None))

    def test_nine_dimensional_master_maps_joint7_minus_joint8(self):
        by_name = dict(zip(MASTER_GRIPPER_ORDER, (1, 2, 3, 4, 5, 6, 0, 0.03, -0.02)))
        names = tuple(reversed(MASTER_GRIPPER_ORDER))
        joints, gripper = master_values(names, [by_name[name] for name in names])
        self.assertEqual(joints, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
        self.assertAlmostEqual(gripper, 0.05)

    def test_missing_duplicate_and_non_finite_master_fields_fail(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            master_values(MASTER_ARM_ORDER[:-1], (0.0,) * 5)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            master_values(MASTER_ARM_ORDER[:-1] + ("joint5",), (0.0,) * 6)
        values = [0.0] * 6
        values[2] = math.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            master_values(MASTER_ARM_ORDER, values)

    def test_payload_has_explicit_speed_and_gripper_effort(self):
        limits = TeleopLimits(speed_percent=7.0, gripper_effort=0.6)
        payload = command_payload((0.0,) * 7, limits)
        self.assertEqual(payload["name"], JOINT_ORDER)
        self.assertEqual(payload["velocity"], (0.0,) * 6 + (7.0,))
        self.assertEqual(payload["effort"], (0.0,) * 6 + (0.6,))


class TeleopSafetyTest(unittest.TestCase):
    def test_unarmed_has_no_commands_and_sides_remain_independent(self):
        safety = TeleopSafety(TeleopLimits(max_joint_abs_rad=5.0))
        left = (0.01, 0.02, 0.03, 0.04, 0.05, 0.06)
        right = (-0.01, -0.02, -0.03, -0.04, -0.05, -0.06)
        seed(safety, left, right)
        self.assertIsNone(safety.commands(0.0))
        self.assertEqual(safety.arm(0.0), (True, "armed"))
        commands = safety.commands(0.0)
        self.assertEqual(commands["left"], left + (0.02,))
        self.assertEqual(commands["right"], right + (0.02,))

    def test_teleop_requires_nine_dimensional_master_input(self):
        safety = TeleopSafety()
        seed(safety, nine_dimensional=False)
        success, reason = safety.arm(0.0)
        self.assertFalse(success)
        self.assertIn("requires a 9D", reason)

    def test_initial_gripper_alignment_is_required(self):
        safety = TeleopSafety(TeleopLimits(initial_gripper_error_m=0.002))
        seed(safety)
        safety.update_follower("left", JOINT_ORDER, (0.0,) * 6 + (0.024,), 0.01)
        success, reason = safety.arm(0.01)
        self.assertFalse(success)
        self.assertIn("gripper", reason)

    def test_initial_alignment_is_atomic(self):
        safety = TeleopSafety(TeleopLimits(initial_joint_error_rad=0.05, max_joint_step_rad=0.1))
        seed(safety)
        moved = (0.06,) + (0.0,) * 5 + (0.0, 0.01, -0.01)
        safety.update_master("left", MASTER_GRIPPER_ORDER, moved, 0.01)
        success, reason = safety.arm(0.01)
        self.assertFalse(success)
        self.assertFalse(safety.armed)
        self.assertIn("left", reason)

    def test_stale_latches_fault_until_explicit_disarm(self):
        safety = TeleopSafety(TeleopLimits(stale_timeout_sec=0.1))
        seed(safety)
        self.assertTrue(safety.arm(0.0)[0])
        self.assertIsNone(safety.commands(0.11))
        self.assertIn("stale", safety.fault)
        self.assertFalse(safety.arm(0.11)[0])
        safety.disarm()
        self.assertIsNone(safety.fault)
        self.assertFalse(safety.arm(0.11)[0])

    def test_absolute_and_step_violations_reject_and_latch(self):
        safety = TeleopSafety(TeleopLimits(max_joint_abs_rad=1.0, max_joint_step_rad=0.1))
        self.assertFalse(safety.update_master("left", MASTER_ARM_ORDER, (1.1,) + (0.0,) * 5, 0.0))
        self.assertIn("absolute", safety.fault)

        safety.disarm()
        seed(safety)
        self.assertTrue(safety.arm(0.0)[0])
        moved = (0.11,) + (0.0,) * 5 + (0.0, 0.01, -0.01)
        self.assertFalse(safety.update_master("left", MASTER_GRIPPER_ORDER, moved, 0.01))
        self.assertIn("step", safety.fault)
        self.assertIsNone(safety.commands(0.01))

    def test_gripper_absolute_and_step_violations_latch(self):
        safety = TeleopSafety(TeleopLimits(max_gripper_abs_m=0.04, max_gripper_step_m=0.005))
        bad = (0.0,) * 6 + (0.0, 0.025, -0.025)
        self.assertFalse(safety.update_master("left", MASTER_GRIPPER_ORDER, bad, 0.0))
        self.assertIn("gripper absolute", safety.fault)

        safety.disarm()
        seed(safety)
        moved = (0.0,) * 6 + (0.0, 0.013, -0.013)
        self.assertFalse(safety.update_master("left", MASTER_GRIPPER_ORDER, moved, 0.01))
        self.assertIn("gripper step", safety.fault)


if __name__ == "__main__":
    unittest.main()
