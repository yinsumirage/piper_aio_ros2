"""Canonical Piper joint ordering without ROS imports."""

import math


JOINT_ORDER = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper")
DUAL_JOINT_ORDER = tuple(f"left_{name}" for name in JOINT_ORDER) + tuple(
    f"right_{name}" for name in JOINT_ORDER
)


def canonical_values(names, values, field, allow_missing=False):
    """Map a named JointState field to joint1..joint6,gripper."""
    names = tuple(names)
    values = tuple(values)
    if len(set(names)) != len(names):
        raise ValueError("JointState.name contains duplicates")
    if values and len(values) != len(names) and not (allow_missing and len(values) < len(names)):
        raise ValueError(f"{field} length {len(values)} does not match name length {len(names)}")
    if not values:
        if allow_missing:
            return (0.0,) * len(JOINT_ORDER)
        raise ValueError(f"{field} is missing")

    by_name = dict(zip(names, values))
    result = []
    for name in JOINT_ORDER[:-1]:
        if name not in by_name:
            if allow_missing:
                result.append(0.0)
                continue
            raise ValueError(f"{field} is missing {name}")
        result.append(float(by_name[name]))

    if "joint7" in by_name and "joint8" in by_name:
        result.append(float(by_name["joint7"]) - float(by_name["joint8"]))
    elif "gripper" in by_name:
        result.append(float(by_name["gripper"]))
    elif allow_missing:
        result.append(0.0)
    else:
        raise ValueError(f"{field} is missing gripper (or joint7/joint8)")

    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{field} contains non-finite values")
    return tuple(result)


def canonical_joint_state(message):
    """Return canonical position, velocity and effort tuples for a JointState-like object."""
    names = getattr(message, "name", ())
    return {
        "position": canonical_values(names, getattr(message, "position", ()), "position"),
        "velocity": canonical_values(names, getattr(message, "velocity", ()), "velocity", allow_missing=True),
        "effort": canonical_values(names, getattr(message, "effort", ()), "effort", allow_missing=True),
    }
