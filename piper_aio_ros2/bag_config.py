"""Load the explicit rosbag stream whitelist."""

from pathlib import Path

import yaml


ALLOWED_KINDS = {"rgb", "state", "eef", "intent", "executed"}


def load_stream_config(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    streams = data.get("streams", {}) if isinstance(data, dict) else {}
    if not streams:
        raise ValueError("stream config contains no streams")
    topics = set()
    cameras = set()
    for name, spec in streams.items():
        if not isinstance(spec, dict) or not {"topic", "type", "kind"} <= set(spec):
            raise ValueError(f"stream {name} needs topic, type and kind")
        if spec["kind"] not in ALLOWED_KINDS:
            raise ValueError(f"stream {name} has invalid kind {spec['kind']}")
        if not str(spec["topic"]).startswith("/") or spec["topic"] in topics:
            raise ValueError(f"stream {name} has invalid or duplicate topic")
        topics.add(spec["topic"])
        if spec["kind"] == "rgb":
            camera = spec.get("camera")
            if not camera or camera in cameras:
                raise ValueError(f"stream {name} needs a unique camera")
            cameras.add(camera)
    if len(cameras) != 3:
        raise ValueError("exactly three RGB streams are required")
    return streams
