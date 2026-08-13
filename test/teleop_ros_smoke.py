"""Bounded synthetic ROS smoke test. Requires an isolated ROS_DOMAIN_ID."""

import os
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool

from piper_aio_ros2.joints import JOINT_ORDER
from piper_aio_ros2.teleop import TeleopNode
from piper_aio_ros2.teleop_core import MASTER_GRIPPER_ORDER


def main():
    if "ROS_DOMAIN_ID" not in os.environ:
        raise RuntimeError("set an isolated ROS_DOMAIN_ID before running this test")
    rclpy.init()
    bridge = TeleopNode()
    probe = Node("synthetic_teleop_probe")
    executor = SingleThreadedExecutor()
    executor.add_node(bridge)
    executor.add_node(probe)
    counts = {"left": 0, "right": 0}
    messages = {}
    publishers = {}
    for side in ("left", "right"):
        publishers[("master", side)] = probe.create_publisher(
            JointState, f"/master_{side}/joint_states", 1
        )
        publishers[("follower", side)] = probe.create_publisher(
            JointState, f"/follower_{side}/joint_states_feedback", 1
        )

        def receive(message, side=side):
            counts[side] += 1
            messages[side] = message

        probe.create_subscription(JointState, f"/follower_{side}/joint_ctrl_cmd", receive, 10)
    client = probe.create_client(SetBool, "/dual_arm_teleop/arm")

    master_positions = {
        "left": [0.10] + [0.0] * 6 + [0.01, -0.01],
        "right": [-0.10] + [0.0] * 6 + [0.01, -0.01],
    }
    follower_positions = {
        "left": [-0.20] + [0.0] * 5 + [0.03],
        "right": [0.20] + [0.0] * 5 + [0.04],
    }

    def publish_inputs():
        for side in ("left", "right"):
            master = JointState()
            master.name = list(MASTER_GRIPPER_ORDER)
            master.position = master_positions[side]
            follower = JointState()
            follower.name = list(JOINT_ORDER)
            follower.position = follower_positions[side]
            publishers[("master", side)].publish(master)
            publishers[("follower", side)].publish(follower)

    def spin_for(seconds, publish=False):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if publish:
                publish_inputs()
            executor.spin_once(timeout_sec=0.01)

    try:
        spin_for(0.5, publish=True)
        assert counts == {"left": 0, "right": 0}, counts
        assert client.wait_for_service(timeout_sec=1.0)
        request = SetBool.Request()
        request.data = True
        future = client.call_async(request)
        deadline = time.monotonic() + 1.0
        while not future.done() and time.monotonic() < deadline:
            publish_inputs()
            executor.spin_once(timeout_sec=0.01)
        assert future.done() and future.result().success, future.result()

        spin_for(0.3, publish=True)
        assert counts["left"] > 0 and counts["right"] > 0, counts
        for side, message in messages.items():
            assert tuple(message.name) == JOINT_ORDER
            assert len(message.position) == 7
            assert all(
                abs(actual - expected) < 1e-12
                for actual, expected in zip(message.position, follower_positions[side])
            )
            assert message.velocity[6] == 30.0
            assert message.effort[6] == 0.5

        spin_for(0.35)
        frozen = dict(counts)
        assert bridge.safety.fault and "stale" in bridge.safety.fault
        spin_for(0.2)
        assert counts == frozen, (counts, frozen)

        request = SetBool.Request()
        request.data = False
        future = client.call_async(request)
        deadline = time.monotonic() + 1.0
        while not future.done() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
        assert future.done() and future.result().success
        assert bridge.safety.fault is None
        print(
            "PASS: unarmed=0, relative arm=no jump, bounded dual 7D, "
            "stale=stopped, disarm=cleared"
        )
    finally:
        executor.remove_node(probe)
        executor.remove_node(bridge)
        probe.destroy_node()
        bridge.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
