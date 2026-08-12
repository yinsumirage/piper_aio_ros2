"""Validate canonical Piper HDF5 episode schema and synchronization."""

import argparse
import json
import sys

import h5py
import numpy as np

from .episode import RGB_SHAPE, SCHEMA_VERSION, VECTOR_SIZE
from .joints import DUAL_JOINT_ORDER


def _attribute(root, name, errors):
    if name not in root.attrs:
        errors.append(f"missing root attr {name}")
        return None
    value = root.attrs[name]
    return value.decode() if isinstance(value, bytes) else value


def validate(path):
    errors = []
    report = {"path": str(path), "ok": False, "errors": errors}
    try:
        with h5py.File(path, "r") as root:
            schema_version = str(_attribute(root, "schema_version", errors))
            fps = _attribute(root, "fps", errors)
            action_source = _attribute(root, "action_source", errors)
            joint_order = _attribute(root, "joint_order", errors)
            topic_map = _attribute(root, "topic_map", errors)
            created_by = _attribute(root, "created_by", errors)
            if schema_version != SCHEMA_VERSION:
                errors.append(f"schema_version must be {SCHEMA_VERSION}")
            try:
                if float(fps) <= 0:
                    errors.append("fps must be positive")
            except (TypeError, ValueError):
                errors.append("fps is invalid")
            try:
                if tuple(json.loads(joint_order)) != DUAL_JOINT_ORDER:
                    errors.append("joint_order is not canonical left7+right7")
            except (TypeError, ValueError, json.JSONDecodeError):
                errors.append("joint_order is invalid JSON")
            try:
                if not isinstance(json.loads(topic_map), dict):
                    errors.append("topic_map must be a JSON object")
            except (TypeError, json.JSONDecodeError):
                errors.append("topic_map is invalid JSON")
            if not isinstance(created_by, str) or not created_by:
                errors.append("created_by must be a non-empty string")

            required = [
                "/observations/qpos",
                "/observations/qvel",
                "/observations/effort",
                "/observations/eef_pose",
                "/action",
                "/actions/intent",
                "/actions/executed",
                "/actions/executed_valid",
                "/collect",
                "/timestamps/frame_ns",
                "/timestamps/source_ns",
                "/sync_delta_ns",
                "/observations/images",
            ]
            for key in required:
                if key not in root:
                    errors.append(f"missing {key}")
            if errors:
                return report

            frame_ns = root["/timestamps/frame_ns"][:]
            frames = len(frame_ns)
            report.update(frames=frames, action_source=action_source)
            if frame_ns.dtype.kind not in "iu" or frame_ns.shape != (frames,):
                errors.append("frame_ns must be an integer vector")
            if frames == 0:
                errors.append("episode has no frames")
            elif np.any(np.diff(frame_ns) <= 0):
                errors.append("frame_ns must be strictly increasing")

            for key in ("qpos", "qvel", "effort", "eef_pose"):
                dataset = root[f"/observations/{key}"]
                if dataset.shape != (frames, VECTOR_SIZE):
                    errors.append(f"{key} must have shape ({frames}, 14)")
                if dataset.dtype.kind != "f" or not np.all(np.isfinite(dataset[:])):
                    errors.append(f"{key} must be finite floating point")
            for key in ("/action", "/actions/intent", "/actions/executed"):
                dataset = root[key]
                if dataset.shape != (frames, VECTOR_SIZE):
                    errors.append(f"{key} must have shape ({frames}, 14)")
                if dataset.dtype.kind != "f" or not np.all(np.isfinite(dataset[:])):
                    errors.append(f"{key} must be finite floating point")
            valid = root["/actions/executed_valid"][:]
            if valid.shape != (frames,) or valid.dtype.kind != "b":
                errors.append("executed_valid must be a boolean frame vector")
            elif action_source == "executed":
                if not np.all(valid):
                    errors.append("executed action_source requires all executed_valid=true")
                if not np.array_equal(root["/action"][:], root["/actions/executed"][:]):
                    errors.append("/action does not equal /actions/executed")
            elif action_source == "intent":
                if np.any(valid):
                    errors.append("intent action_source requires all executed_valid=false")
                if not np.array_equal(root["/action"][:], root["/actions/intent"][:]):
                    errors.append("/action does not equal /actions/intent")
            else:
                errors.append("action_source must be executed or intent")

            images = root["/observations/images"]
            if len(images) != 3:
                errors.append("exactly three RGB cameras are required")
            for camera, dataset in images.items():
                if dataset.shape != (frames,) + RGB_SHAPE or dataset.dtype != np.dtype(np.uint8):
                    errors.append(f"RGB {camera} must be uint8 ({frames}, {RGB_SHAPE})")
            if "/observations/images_depth" in root:
                depth = root["/observations/images_depth"]
                if len(depth) != 3:
                    errors.append("depth must contain exactly three cameras")
                for camera, dataset in depth.items():
                    if dataset.shape != (frames, 480, 640) or dataset.dtype != np.dtype(np.uint16):
                        errors.append(f"depth {camera} must be uint16 ({frames}, 480, 640)")
            collect = root["/collect"]
            if collect.shape != (frames,) or h5py.check_string_dtype(collect.dtype) is None:
                errors.append("collect must be a UTF-8 frame vector")

            sources = root["/timestamps/source_ns"]
            deltas = root["/sync_delta_ns"]
            if set(sources) != set(deltas):
                errors.append("source_ns and sync_delta_ns streams differ")
            for stream in set(sources) & set(deltas):
                source = sources[stream][:]
                delta = deltas[stream][:]
                if source.shape != (frames,) or delta.shape != (frames,):
                    errors.append(f"timestamp stream {stream} has wrong shape")
                    continue
                if source.dtype.kind not in "iu" or delta.dtype.kind not in "iu":
                    errors.append(f"timestamp stream {stream} must be integer")
                    continue
                if np.any(source <= 0) or np.any(np.diff(source) < 0):
                    errors.append(f"source timestamps for {stream} must be positive and monotonic")
                if not np.array_equal(source - frame_ns, delta):
                    errors.append(f"sync delta for {stream} does not equal source-frame")
                action_stream = "action" in stream
                tolerance = 20_000_000 if stream.startswith("rgb_") or action_stream else 10_000_000
                if np.any(np.abs(delta) > tolerance):
                    errors.append(f"sync delta for {stream} exceeds {tolerance} ns")
                if action_stream and np.any(delta > 0):
                    errors.append(f"action stream {stream} selected a future message")
                if stream.startswith("rgb_") and len(np.unique(source)) != frames:
                    errors.append(f"RGB stream {stream} reuses source frames")
    except (OSError, ValueError) as error:
        errors.append(str(error))
    report["ok"] = not errors
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("episode")
    args = parser.parse_args(argv)
    report = validate(args.episode)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
