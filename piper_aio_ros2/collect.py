"""Interactive ROS 2 episode collector."""

from collections import deque
import math
import os
import select
import sys
import termios
import time
import tty

from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import Image, JointState

from .episode import EpisodeBuffer, next_episode_index
from .joints import canonical_joint_state


STREAM_PARAMETERS = {
    "rgb_front": "/camera_f/color/image_raw",
    "rgb_left": "/camera_l/color/image_raw",
    "rgb_right": "/camera_r/color/image_raw",
    "depth_front": "/camera_f/depth/image_raw",
    "depth_left": "/camera_l/depth/image_raw",
    "depth_right": "/camera_r/depth/image_raw",
    "follower_joint_left": "/joint_left",
    "follower_joint_right": "/joint_right",
    "leader_action_left": "/joint_states_ctrl_left",
    "leader_action_right": "/joint_states_ctrl_right",
    "follower_eef_left": "/end_pose_stamped_left",
    "follower_eef_right": "/end_pose_stamped_right",
}


class Keyboard:
    def __init__(self):
        self._settings = None

    def setup(self):
        if not sys.stdin.isatty():
            raise RuntimeError("interactive collection requires a TTY")
        self._settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    def close(self):
        if self._settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._settings)

    @staticmethod
    def get_key():
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    def wait_for(self, keys, node):
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            key = self.get_key()
            if key in keys:
                return key
        return None


class Collector(Node):
    def __init__(self):
        super().__init__("piper_aio_collect")
        self.declare_parameter("dataset_dir", "~/data/piper_aio_ros2")
        self.declare_parameter("task_name", "test")
        self.declare_parameter("episode_index", 0)
        self.declare_parameter("frame_rate", 30.0)
        self.declare_parameter("use_depth", False)
        self.declare_parameter("camera_names", ["cam_high", "cam_left_wrist", "cam_right_wrist"])
        for name, default in STREAM_PARAMETERS.items():
            self.declare_parameter("topics." + name, default)

        self.camera_names = list(self.get_parameter("camera_names").value)
        self.use_depth = bool(self.get_parameter("use_depth").value)
        self.frame_rate = float(self.get_parameter("frame_rate").value)
        if self.frame_rate <= 0:
            raise ValueError("frame_rate must be positive")
        self.bridge = CvBridge()
        self.queues = {}
        self._last_warning = (None, 0.0)
        self._create_subscriptions()

    def _create_subscriptions(self):
        specs = {
            "rgb_front": (Image, qos_profile_sensor_data),
            "rgb_left": (Image, qos_profile_sensor_data),
            "rgb_right": (Image, qos_profile_sensor_data),
            "follower_joint_left": (JointState, QoSProfile(depth=100)),
            "follower_joint_right": (JointState, QoSProfile(depth=100)),
            "leader_action_left": (JointState, QoSProfile(depth=100)),
            "leader_action_right": (JointState, QoSProfile(depth=100)),
            "follower_eef_left": (PoseStamped, QoSProfile(depth=100)),
            "follower_eef_right": (PoseStamped, QoSProfile(depth=100)),
        }
        if self.use_depth:
            specs.update(
                {
                    "depth_front": (Image, qos_profile_sensor_data),
                    "depth_left": (Image, qos_profile_sensor_data),
                    "depth_right": (Image, qos_profile_sensor_data),
                }
            )
        for name, (message_type, qos) in specs.items():
            self.queues[name] = deque(maxlen=2000)
            topic = str(self.get_parameter("topics." + name).value)
            self.create_subscription(message_type, topic, self._callback(name), qos)

    def _callback(self, name):
        def append(message):
            header = getattr(message, "header", None)
            stamp = getattr(header, "stamp", None)
            nanoseconds = 0 if stamp is None else stamp.sec * 1_000_000_000 + stamp.nanosec
            if nanoseconds <= 0:
                nanoseconds = self.get_clock().now().nanoseconds
            self.queues[name].append((nanoseconds, message))

        return append

    def reset(self):
        for queue in self.queues.values():
            queue.clear()

    def _synced_messages(self):
        if any(not queue for queue in self.queues.values()):
            return None
        camera_streams = ["rgb_front", "rgb_left", "rgb_right"]
        if self.use_depth:
            camera_streams.extend(("depth_front", "depth_left", "depth_right"))
        frame_time = min(self.queues[name][-1][0] for name in camera_streams)
        if any(queue[-1][0] < frame_time for queue in self.queues.values()):
            return None

        messages = {}
        for name, queue in self.queues.items():
            while queue[0][0] < frame_time:
                queue.popleft()
            messages[name] = queue.popleft()
        return frame_time, messages

    def _image(self, message, depth=False):
        image = np.asarray(self.bridge.imgmsg_to_cv2(message, desired_encoding="passthrough"))
        if depth and image.shape == (400, 640):
            image = np.pad(image, ((40, 40), (0, 0)))
        return image

    @staticmethod
    def _rpy(pose):
        x, y, z, w = pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        sin_pitch = 2 * (w * y - z * x)
        pitch = math.copysign(math.pi / 2, sin_pitch) if abs(sin_pitch) >= 1 else math.asin(sin_pitch)
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        return roll, pitch, yaw

    def _eef(self, message, canonical_position):
        pose = message.pose
        roll, pitch, yaw = self._rpy(pose)
        gripper = canonical_position[6]
        return np.array([pose.position.x, pose.position.y, pose.position.z, roll, pitch, yaw, gripper])

    def snapshot(self):
        synced = self._synced_messages()
        if synced is None:
            return None
        frame_ns, stamped = synced
        messages = {name: pair[1] for name, pair in stamped.items()}
        source_ns = {name: pair[0] for name, pair in stamped.items()}
        follower_left = canonical_joint_state(messages["follower_joint_left"])
        follower_right = canonical_joint_state(messages["follower_joint_right"])
        leader_left = canonical_joint_state(messages["leader_action_left"])
        leader_right = canonical_joint_state(messages["leader_action_right"])
        action_left = np.asarray(leader_left["position"])
        action_right = np.asarray(leader_right["position"])
        qpos_left = np.asarray(follower_left["position"])
        qpos_right = np.asarray(follower_right["position"])
        if any(np.allclose(values, 0.0) for values in (qpos_left, qpos_right, action_left, action_right)):
            raise ValueError("all-zero follower qpos or leader action")

        observation = {
            "images": {
                self.camera_names[0]: self._image(messages["rgb_front"]),
                self.camera_names[1]: self._image(messages["rgb_left"]),
                self.camera_names[2]: self._image(messages["rgb_right"]),
            },
            "qpos": np.concatenate((qpos_left, qpos_right)),
            "qvel": np.concatenate(
                (
                    follower_left["velocity"],
                    follower_right["velocity"],
                )
            ),
            "effort": np.concatenate(
                (
                    follower_left["effort"],
                    follower_right["effort"],
                )
            ),
            "eef_pose": np.concatenate(
                (
                    self._eef(messages["follower_eef_left"], follower_left["position"]),
                    self._eef(messages["follower_eef_right"], follower_right["position"]),
                )
            ),
        }
        if self.use_depth:
            observation["images_depth"] = {
                self.camera_names[0]: self._image(messages["depth_front"], depth=True),
                self.camera_names[1]: self._image(messages["depth_left"], depth=True),
                self.camera_names[2]: self._image(messages["depth_right"], depth=True),
            }
        return observation, np.concatenate((action_left, action_right)), frame_ns, source_ns

    def warn_throttled(self, message):
        now = time.monotonic()
        if message != self._last_warning[0] or now - self._last_warning[1] >= 2.0:
            self.get_logger().warning(message)
            self._last_warning = (message, now)

    def record(self, keyboard):
        topic_map = {name: str(self.get_parameter("topics." + name).value) for name in self.queues}
        buffer = EpisodeBuffer(self.camera_names, self.use_depth, self.frame_rate, topic_map)
        interval = 1.0 / self.frame_rate
        next_frame = time.monotonic()
        print("Recording: SPACE stops the episode")
        while rclpy.ok():
            if keyboard.get_key() == " ":
                return buffer
            rclpy.spin_once(self, timeout_sec=min(0.02, max(0.0, next_frame - time.monotonic())))
            now = time.monotonic()
            if now < next_frame:
                continue
            next_frame = now + interval
            try:
                sample = self.snapshot()
                if sample is None:
                    self.warn_throttled("waiting for synchronized streams")
                    continue
                observation, action, frame_ns, source_ns = sample
                buffer.append(observation, action, frame_ns=frame_ns, source_ns=source_ns)
                print(f"\rframes: {len(buffer)}", end="", flush=True)
            except (KeyError, ValueError) as error:
                self.warn_throttled(f"sample skipped: {error}")
        return buffer


def main(args=None):
    rclpy.init(args=args)
    node = Collector()
    keyboard = Keyboard()
    try:
        keyboard.setup()
        dataset_dir = os.path.expanduser(str(node.get_parameter("dataset_dir").value))
        task_dir = os.path.join(dataset_dir, str(node.get_parameter("task_name").value))
        requested_index = int(node.get_parameter("episode_index").value)
        episode_index = next_episode_index(task_dir) if requested_index == 0 else requested_index
        print("ENTER=start, SPACE=stop, then s=save or q=discard, Ctrl+C=exit")
        while rclpy.ok():
            print(f"\nEpisode {episode_index}: press ENTER to start")
            if keyboard.wait_for(("\n", "\r"), node) is None:
                break
            node.reset()
            buffer = node.record(keyboard)
            print(f"\nRecorded {len(buffer)} frames. Press s to save or q to discard")
            choice = keyboard.wait_for(("s", "S", "q", "Q"), node)
            if choice is None:
                break
            if choice.lower() == "s":
                if len(buffer) == 0:
                    print("Nothing saved: episode has zero frames")
                else:
                    path = buffer.save(os.path.join(task_dir, f"episode_{episode_index}.hdf5"))
                    print(f"Saved {path}")
                    episode_index += 1
            else:
                print(f"Discarded {len(buffer)} frames")
    except KeyboardInterrupt:
        print("\nCollection stopped")
    finally:
        keyboard.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
