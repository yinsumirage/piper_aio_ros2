"""Pure-Python episode validation and HDF5 persistence."""

from pathlib import Path
import os
import re

import h5py
import numpy as np


RGB_SHAPE = (480, 640, 3)
DEPTH_SHAPE = (480, 640)
VECTOR_SIZE = 14


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


class EpisodeBuffer:
    """In-memory frames with the legacy piper-aio HDF5 contract."""

    def __init__(self, camera_names, use_depth=False):
        if len(camera_names) != 3 or len(set(camera_names)) != 3:
            raise ValueError("camera_names must contain three unique names")
        self.camera_names = tuple(camera_names)
        self.use_depth = bool(use_depth)
        self._frames = []

    def __len__(self):
        return len(self._frames)

    @staticmethod
    def _array(value, shape, name, dtype=None):
        array = np.asarray(value, dtype=dtype)
        if array.shape != shape:
            raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
        return np.array(array, copy=True)

    def append(self, observation, action):
        frame = {
            "qpos": self._array(observation["qpos"], (VECTOR_SIZE,), "qpos", np.float64),
            "qvel": self._array(observation["qvel"], (VECTOR_SIZE,), "qvel", np.float64),
            "effort": self._array(observation["effort"], (VECTOR_SIZE,), "effort", np.float64),
            "eef_pose": self._array(observation["eef_pose"], (VECTOR_SIZE,), "eef_pose", np.float64),
            "action": self._array(action, (VECTOR_SIZE,), "action", np.float64),
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
                root.create_dataset("action", data=np.stack([frame["action"] for frame in self._frames]))
                root.create_dataset(
                    "collect",
                    data=["teleop"] * len(self._frames),
                    dtype=h5py.string_dtype(encoding="utf-8"),
                )
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return output
