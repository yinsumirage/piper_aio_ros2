import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


CONTROL_REMAPPINGS = [
    ("joint_ctrl_single", "joint_ctrl_cmd"),
]


def generate_launch_description():
    config = os.path.join(get_package_share_directory("piper_aio_ros2"), "config", "four_arm.yaml")
    nodes = []
    for side in ("left", "right"):
        nodes.extend(
            [
                Node(
                    package="piper",
                    executable="piper_read_slave_joint",
                    namespace=f"master_{side}",
                    name="piper_read",
                    output="screen",
                    parameters=[config],
                ),
                Node(
                    package="piper",
                    executable="piper_single_ctrl",
                    namespace=f"follower_{side}",
                    name="piper_ctrl",
                    output="screen",
                    parameters=[config],
                    remappings=CONTROL_REMAPPINGS,
                ),
            ]
        )
    return LaunchDescription(nodes)
