"""Bounded RealSense device and ROS image-stream diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
import time

from .cameras import (
    CAMERA_SPECS,
    CameraConfigError,
    CameraInventoryError,
    discover_devices,
    load_camera_config,
    require_online,
)


def _stamp_ns(message):
    return message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec


def _policy_name(value):
    return getattr(value, "name", str(value))


def _is_performance_issue(error):
    return "measured rate" in error or "frame gaps" in error


def _check_ros(serials, duration, roles):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    reports = {
        role: {
            "serial": serials[role],
            "topic": spec["topic"],
            "expected_type": "sensor_msgs/msg/Image",
            "received": 0,
            "receive_times": [],
            "stamps_ns": [],
        }
        for role, spec in CAMERA_SPECS.items()
        if role in roles
    }
    rclpy.init()
    node = rclpy.create_node("piper_aio_camera_status")
    subscriptions = []
    try:
        for role in roles:
            spec = CAMERA_SPECS[role]
            def callback(message, role=role):
                report = reports[role]
                report["received"] += 1
                report["receive_times"].append(time.monotonic())
                report["stamps_ns"].append(_stamp_ns(message))
                report["encoding"] = message.encoding
                report["width"] = message.width
                report["height"] = message.height

            subscriptions.append(node.create_subscription(Image, spec["topic"], callback, qos_profile_sensor_data))
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(0.2, max(0.0, deadline - time.monotonic())))

        graph_types = {name: types for name, types in node.get_topic_names_and_types()}
        errors = []
        output = {}
        for role, report in reports.items():
            times = report.pop("receive_times")
            stamps = report.pop("stamps_ns")
            actual_types = graph_types.get(report["topic"], [])
            publisher_profiles = []
            for info in node.get_publishers_info_by_topic(report["topic"]):
                publisher_profiles.append(
                    {
                        "node_name": info.node_name,
                        "node_namespace": info.node_namespace,
                        "reliability": _policy_name(info.qos_profile.reliability),
                        "durability": _policy_name(info.qos_profile.durability),
                    }
                )
            hz = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
            receive_gaps = [b - a for a, b in zip(times, times[1:])]
            stamp_gaps = [(b - a) / 1e9 for a, b in zip(stamps, stamps[1:])]
            report.update(
                actual_types=actual_types,
                publisher_count=len(publisher_profiles),
                publishers=publisher_profiles,
                hz=round(hz, 3),
                max_receive_gap_ms=round(max(receive_gaps, default=0.0) * 1000, 3),
                max_stamp_gap_ms=round(max(stamp_gaps, default=0.0) * 1000, 3),
                receive_gaps_over_100ms=sum(gap > 0.1 for gap in receive_gaps),
                stamp_gaps_over_100ms=sum(gap > 0.1 for gap in stamp_gaps),
                timestamps_positive=bool(stamps) and all(stamp > 0 for stamp in stamps),
                timestamps_monotonic=bool(stamps) and all(b > a for a, b in zip(stamps, stamps[1:])),
            )
            role_errors = []
            if report["expected_type"] not in actual_types:
                role_errors.append("topic missing or type mismatch")
            if report["publisher_count"] != 1:
                role_errors.append(f"publisher count is {report['publisher_count']}, expected exactly 1")
            if report["received"] < 2:
                role_errors.append("fewer than 2 images received")
            if report.get("encoding", "").lower() != "rgb8":
                role_errors.append(f"encoding is {report.get('encoding', '<missing>')}, expected rgb8")
            if (report.get("width"), report.get("height")) != (640, 480):
                role_errors.append(f"shape is {report.get('width', 0)}x{report.get('height', 0)}, expected 640x480")
            if not 27.0 <= hz <= 33.0:
                role_errors.append(f"measured rate {hz:.2f} Hz is outside 27-33 Hz")
            if not report["timestamps_positive"] or not report["timestamps_monotonic"]:
                role_errors.append("header timestamps are missing or moved backwards")
            if report["receive_gaps_over_100ms"] or report["stamp_gaps_over_100ms"]:
                role_errors.append("one or more frame gaps exceeded 100 ms")
            report["warnings"] = [error for error in role_errors if _is_performance_issue(error)]
            report["errors"] = [error for error in role_errors if not _is_performance_issue(error)]
            errors.extend(f"{role}: {error}" for error in role_errors)
            output[role] = report
        return output, errors
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate configured RealSense devices and image topics")
    parser.add_argument("--config", required=True)
    parser.add_argument("--timeout", type=float, default=10.0, help="inventory timeout in seconds")
    parser.add_argument("--sample-seconds", type=float, default=10.0)
    parser.add_argument("--devices-only", action="store_true")
    parser.add_argument("--role", choices=("all", *CAMERA_SPECS), default="all")
    parser.add_argument(
        "--require-nominal-rate",
        action="store_true",
        help="fail unless each selected stream is 27-33 Hz with no frame gap over 100 ms",
    )
    args = parser.parse_args(argv)
    report = {"ok": False, "config": args.config, "errors": []}
    try:
        if args.sample_seconds <= 0:
            raise CameraConfigError("sample duration must be positive")
        serials = load_camera_config(args.config)
        devices = discover_devices(args.timeout)
        extra = require_online(serials, devices)
        report.update(serials=serials, devices=devices, extra_online_serials=extra)
        if not args.devices_only:
            roles = tuple(CAMERA_SPECS) if args.role == "all" else (args.role,)
            streams, errors = _check_ros(serials, args.sample_seconds, roles)
            report["streams"] = streams
            rate_errors = [error for error in errors if _is_performance_issue(error)]
            report["warnings"] = rate_errors
            report["errors"].extend(error for error in errors if error not in rate_errors)
            if args.require_nominal_rate:
                report["errors"].extend(rate_errors)
    except (CameraConfigError, CameraInventoryError) as exc:
        report["errors"].append(str(exc))
    except KeyboardInterrupt:
        report["errors"].append("interrupted by user")
    report["ok"] = not report["errors"]
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
