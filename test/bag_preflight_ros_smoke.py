"""Bounded ROS graph regression for official follower feedback topics."""

import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ALL_TOPICS = (
    "/camera_f/color/image_raw",
    "/camera_l/color/image_raw",
    "/camera_r/color/image_raw",
    "/follower_left/joint_states_feedback",
    "/follower_right/joint_states_feedback",
    "/master_left/joint_states",
    "/master_right/joint_states",
    "/follower_left/joint_ctrl_cmd",
    "/follower_right/joint_ctrl_cmd",
    "/follower_left/joint_ctrl",
    "/follower_right/joint_ctrl",
    "/follower_left/end_pose_stamped",
    "/follower_right/end_pose_stamped",
)


def publish_graph(ready, stop):
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from rclpy.node import Node
    from sensor_msgs.msg import Image, JointState

    rclpy.init()
    node = Node("synthetic_bag_preflight_graph")
    topics = {
        Image: (
            "/camera_f/color/image_raw",
            "/camera_l/color/image_raw",
            "/camera_r/color/image_raw",
        ),
        JointState: (
            "/follower_left/joint_states_feedback",
            "/follower_right/joint_states_feedback",
            "/master_left/joint_states",
            "/master_right/joint_states",
            "/follower_left/joint_ctrl_cmd",
            "/follower_right/joint_ctrl_cmd",
            "/follower_left/joint_ctrl",
            "/follower_right/joint_ctrl",
        ),
        PoseStamped: (
            "/follower_left/end_pose_stamped",
            "/follower_right/end_pose_stamped",
        ),
    }
    publishers = [node.create_publisher(message_type, topic, 1) for message_type, names in topics.items() for topic in names]
    ready.set()
    try:
        while not stop.wait(0.05):
            rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        publishers.clear()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def wait_for_graph(process):
    import rclpy
    from rclpy.node import Node

    rclpy.init()
    node = Node("synthetic_bag_preflight_probe")
    deadline = time.monotonic() + 5.0
    visible = set()
    try:
        while process.is_alive() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            visible = {name for name, _ in node.get_topic_names_and_types()}
            if set(ALL_TOPICS) <= visible:
                return
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    raise AssertionError(
        f"synthetic graph incomplete; alive={process.is_alive()} exit={process.exitcode} "
        f"missing={sorted(set(ALL_TOPICS) - visible)}"
    )


def main():
    if "ROS_DOMAIN_ID" not in os.environ:
        raise RuntimeError("set an isolated ROS_DOMAIN_ID before running this test")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    stop = context.Event()
    process = context.Process(target=publish_graph, args=(ready, stop), name="synthetic_preflight_graph")
    process.start()
    try:
        assert ready.wait(3.0), "synthetic graph did not become ready"
        wait_for_graph(process)
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new_bag"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "piper_aio_ros2.bag_preflight",
                    "--config",
                    str(root / "config" / "record_topics.yaml"),
                    "--output-dir",
                    str(output),
                    "--min-free-gb",
                    "0",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        assert result.returncode == 0, (result.stdout, result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["ok"] is True, report
        assert report["unexpected_control_publishers"] == [], report
        for name in ("executed_action_left", "executed_action_right"):
            assert report["streams"][name]["publisher_count"] == 1, report
        print("PASS: 11 whitelist topics plus two official joint_ctrl feedback topics")
    finally:
        stop.set()
        process.join(timeout=3.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        assert not process.is_alive(), "synthetic publisher process remains"


if __name__ == "__main__":
    main()
