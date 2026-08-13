import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from piper_aio_ros2.cameras import CAMERA_SPECS, discover_devices, load_camera_config, require_online


def launch_setup(context):
    config = LaunchConfiguration("config").perform(context)
    role = LaunchConfiguration("role").perform(context)
    if role not in (*CAMERA_SPECS, "all"):
        raise RuntimeError("role must be one of all, front, left, right")
    serials = load_camera_config(config)
    devices = discover_devices(float(LaunchConfiguration("inventory_timeout").perform(context)))
    selected = serials if role == "all" else {role: serials[role]}
    require_online(selected, devices)
    wrapper = os.path.join(get_package_share_directory("realsense2_camera"), "launch", "rs_launch.py")
    actions = []
    for selected_role in CAMERA_SPECS if role == "all" else (role,):
        name = CAMERA_SPECS[selected_role]["name"]
        actions.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(wrapper),
                launch_arguments={
                    "camera_namespace": "",
                    "camera_name": name,
                    "serial_no": "_" + serials[selected_role],
                    "enable_color": "true",
                    "rgb_camera.color_profile": "640x480x30",
                    "rgb_camera.color_format": "RGB8",
                    "enable_depth": "false",
                    "enable_infra": "false",
                    "enable_infra1": "false",
                    "enable_infra2": "false",
                    "enable_rgbd": "false",
                    "enable_gyro": "false",
                    "enable_accel": "false",
                    "pointcloud.enable": "false",
                    "align_depth.enable": "false",
                    "wait_for_device_timeout": "5.0",
                    "reconnect_timeout": "6.0",
                }.items(),
            )
        )
    return actions


def generate_launch_description():
    default_config = os.path.join(get_package_share_directory("piper_aio_ros2"), "config", "cameras.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("config", default_value=default_config),
            DeclareLaunchArgument("role", default_value="all", description="all, front, left, or right"),
            DeclareLaunchArgument("inventory_timeout", default_value="10.0"),
            OpaqueFunction(function=launch_setup),
        ]
    )
