"""Pure-Python episode validation and HDF5 persistence."""

import json
import os
from pathlib import Path
import re

import h5py
import numpy as np

from .joints import DUAL_JOINT_ORDER


RGB_SHAPE = (480, 640, 3)
DEPTH_SHAPE = (480, 640)
VECTOR_SIZE = 14
SCHEMA_VERSION = "1"


def next_episode_index(directory):
    directory = Path(directory)
    if not directory.exists():
        return 0
    indices = []
    for path in directory.iterdir():
        match = re.fullmatch(r"episode_(\d+)\.hdf5", path.name)
        if match:
            indices.append(int(match.group(1)))
    return max(indices, default=-1) + 1


def set_schema_attrs(root, fps, action_source, topic_map, created_by):
    if action_source not in ("executed", "intent"):
        raise ValueError("action_source must be executed or intent")
    root.attrs.update(
        schema_version=SCHEMA_VERSION,
        fps=float(fps),
        action_source=action_source,
        joint_order=json.dumps(DUAL_JOINT_ORDER),
        topic_map=json.dumps(topic_map or {}, sort_keys=True),
        created_by=created_by,
    )


def write_action_datasets(root, intent, executed, executed_valid, action_source):
    intent = np.asarray(intent, dtype=np.float64)
    executed = np.asarray(executed, dtype=np.float64)
    valid = np.asarray(executed_valid, dtype=np.bool_)
    if intent.shape != executed.shape or intent.ndim != 2 or intent.shape[1:] != (VECTOR_SIZE,):
        raise ValueError("intent and executed must both have shape (frames, 14)")
    if valid.shape != (len(intent),):
        raise ValueError("executed_valid must have shape (frames,)")
    if action_source == "executed" and not np.all(valid):
        raise ValueError("executed action_source requires every executed frame to be valid")
    if action_source == "intent" and np.any(valid):
        raise ValueError("mixed intent/executed episodes are not supported")
    actions = root.create_group("actions")
    actions.create_dataset("intent", data=intent)
    actions.create_dataset("executed", data=executed)
    actions.create_dataset("executed_valid", data=valid)
    root.create_dataset("action", data=executed if action_source == "executed" else intent)


def write_timestamp_datasets(root, frame_ns, source_ns, sync_delta_ns):
    frame_ns = np.asarray(frame_ns, dtype=np.int64)
    timestamps = root.create_group("timestamps")
    timestamps.create_dataset("frame_ns", data=frame_ns)
    sources = timestamps.create_group("source_ns")
    deltas = root.create_group("sync_delta_ns")
    if set(source_ns) != set(sync_delta_ns):
        raise ValueError("source_ns and sync_delta_ns stream sets differ")
    for stream in sorted(source_ns):
        source = np.asarray(source_ns[stream], dtype=np.int64)
        delta = np.asarray(sync_delta_ns[stream], dtype=np.int64)
        if source.shape != frame_ns.shape or delta.shape != frame_ns.shape:
            raise ValueError(f"timestamp stream {stream} length differs from frame_ns")
        sources.create_dataset(stream, data=source)
        deltas.create_dataset(stream, data=delta)


class EpisodeBuffer:
    """In-memory frames with schema-v1 and legacy piper-aio keys."""

    def __init__(self, camera_names, use_depth=False, fps=30.0, topic_map=None, created_by="collect"):
        if len(camera_names) != 3 or len(set(camera_names)) != 3:
            raise ValueError("camera_names must contain three unique names")
        self.camera_names = tuple(camera_names)
        self.use_depth = bool(use_depth)
        self.fps = float(fps)
        self.topic_map = dict(topic_map or {})
        self.created_by = created_by
        self._frames = []

    def __len__(self):
        return len(self._frames)

    @staticmethod
    def _array(value, shape, name, dtype=None):
        array = np.asarray(value, dtype=dtype)
        if array.shape != shape:
            raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
        if np.issubdtype(array.dtype, np.floating) and not np.all(np.isfinite(array)):
            raise ValueError(f"{name} contains non-finite values")
        return np.array(array, copy=True)

    def append(self, observation, intent, executed=None, frame_ns=None, source_ns=None):
        intent = self._array(intent, (VECTOR_SIZE,), "intent", np.float64)
        frame = {
            "qpos": self._array(observation["qpos"], (VECTOR_SIZE,), "qpos", np.float64),
            "qvel": self._array(observation["qvel"], (VECTOR_SIZE,), "qvel", np.float64),
            "effort": self._array(observation["effort"], (VECTOR_SIZE,), "effort", np.float64),
            "eef_pose": self._array(observation["eef_pose"], (VECTOR_SIZE,), "eef_pose", np.float64),
            "intent": intent,
            "executed": np.zeros(VECTOR_SIZE, dtype=np.float64)
            if executed is None
            else self._array(executed, (VECTOR_SIZE,), "executed", np.float64),
            "executed_valid": executed is not None,
            "frame_ns": int(frame_ns if frame_ns is not None else len(self._frames) * 1e9 / self.fps),
            "source_ns": {name: int(value) for name, value in (source_ns or {}).items()},
            "images": {},
        }
        for camera in self.camera_names:
            frame["images"][camera] = self._array(
                observation["images"][camera], RGB_SHAPE, f"images/{camera}", np.uint8
            )
        if self.use_depth:
            frame["images_depth"] = {}
            for camera in self.camera_names:
                frame["images_depth"][camera] = self._array(
                    observation["images_depth"][camera], DEPTH_SHAPE, f"images_depth/{camera}", np.uint16
                )
        self._frames.append(frame)

    def save(self, output_path):
        if not self._frames:
            raise ValueError("cannot save an empty episode")
        valid = [frame["executed_valid"] for frame in self._frames]
        if any(valid) and not all(valid):
            raise ValueError("mixed intent/executed frames cannot be saved")
        action_source = "executed" if all(valid) else "intent"
        output = Path(output_path)
        if output.suffix != ".hdf5":
            output = output.with_suffix(".hdf5")
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        if temporary.exists():
            raise FileExistsError(temporary)

        try:
            with h5py.File(temporary, "w", rdcc_nbytes=2 * 1024**2) as root:
                set_schema_attrs(root, self.fps, action_source, self.topic_map, self.created_by)
                observations = root.create_group("observations")
                images = observations.create_group("images")
                for camera in self.camera_names:
                    data = np.stack([frame["images"][camera] for frame in self._frames])
                    images.create_dataset(camera, data=data, chunks=(1,) + RGB_SHAPE)
                if self.use_depth:
                    images_depth = observations.create_group("images_depth")
                    for camera in self.camera_names:
                        data = np.stack([frame["images_depth"][camera] for frame in self._frames])
                        images_depth.create_dataset(camera, data=data, chunks=(1,) + DEPTH_SHAPE)

                for name in ("qpos", "qvel", "effort", "eef_pose"):
                    observations.create_dataset(name, data=np.stack([frame[name] for frame in self._frames]))
                write_action_datasets(
                    root,
                    np.stack([frame["intent"] for frame in self._frames]),
                    np.stack([frame["executed"] for frame in self._frames]),
                    valid,
                    action_source,
                )
                root.create_dataset(
                    "collect",
                    data=["teleop"] * len(self._frames),
                    dtype=h5py.string_dtype(encoding="utf-8"),
                )
                frame_ns = [frame["frame_ns"] for frame in self._frames]
                stream_names = set(self._frames[0]["source_ns"])
                if any(set(frame["source_ns"]) != stream_names for frame in self._frames):
                    raise ValueError("every frame must contain the same source timestamp streams")
                source_ns = {
                    name: [frame["source_ns"][name] for frame in self._frames]
                    for name in sorted(stream_names)
                }
                write_timestamp_datasets(
                    root,
                    frame_ns,
                    source_ns,
                    {name: np.asarray(values) - frame_ns for name, values in source_ns.items()},
                )
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return output
