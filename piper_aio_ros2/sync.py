"""Pure timestamp selection used by rosbag conversion."""

from bisect import bisect_left, bisect_right
from collections import Counter


RGB_TOLERANCE_NS = 20_000_000
STATE_TOLERANCE_NS = 10_000_000
ACTION_TOLERANCE_NS = 20_000_000


class DuplicateImageSelection(ValueError):
    pass


def message_time_ns(message, receive_time_ns):
    stamp = getattr(getattr(message, "header", None), "stamp", None)
    header_ns = 0 if stamp is None else int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
    return (header_ns, "header") if header_ns > 0 else (int(receive_time_ns), "receive")


def select_index(times, target_ns, tolerance_ns, causal=False):
    """Return an in-tolerance index, using nearest or latest-past selection."""
    if not times:
        return None
    if causal:
        index = bisect_right(times, target_ns) - 1
        return index if index >= 0 and target_ns - times[index] <= tolerance_ns else None
    right = bisect_left(times, target_ns)
    candidates = [index for index in (right - 1, right) if 0 <= index < len(times)]
    if not candidates:
        return None
    index = min(candidates, key=lambda item: (abs(times[item] - target_ns), times[item] > target_ns))
    return index if abs(times[index] - target_ns) <= tolerance_ns else None


def fixed_grid(start_ns, end_ns, fps=30.0):
    if fps <= 0 or end_ns < start_ns:
        return []
    count = int((end_ns - start_ns) * fps // 1_000_000_000) + 1
    return [start_ns + round(index * 1_000_000_000 / fps) for index in range(count)]


def build_sync_plan(stream_times, stream_kinds, required_streams, fps=30.0):
    missing = [name for name in required_streams if not stream_times.get(name)]
    if missing:
        raise ValueError("required streams have no messages: " + ", ".join(sorted(missing)))
    start_ns = max(stream_times[name][0] for name in required_streams)
    end_ns = min(stream_times[name][-1] for name in required_streams)
    if end_ns < start_ns:
        raise ValueError("required streams do not overlap")

    candidates = fixed_grid(start_ns, end_ns, fps)
    valid = []
    dropped = Counter()
    image_indices = {name: set() for name in required_streams if stream_kinds[name] == "rgb"}
    duplicate_counts = Counter()
    for target_ns in candidates:
        selection = {}
        deltas = {}
        failed = []
        for name in required_streams:
            kind = stream_kinds[name]
            tolerance = RGB_TOLERANCE_NS if kind == "rgb" else ACTION_TOLERANCE_NS if kind in (
                "intent",
                "executed",
            ) else STATE_TOLERANCE_NS
            index = select_index(stream_times[name], target_ns, tolerance, causal=kind in ("intent", "executed"))
            if index is None:
                failed.append(name)
                dropped[f"{name}:out_of_tolerance"] += 1
            else:
                selection[name] = index
                deltas[name] = stream_times[name][index] - target_ns
        if failed:
            continue
        for name, used in image_indices.items():
            index = selection[name]
            if index in used:
                duplicate_counts[name] += 1
            used.add(index)
        valid.append({"frame_ns": target_ns, "indices": selection, "sync_delta_ns": deltas})
    if duplicate_counts:
        details = ", ".join(f"{name}={count}" for name, count in sorted(duplicate_counts.items()))
        raise DuplicateImageSelection("repeated camera source selection: " + details)
    return {
        "overlap_ns": [start_ns, end_ns],
        "candidate_frames": len(candidates),
        "valid_frames": valid,
        "dropped": dict(sorted(dropped.items())),
        "duplicate_image_selections": dict(duplicate_counts),
    }
