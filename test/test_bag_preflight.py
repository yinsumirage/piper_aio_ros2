import unittest

from piper_aio_ros2.bag_preflight import is_unexpected_control_topic


class BagPreflightControlTopicTest(unittest.TestCase):
    def test_official_follower_feedback_is_allowed(self):
        self.assertFalse(is_unexpected_control_topic("/follower_left/joint_ctrl"))
        self.assertFalse(is_unexpected_control_topic("/follower_right/joint_ctrl"))

    def test_whitelisted_bridge_command_is_allowed(self):
        topic = "/follower_left/joint_ctrl_cmd"
        self.assertFalse(is_unexpected_control_topic(topic, {topic}))

    def test_unapproved_command_and_enable_topics_are_rejected(self):
        for topic in (
            "/rogue/joint_ctrl",
            "/follower_left/joint_ctrl_cmd",
            "/follower_right/pos_cmd",
            "/follower_left/gripper_ctrl",
            "/follower_right/enable_flag",
            "/rogue/control/target",
        ):
            with self.subTest(topic=topic):
                self.assertTrue(is_unexpected_control_topic(topic))

    def test_similar_status_names_are_not_commands(self):
        self.assertFalse(is_unexpected_control_topic("/status/joint_controller_state"))
        self.assertFalse(is_unexpected_control_topic("/driver/enabled"))


if __name__ == "__main__":
    unittest.main()
