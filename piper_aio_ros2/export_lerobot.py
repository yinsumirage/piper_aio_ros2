"""Export canonical HDF5 episodes to a local LeRobotDataset v3."""

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys

import h5py
import numpy as np

from .episode import RGB_SHAPE
from .joints import DUAL_JOINT_ORDER
from .validate_episode import validate


CAMERAS = ("cam_high", "cam_left_wrist", "cam_right_wrist")
EEF_ORDER = tuple(f"{side}_{name}" for side in ("left", "right") for name in (
    "x",
    "y",
    "z",
    "roll",
    "pitch",
    "yaw",
    "gripper",
))


def export(episodes, output, repo_id, task, allow_intent_only=False):
    if version("lerobot") != "0.6.0":
        raise RuntimeError(f"requires lerobot==0.6.0, found {version('lerobot')}")
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    episode_paths = [Path(path).expanduser().resolve() for path in episodes]
    if not episode_paths:
        raise ValueError("at least one HDF5 episode is required")

    fps = None
    action_source = None
    for path in episode_paths:
        report = validate(path)
        if not report["ok"]:
            raise ValueError(f"invalid episode {path}: {'; '.join(report['errors'])}")
        with h5py.File(path, "r") as root:
            source = root.attrs["action_source"]
            if source != "executed" and not allow_intent_only:
                raise ValueError(f"{path} is {source}; pass --allow-intent-only to export it")
            if action_source is None:
                action_source = source
            elif source != action_source:
                raise ValueError("all episodes must use the same action_source")
            episode_fps = float(root.attrs["fps"])
            fps = episode_fps if fps is None else fps
            if episode_fps != fps:
                raise ValueError("all episodes must use the same fps")
            if set(root["/observations/images"].keys()) != set(CAMERAS):
                raise ValueError(f"{path} does not contain the canonical three camera names")
    if not float(fps).is_integer():
        raise ValueError("LeRobotDataset requires integer fps")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    features = {
        "observation.state": {"dtype": "float32", "shape": (14,), "names": list(DUAL_JOINT_ORDER)},
        "observation.eef_pose": {"dtype": "float32", "shape": (14,), "names": list(EEF_ORDER)},
        "action": {"dtype": "float32", "shape": (14,), "names": list(DUAL_JOINT_ORDER)},
    }
    for camera in CAMERAS:
        features[f"observation.images.{camera}"] = {
            "dtype": "video",
            "shape": (3, RGB_SHAPE[0], RGB_SHAPE[1]),
            "names": ["channels", "height", "width"],
        }
    dataset = LeRobotDataset.create(
        repo_id=repo_id,
        fps=int(fps),
        features=features,
        root=output,
        robot_type="piper_dual_arm",
        use_videos=True,
    )
    try:
        for path in episode_paths:
            with h5py.File(path, "r") as root:
                for index in range(len(root["/action"])):
                    frame = {
                        "observation.state": root["/observations/qpos"][index].astype(np.float32),
                        "observation.eef_pose": root["/observations/eef_pose"][index].astype(np.float32),
                        "action": root["/action"][index].astype(np.float32),
                        "task": task,
                    }
                    for camera in CAMERAS:
                        frame[f"observation.images.{camera}"] = root[f"/observations/images/{camera}"][index]
                    dataset.add_frame(frame)
            dataset.save_episode()
    finally:
        dataset.finalize()
    return {"output": str(output), "repo_id": repo_id, "episodes": len(episode_paths), "fps": int(fps)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes", nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--allow-intent-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = export(args.episodes, args.output, args.repo_id, args.task, args.allow_intent_only)
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
