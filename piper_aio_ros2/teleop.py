"""ROS 2 dual-arm leader-follower bridge with explicit arming."""

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool

from .teleop_core import SIDES, TeleopLimits, TeleopSafety, command_payload


class TeleopNode(Node):
    def __init__(self):
        super().__init__("dual_arm_teleop")
        defaults = TeleopLimits()
        for name, value in (
            ("publish_hz", defaults.publish_hz),
            ("stale_timeout_sec", defaults.stale_timeout_sec),
            ("max_joint_abs_rad", defaults.max_joint_abs_rad),
            ("max_gripper_abs_m", defaults.max_gripper_abs_m),
            ("max_alignment_joint_error_rad", defaults.max_alignment_joint_error_rad),
            ("max_alignment_gripper_error_m", defaults.max_alignment_gripper_error_m),
            ("alignment_joint_tolerance_rad", defaults.alignment_joint_tolerance_rad),
            ("alignment_gripper_tolerance_m", defaults.alignment_gripper_tolerance_m),
            ("alignment_timeout_sec", defaults.alignment_timeout_sec),
            ("alignment_settle_sec", defaults.alignment_settle_sec),
            (
                "max_alignment_master_joint_drift_rad",
                defaults.max_alignment_master_joint_drift_rad,
            ),
            (
                "max_alignment_master_gripper_drift_m",
                defaults.max_alignment_master_gripper_drift_m,
            ),
            ("max_joint_step_rad", defaults.max_joint_step_rad),
            ("max_gripper_step_m", defaults.max_gripper_step_m),
            ("alignment_speed_percent", defaults.alignment_speed_percent),
            ("speed_percent", defaults.speed_percent),
            ("gripper_effort", defaults.gripper_effort),
        ):
            self.declare_parameter(name, value)
        topic_defaults = {
            "master_left": "/master_left/joint_states",
            "master_right": "/master_right/joint_states",
            "follower_left": "/follower_left/joint_states_feedback",
            "follower_right": "/follower_right/joint_states_feedback",
            "command_left": "/follower_left/joint_ctrl_cmd",
            "command_right": "/follower_right/joint_ctrl_cmd",
        }
        for name, value in topic_defaults.items():
            self.declare_parameter("topics." + name, value)
        limits = TeleopLimits(
            **{
                name: self.get_parameter(name).value
                for name in TeleopLimits.__dataclass_fields__
            }
        )
        self.safety = TeleopSafety(limits)
        self._last_reported_fault = None
        self._last_alignment_report_at = None
        qos = QoSProfile(depth=1)
        self._command_publishers = {
            side: self.create_publisher(
                JointState, self.get_parameter("topics.command_" + side).value, qos
            )
            for side in SIDES
        }
        for side in SIDES:
            self.create_subscription(
                JointState,
                self.get_parameter("topics.master_" + side).value,
                lambda message, side=side: self._input("master", side, message),
                qos,
            )
            self.create_subscription(
                JointState,
                self.get_parameter("topics.follower_" + side).value,
                lambda message, side=side: self._input("follower", side, message),
                qos,
            )
        self.create_service(SetBool, "~/arm", self._set_armed)
        self.create_timer(1.0 / limits.publish_hz, self._publish)
        self.get_logger().info("teleop started unarmed; no enable service is called")

    def _input(self, source, side, message):
        before = self.safety.fault
        update = self.safety.update_master if source == "master" else self.safety.update_follower
        update(side, message.name, message.position, time.monotonic())
        self._report_new_fault(before)

    def _report_new_fault(self, previous=None):
        fault = self.safety.fault
        if fault is not None and fault != previous and fault != self._last_reported_fault:
            self.get_logger().error("teleop fault latched; publishing stopped: " + fault)
            self._last_reported_fault = fault

    def _set_armed(self, request, response):
        if request.data:
            now = time.monotonic()
            response.success, response.message = self.safety.arm(now)
            if response.success:
                self._last_alignment_report_at = now
        else:
            self.safety.disarm()
            self._last_reported_fault = None
            self._last_alignment_report_at = None
            response.success, response.message = True, "disarmed; fault and cached inputs cleared"
        self.get_logger().info(response.message)
        return response

    def _publish(self):
        before = self.safety.fault
        aligning_before = self.safety.aligning
        now = time.monotonic()
        commands = self.safety.commands(now)
        self._report_new_fault(before)
        if commands is None:
            return
        if (
            self.safety.aligning
            and self._last_alignment_report_at is not None
            and now - self._last_alignment_report_at >= 1.0
        ):
            elapsed, errors = self.safety.alignment_status(now)
            detail = "; ".join(
                f"{side} joint={joint:.4f} rad gripper={gripper:.4f} m"
                for side, (joint, gripper) in errors.items()
            )
            self.get_logger().info(f"alignment {elapsed:.1f}s: {detail}")
            self._last_alignment_report_at = now
        if self.safety.fault is None and aligning_before and not self.safety.aligning:
            self.get_logger().info("dual-arm alignment complete; live follow active")
            self._last_alignment_report_at = None
        stamp = self.get_clock().now().to_msg()
        messages = {}
        for side in SIDES:
            payload = command_payload(
                commands[side], self.safety.limits, self.safety.command_speed_percent(side)
            )
            message = JointState()
            message.header.stamp = stamp
            message.name = list(payload["name"])
            message.position = list(payload["position"])
            message.velocity = list(payload["velocity"])
            message.effort = list(payload["effort"])
            messages[side] = message
        for side in SIDES:
            self._command_publishers[side].publish(messages[side])


def main(args=None):
    rclpy.init(args=args)
    node = TeleopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
