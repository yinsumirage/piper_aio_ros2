from glob import glob
from os.path import join

from setuptools import find_packages, setup


package_name = "piper_aio_ros2"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "LICENSE", "NOTICE"]),
        (join("share", package_name, "config"), glob("config/*.yaml")),
        (join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="yinsumirage",
    maintainer_email="yinsumirage@gmail.com",
    description="Piper AIO collection, explicitly armed dual-arm teleop, and dry-run replay tools",
    license="MIT",
    entry_points={
        "console_scripts": [
            "collect = piper_aio_ros2.collect:main",
            "replay = piper_aio_ros2.replay:main",
            "teleop = piper_aio_ros2.teleop:main",
            "bag_preflight = piper_aio_ros2.bag_preflight:main",
            "bag_inspect = piper_aio_ros2.bag_inspect:main",
            "bag_to_hdf5 = piper_aio_ros2.bag_to_hdf5:main",
            "validate_episode = piper_aio_ros2.validate_episode:main",
        ],
    },
)
