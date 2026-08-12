import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_config = os.path.join(get_package_share_directory("piper_aio_ros2"), "config", "teleop.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("config", default_value=default_config),
            Node(
                package="piper_aio_ros2",
                executable="teleop",
                name="dual_arm_teleop",
                output="screen",
                parameters=[LaunchConfiguration("config")],
            ),
        ]
    )
