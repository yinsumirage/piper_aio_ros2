"""Convert one whitelisted rosbag directory into one schema-v1 HDF5 episode."""

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys

import h5py
import numpy as np

from .bag_config import load_stream_config
from .bag_reader import index_bag, open_reader, stream_report
from .episode import RGB_SHAPE, set_schema_attrs, write_action_datasets, write_timestamp_datasets
from .joints import canonical_joint_state
from .sync import build_sync_plan


def _stream_by(streams, kind, side=None):
    matches = [
        name
        for name, spec in streams.items()
        if spec["kind"] == kind and (side is None or spec.get("side") == side)
    ]
    if len(matches) != 1:
        raise ValueError(f"need exactly one {kind} stream" + (f" for {side}" if side else ""))
    return matches[0]


def _rpy(pose):
    x, y, z, w = pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    sin_pitch = 2 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2, sin_pitch) if abs(sin_pitch) >= 1 else math.asin(sin_pitch)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


def _eef_values(message, gripper):
    pose = message.pose
    return (
        pose.position.x,
        pose.position.y,
        pose.position.z,
        *_rpy(pose),
        gripper,
    )


def _percentiles(values):
    values = np.abs(np.asarray(values, dtype=np.int64))
    return {
        "p50": int(np.percentile(values, 50)),
        "p95": int(np.percentile(values, 95)),
        "max": int(np.max(values)),
    } if len(values) else {"p50": None, "p95": None, "max": None}


def _write_selected_images(root, bag_path, streams, entries, frames):
    from cv_bridge import CvBridge
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    rgb_streams = [name for name, spec in streams.items() if spec["kind"] == "rgb"]
    image_group = root["observations"].create_group("images")
    datasets = {
        name: image_group.create_dataset(
            streams[name]["camera"], shape=(len(frames),) + RGB_SHAPE, dtype=np.uint8, chunks=(1,) + RGB_SHAPE
        )
        for name in rgb_streams
    }
    selected = {
        streams[name]["topic"]: {
            entries[name][frame["indices"][name]]["ordinal"]: frame_index
            for frame_index, frame in enumerate(frames)
        }
        for name in rgb_streams
    }
    topic_to_stream = {streams[name]["topic"]: name for name in rgb_streams}
    reader = open_reader(bag_path)
    bag_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    message_types = {topic: get_message(bag_types[topic]) for topic in selected}
    ordinals = Counter()
    written = Counter()
    bridge = CvBridge()
    while reader.has_next():
        topic, serialized, _ = reader.read_next()
        if topic not in selected:
            continue
        ordinal = ordinals[topic]
        ordinals[topic] += 1
        if ordinal not in selected[topic]:
            continue
        image = np.asarray(bridge.imgmsg_to_cv2(deserialize_message(serialized, message_types[topic]), "rgb8"))
        if image.shape != RGB_SHAPE or image.dtype != np.uint8:
            raise ValueError(f"{topic} image must be uint8 {RGB_SHAPE}, got {image.dtype} {image.shape}")
        datasets[topic_to_stream[topic]][selected[topic][ordinal]] = image
        written[topic] += 1
    missing = [topic for topic in selected if written[topic] != len(frames)]
    if missing:
        raise ValueError("selected images were not found in second pass: " + ", ".join(missing))


def convert(bag_path, output_path, config_path, qc_path=None, fps=30.0, allow_intent_only=False):
    streams = load_stream_config(config_path)
    output = Path(output_path).expanduser().resolve()
    qc_output = Path(qc_path).expanduser().resolve() if qc_path else output.with_suffix(".qc.json")
    if output.exists() or qc_output.exists():
        raise FileExistsError(output if output.exists() else qc_output)
    bag_types, entries = index_bag(bag_path, streams)
    topics = stream_report(streams, bag_types, entries)
    errors = [
        f"{name}: expected {item['expected_type']}, bag has {item['bag_type']}"
        for name, item in topics.items()
        if item["bag_type"] is not None and item["bag_type"] != item["expected_type"]
    ]
    if errors:
        raise ValueError("; ".join(errors))

    rgb = [name for name, spec in streams.items() if spec["kind"] == "rgb"]
    state = [_stream_by(streams, "state", side) for side in ("left", "right")]
    eef = [_stream_by(streams, "eef", side) for side in ("left", "right")]
    intent = [_stream_by(streams, "intent", side) for side in ("left", "right")]
    executed = [_stream_by(streams, "executed", side) for side in ("left", "right")]
    required = rgb + state + eef + intent
    executed_present = [bool(entries[name]) for name in executed]
    if any(executed_present) and not all(executed_present):
        raise ValueError("executed action streams are only partially present")
    if all(executed_present):
        action_source = "executed"
        required += executed
    elif allow_intent_only:
        action_source = "intent"
    else:
        raise ValueError("executed actions are absent; pass --allow-intent-only to create an intent-only episode")

    stream_times = {name: [entry["source_ns"] for entry in stream_entries] for name, stream_entries in entries.items()}
    kinds = {name: spec["kind"] for name, spec in streams.items()}
    plan = build_sync_plan(stream_times, kinds, required, fps)
    frames = plan["valid_frames"]
    if not frames:
        raise ValueError("no valid synchronized frames")

    qpos, qvel, effort, eef_pose, intents, executed_actions = [], [], [], [], [], []
    source_ns = {name: [] for name in required}
    deltas = {name: [] for name in required}
    for frame in frames:
        selected = {
            name: entries[name][frame["indices"][name]]["message"]
            for name in required
            if streams[name]["kind"] != "rgb"
        }
        followers = [canonical_joint_state(selected[name]) for name in state]
        qpos.append(followers[0]["position"] + followers[1]["position"])
        qvel.append(followers[0]["velocity"] + followers[1]["velocity"])
        effort.append(followers[0]["effort"] + followers[1]["effort"])
        eef_pose.append(
            _eef_values(selected[eef[0]], followers[0]["position"][6])
            + _eef_values(selected[eef[1]], followers[1]["position"][6])
        )
        leader = [canonical_joint_state(selected[name])["position"] for name in intent]
        intents.append(leader[0] + leader[1])
        if action_source == "executed":
            command = [canonical_joint_state(selected[name])["position"] for name in executed]
            executed_actions.append(command[0] + command[1])
        else:
            executed_actions.append((0.0,) * 14)
        for name in required:
            entry = entries[name][frame["indices"][name]]
            source_ns[name].append(entry["source_ns"])
            deltas[name].append(frame["sync_delta_ns"][name])

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    topic_map = {name: spec["topic"] for name, spec in streams.items()}
    try:
        with h5py.File(temporary, "w") as root:
            set_schema_attrs(root, fps, action_source, topic_map, "bag_to_hdf5")
            root.attrs["timestamp_source"] = json.dumps(
                {name: topics[name]["timestamp_source"] for name in required}, sort_keys=True
            )
            observations = root.create_group("observations")
            observations.create_dataset("qpos", data=np.asarray(qpos, dtype=np.float64))
            observations.create_dataset("qvel", data=np.asarray(qvel, dtype=np.float64))
            observations.create_dataset("effort", data=np.asarray(effort, dtype=np.float64))
            observations.create_dataset("eef_pose", data=np.asarray(eef_pose, dtype=np.float64))
            _write_selected_images(root, bag_path, streams, entries, frames)
            valid = np.ones(len(frames), dtype=np.bool_) if action_source == "executed" else np.zeros(len(frames), dtype=np.bool_)
            write_action_datasets(root, intents, executed_actions, valid, action_source)
            root.create_dataset(
                "collect",
                data=["teleop"] * len(frames),
                dtype=h5py.string_dtype(encoding="utf-8"),
            )
            write_timestamp_datasets(root, [frame["frame_ns"] for frame in frames], source_ns, deltas)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    qc = {
        "ok": True,
        "bag": str(bag_path),
        "output": str(output),
        "topics": topics,
        "overlap_ns": plan["overlap_ns"],
        "candidate_frames": plan["candidate_frames"],
        "valid_frames": len(frames),
        "dropped": plan["dropped"],
        "sync_delta_ns": {name: _percentiles(values) for name, values in deltas.items()},
        "duplicate_image_selections": plan["duplicate_image_selections"],
        "action_source": action_source,
    }
    qc_output.parent.mkdir(parents=True, exist_ok=True)
    qc_output.write_text(json.dumps(qc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, qc_output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bag")
    parser.add_argument("output")
    parser.add_argument("--config", required=True)
    parser.add_argument("--qc")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--allow-intent-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, qc = convert(
            args.bag, args.output, args.config, args.qc, args.fps, args.allow_intent_only
        )
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "output": str(output), "qc": str(qc)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
