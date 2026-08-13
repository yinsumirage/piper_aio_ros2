import math
from pathlib import Path
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

    def test_nine_dimensional_master_maps_gripper_opening_magnitude(self):
        by_name = dict(zip(MASTER_GRIPPER_ORDER, (1, 2, 3, 4, 5, 6, 0, -0.03, 0.02)))
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
        aligning = command_payload((0.0,) * 7, limits, speed_percent=3.0)
        self.assertEqual(aligning["velocity"], (0.0,) * 6 + (3.0,))

    def test_runtime_config_uses_semantic_follower_mapping_and_absolute_alignment(self):
        root = Path(__file__).resolve().parents[1]
        four_arm = (root / "config" / "four_arm.yaml").read_text(encoding="utf-8")
        left = four_arm.split("/follower_left/piper_ctrl:", 1)[1].split(
            "/follower_right/piper_ctrl:", 1
        )[0]
        right = four_arm.split("/follower_right/piper_ctrl:", 1)[1]
        self.assertIn("can_port: can_slave_l", left)
        self.assertIn("can_port: can_slave_r", right)

        teleop = (root / "config" / "teleop.yaml").read_text(encoding="utf-8")
        self.assertIn("publish_hz: 100.0", teleop)
        self.assertIn("max_alignment_gripper_error_m: 0.08", teleop)
        self.assertIn("alignment_speed_percent: 100.0", teleop)
        self.assertIn("alignment_joint_tolerance_rad: 0.02", teleop)
        self.assertIn("alignment_gripper_tolerance_m: 0.002", teleop)
        self.assertIn("speed_percent: 100.0", teleop)
        self.assertIn("gripper_effort: 1.0", teleop)

        launch = (root / "launch" / "four_arm.launch.py").read_text(encoding="utf-8")
        self.assertIn('arguments=["--ros-args", "--log-level", "warn"]', launch)


class TeleopSafetyTest(unittest.TestCase):
    def test_unarmed_has_no_commands_and_sides_remain_independent(self):
        safety = TeleopSafety(TeleopLimits(max_joint_abs_rad=5.0))
        left = (0.01, 0.02, 0.03, 0.04, 0.05, 0.06)
        right = (-0.01, -0.02, -0.03, -0.04, -0.05, -0.06)
        seed(safety, left, right)
        self.assertIsNone(safety.commands(0.0))
        self.assertEqual(
            safety.arm(0.0), (True, "armed; absolute alignment active")
        )
        commands = safety.commands(0.0)
        self.assertEqual(commands["left"], left + (0.02,))
        self.assertEqual(commands["right"], right + (0.02,))
        self.assertTrue(safety.aligning)
        self.assertEqual(safety.command_speed_percent("left"), 100.0)
        self.assertEqual(safety.commands(0.0)["left"], left + (0.02,))
        self.assertFalse(safety.aligning)

    def test_absolute_alignment_holds_first_then_targets_both_sides_together(self):
        safety = TeleopSafety(
            TeleopLimits(
                max_joint_abs_rad=2.0,
                max_joint_step_rad=0.5,
                max_gripper_step_m=0.05,
            )
        )
        master = {
            "left": (0.30,) + (0.0,) * 5,
            "right": (-0.20,) + (0.0,) * 5,
        }
        follower = {
            "left": (0.0,) * 6,
            "right": (0.0,) * 6,
        }
        follower_position = {side: follower[side] + (0.0,) for side in ("left", "right")}
        for side in ("left", "right"):
            safety.update_master(
                side, MASTER_GRIPPER_ORDER, master[side] + (0.0, 0.02, -0.02), 0.0
            )
            safety.update_follower(side, JOINT_ORDER, follower[side] + (0.0,), 0.0)

        self.assertEqual(
            safety.arm(0.0), (True, "armed; absolute alignment active")
        )
        commands = safety.commands(0.0)
        self.assertEqual(commands["left"], follower_position["left"])
        self.assertEqual(commands["right"], follower_position["right"])

        commands = safety.commands(0.01)
        self.assertEqual(commands["left"], master["left"] + (0.04,))
        self.assertEqual(commands["right"], master["right"] + (0.04,))
        self.assertTrue(safety.aligning)
        safety.update_follower("left", JOINT_ORDER, commands["left"], 0.01)
        self.assertTrue(safety.aligning)
        safety.commands(0.01)
        self.assertTrue(safety.aligning)
        safety.update_follower("right", JOINT_ORDER, commands["right"], 0.01)
        safety.commands(0.01)
        self.assertFalse(safety.aligning)
        commands = safety.commands(0.02)
        self.assertEqual(commands["left"], master["left"] + (0.04,))
        self.assertEqual(commands["right"], master["right"] + (0.04,))
        self.assertEqual(safety.command_speed_percent("left"), 100.0)
        self.assertEqual(safety.command_speed_percent("right"), 100.0)

    def test_teleop_requires_nine_dimensional_master_input(self):
        safety = TeleopSafety()
        seed(safety, nine_dimensional=False)
        success, reason = safety.arm(0.0)
        self.assertFalse(success)
        self.assertIn("requires a 9D", reason)

    def test_excessive_automatic_gripper_alignment_is_rejected(self):
        safety = TeleopSafety(TeleopLimits(max_alignment_gripper_error_m=0.002))
        seed(safety)
        safety.update_follower("left", JOINT_ORDER, (0.0,) * 6 + (0.024,), 0.01)
        success, reason = safety.arm(0.01)
        self.assertFalse(success)
        self.assertIn("gripper", reason)

    def test_full_80mm_master_gripper_range_aligns_as_positive_opening(self):
        safety = TeleopSafety()
        for side in ("left", "right"):
            joint7, joint8 = (-0.04, 0.04) if side == "left" else (0.04, -0.04)
            safety.update_master(
                side,
                MASTER_GRIPPER_ORDER,
                (0.0,) * 6 + (0.0, joint7, joint8),
                0.0,
            )
            safety.update_follower(side, JOINT_ORDER, (0.0,) * 7, 0.0)
        self.assertTrue(safety.arm(0.0)[0])
        self.assertEqual(safety.commands(0.0)["left"][6], 0.0)
        commands = safety.commands(0.0)
        self.assertAlmostEqual(commands["left"][6], 0.08)
        self.assertAlmostEqual(commands["right"][6], 0.08)
        self.assertIsNone(safety.fault)

    def test_unarmed_motion_reseeds_without_latching_a_step_fault(self):
        safety = TeleopSafety(TeleopLimits(max_joint_step_rad=0.01))
        seed(safety)
        moved = (0.5,) + (0.0,) * 5 + (0.0, 0.01, -0.01)
        self.assertTrue(safety.update_master("left", MASTER_GRIPPER_ORDER, moved, 0.01))
        self.assertIsNone(safety.fault)

    def test_excessive_automatic_joint_alignment_is_rejected_atomically(self):
        safety = TeleopSafety(
            TeleopLimits(max_alignment_joint_error_rad=0.05, max_joint_step_rad=0.1)
        )
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
        self.assertTrue(safety.arm(0.0)[0])
        moved = (0.0,) * 6 + (0.0, 0.013, -0.013)
        self.assertFalse(safety.update_master("left", MASTER_GRIPPER_ORDER, moved, 0.01))
        self.assertIn("gripper step", safety.fault)

if __name__ == "__main__":
    unittest.main()
