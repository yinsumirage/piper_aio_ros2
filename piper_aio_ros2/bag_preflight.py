"""Read-only ROS graph and disk preflight for whitelist rosbag recording."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from .bag_config import load_stream_config


def _existing_parent(path):
    path = Path(path).expanduser().resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    parser.add_argument("--list-topics", action="store_true")
    args = parser.parse_args(argv)
    streams = load_stream_config(args.config)
    if args.list_topics:
        print("\n".join(spec["topic"] for spec in streams.values()))
        return 0
    if not args.output_dir:
        parser.error("--output-dir is required")

    import rclpy

    output = Path(args.output_dir).expanduser().resolve()
    free_bytes = shutil.disk_usage(_existing_parent(output)).free
    report = {
        "ok": True,
        "output_dir": str(output),
        "output_exists": output.exists(),
        "free_bytes": free_bytes,
        "minimum_free_bytes": int(args.min_free_gb * 1024**3),
        "preflight_creates_publishers": False,
        "streams": {},
        "unexpected_control_publishers": [],
        "errors": [],
    }
    if output.exists():
        report["errors"].append("output directory already exists")
    if free_bytes < report["minimum_free_bytes"]:
        report["errors"].append("insufficient free disk space")

    rclpy.init()
    node = rclpy.create_node("piper_aio_bag_preflight")
    try:
        rclpy.spin_once(node, timeout_sec=0.5)
        graph_types = {name: types for name, types in node.get_topic_names_and_types()}
        whitelist = {spec["topic"] for spec in streams.values()}
        for name, spec in streams.items():
            actual_types = graph_types.get(spec["topic"], [])
            publishers = [
                {"node_name": info.node_name, "node_namespace": info.node_namespace}
                for info in node.get_publishers_info_by_topic(spec["topic"])
            ]
            stream_report = {
                "topic": spec["topic"],
                "expected_type": spec["type"],
                "actual_types": actual_types,
                "publisher_count": len(publishers),
                "publishers": publishers,
            }
            report["streams"][name] = stream_report
            if not actual_types:
                report["errors"].append(f"{name}: topic missing")
            elif spec["type"] not in actual_types:
                report["errors"].append(f"{name}: type mismatch")
            if not publishers:
                report["errors"].append(f"{name}: no publisher")

        for topic in graph_types:
            lowered = topic.lower()
            if topic in whitelist or not any(word in lowered for word in ("joint_ctrl", "gripper_ctrl", "/control")):
                continue
            for info in node.get_publishers_info_by_topic(topic):
                report["unexpected_control_publishers"].append(
                    {"topic": topic, "node_name": info.node_name, "node_namespace": info.node_namespace}
                )
        if report["unexpected_control_publishers"]:
            report["errors"].append("unexpected publishers exist on non-whitelisted control topics")
    finally:
        node.destroy_node()
        rclpy.shutdown()

    report["ok"] = not report["errors"]
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
