"""Pure mapping and safety state for the dual-arm teleop bridge."""

from dataclasses import dataclass
import math

from .joints import JOINT_ORDER


SIDES = ("left", "right")
MASTER_ARM_ORDER = JOINT_ORDER[:6]
MASTER_GRIPPER_ORDER = MASTER_ARM_ORDER + ("gripper", "joint7", "joint8")


def _named_values(names, values, expected, label):
    names = tuple(names)
    values = tuple(values)
    if len(set(names)) != len(names):
        raise ValueError(f"{label} names contain duplicates")
    if len(values) != len(names):
        raise ValueError(f"{label} position length does not match names")
    if len(names) != len(expected) or set(names) != set(expected):
        raise ValueError(f"{label} names must be exactly {expected}")
    by_name = dict(zip(names, values))
    result = tuple(float(by_name[name]) for name in expected)
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} position contains non-finite values")
    return result


def master_values(names, values):
    """Map a strict official 6D or 9D master JointState by name."""
    names = tuple(names)
    if len(names) == len(MASTER_ARM_ORDER):
        return _named_values(names, values, MASTER_ARM_ORDER, "master"), None
    mapped = _named_values(names, values, MASTER_GRIPPER_ORDER, "master")
    return mapped[:6], mapped[7] - mapped[8]


def follower_values(names, values):
    """Map the official 7D follower feedback by name."""
    mapped = _named_values(names, values, JOINT_ORDER, "follower")
    return mapped[:6], mapped[6]


@dataclass(frozen=True)
class TeleopLimits:
    publish_hz: float = 30.0
    stale_timeout_sec: float = 0.2
    max_joint_abs_rad: float = 3.0
    max_gripper_abs_m: float = 0.07
    max_alignment_joint_error_rad: float = 1.0
    max_alignment_gripper_error_m: float = 0.05
    alignment_joint_step_rad: float = 0.01
    alignment_gripper_step_m: float = 0.001
    max_joint_step_rad: float = 0.05
    max_gripper_step_m: float = 0.005
    alignment_speed_percent: float = 10.0
    speed_percent: float = 30.0
    gripper_effort: float = 0.5

    def __post_init__(self):
        positive = (
            self.publish_hz,
            self.stale_timeout_sec,
            self.max_joint_abs_rad,
            self.max_gripper_abs_m,
            self.max_alignment_joint_error_rad,
            self.max_alignment_gripper_error_m,
            self.alignment_joint_step_rad,
            self.alignment_gripper_step_m,
            self.max_joint_step_rad,
            self.max_gripper_step_m,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("teleop limits must be finite and positive")
        for name in ("alignment_speed_percent", "speed_percent"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 1.0 <= value <= 100.0:
                raise ValueError(f"{name} must be in [1, 100]")
        if not math.isfinite(self.gripper_effort) or not 0.5 <= self.gripper_effort <= 3.0:
            raise ValueError("gripper_effort must be in [0.5, 3.0]")


@dataclass(frozen=True)
class _Sample:
    joints: tuple
    gripper: object
    received_at: float


def command_payload(position, limits, speed_percent=None):
    """Build the explicit 7D fields consumed by the official follower."""
    position = tuple(float(value) for value in position)
    if len(position) != 7 or not all(math.isfinite(value) for value in position):
        raise ValueError("command position must contain seven finite values")
    speed = limits.speed_percent if speed_percent is None else float(speed_percent)
    if not math.isfinite(speed) or not 1.0 <= speed <= 100.0:
        raise ValueError("command speed_percent must be in [1, 100]")
    return {
        "name": JOINT_ORDER,
        "position": position,
        "velocity": (0.0,) * 6 + (speed,),
        "effort": (0.0,) * 6 + (float(limits.gripper_effort),),
    }


def _step_toward(current, target, maximum):
    return current + max(-maximum, min(maximum, target - current))


class TeleopSafety:
    """Atomic two-side arming, freshness checks, and latched faults."""

    def __init__(self, limits=None):
        self.limits = limits or TeleopLimits()
        self.armed = False
        self.fault = None
        self._samples = {}
        self._aligning = False
        self._alignment_first = False
        self._command_speeds = {side: self.limits.speed_percent for side in SIDES}

    def _latch(self, reason):
        if self.fault is None:
            self.fault = reason
        self.armed = False
        self._aligning = False
        self._alignment_first = False
        self._command_speeds = {side: self.limits.speed_percent for side in SIDES}
        return False

    def _check_side(self, side):
        if side not in SIDES:
            raise ValueError(f"invalid side {side}")

    def _store(self, source, side, joints, gripper, now):
        self._check_side(side)
        if self.fault is not None:
            return False
        if not math.isfinite(now):
            return self._latch(f"{source}_{side}: non-finite receive time")
        if any(abs(value) > self.limits.max_joint_abs_rad for value in joints):
            return self._latch(f"{source}_{side}: joint absolute safety limit exceeded")
        if gripper is not None and abs(gripper) > self.limits.max_gripper_abs_m:
            return self._latch(f"{source}_{side}: gripper absolute safety limit exceeded")

        key = (source, side)
        previous = self._samples.get(key)
        if previous is not None:
            if (previous.gripper is None) != (gripper is None):
                return self._latch(f"{source}_{side}: input schema changed")
            if any(
                abs(current - old) > self.limits.max_joint_step_rad
                for current, old in zip(joints, previous.joints)
            ):
                return self._latch(f"{source}_{side}: joint step safety limit exceeded")
            if gripper is not None and abs(gripper - previous.gripper) > self.limits.max_gripper_step_m:
                return self._latch(f"{source}_{side}: gripper step safety limit exceeded")
        self._samples[key] = _Sample(tuple(joints), gripper, float(now))
        return True

    def update_master(self, side, names, position, now):
        try:
            joints, gripper = master_values(names, position)
        except (TypeError, ValueError) as error:
            self._check_side(side)
            return self._latch(f"master_{side}: {error}")
        return self._store("master", side, joints, gripper, now)

    def update_follower(self, side, names, position, now):
        try:
            joints, gripper = follower_values(names, position)
        except (TypeError, ValueError) as error:
            self._check_side(side)
            return self._latch(f"follower_{side}: {error}")
        return self._store("follower", side, joints, gripper, now)

    def disarm(self):
        self.armed = False
        self.fault = None
        self._samples.clear()
        self._aligning = False
        self._alignment_first = False
        self._command_speeds = {side: self.limits.speed_percent for side in SIDES}

    @property
    def aligning(self):
        return self._aligning

    def command_speed_percent(self, side):
        self._check_side(side)
        return self._command_speeds[side]

    def _fresh(self, now):
        required = [(source, side) for source in ("master", "follower") for side in SIDES]
        missing = [f"{source}_{side}" for source, side in required if (source, side) not in self._samples]
        if missing:
            return False, "missing fresh input: " + ", ".join(missing)
        for key in required:
            age = now - self._samples[key].received_at
            if age < 0.0 or age > self.limits.stale_timeout_sec:
                self._latch(f"{key[0]}_{key[1]}: stale input")
                return False, self.fault
        return True, "inputs fresh"

    def arm(self, now):
        if self.fault is not None:
            return False, f"fault latched; disarm first: {self.fault}"
        if self.armed:
            return True, "already armed"
        fresh, reason = self._fresh(now)
        if not fresh:
            return False, reason

        for side in SIDES:
            master = self._samples[("master", side)]
            follower = self._samples[("follower", side)]
            if master.gripper is None:
                return False, f"{side}: teleop requires a 9D master input with gripper"
            joint_error = max(abs(a - b) for a, b in zip(master.joints, follower.joints))
            if joint_error > self.limits.max_alignment_joint_error_rad:
                return False, f"{side}: automatic joint alignment distance exceeds threshold"
            if abs(master.gripper - follower.gripper) > self.limits.max_alignment_gripper_error_m:
                return False, f"{side}: automatic gripper alignment distance exceeds threshold"
        self._aligning = True
        self._alignment_first = True
        self.armed = True
        return True, "armed; gradual absolute alignment active"

    def commands(self, now):
        if not self.armed or self.fault is not None:
            return None
        fresh, _ = self._fresh(now)
        if not fresh:
            return None
        commands = {}
        speeds = {}
        samples = {
            side: (
                self._samples[("master", side)].joints
                + (self._samples[("master", side)].gripper,),
                self._samples[("follower", side)].joints
                + (self._samples[("follower", side)].gripper,),
            )
            for side in SIDES
        }
        if self._aligning:
            for side, (master, follower) in samples.items():
                if any(
                    abs(target - current) > self.limits.max_alignment_joint_error_rad
                    for current, target in zip(follower[:6], master[:6])
                ):
                    self._latch(f"{side}: automatic joint alignment distance exceeded threshold")
                    return None
                if (
                    abs(master[6] - follower[6])
                    > self.limits.max_alignment_gripper_error_m
                ):
                    self._latch(f"{side}: automatic gripper alignment distance exceeded threshold")
                    return None
        alignment_complete = self._aligning and not self._alignment_first and all(
            all(
                abs(target - current) <= self.limits.alignment_joint_step_rad
                for current, target in zip(follower[:6], master[:6])
            )
            and abs(master[6] - follower[6]) <= self.limits.alignment_gripper_step_m
            for master, follower in samples.values()
        )
        for side in SIDES:
            master_position, follower_position = samples[side]
            if self._aligning:
                speeds[side] = self.limits.alignment_speed_percent
                if self._alignment_first:
                    position = follower_position
                elif alignment_complete:
                    position = master_position
                else:
                    position = tuple(
                        _step_toward(current, target, self.limits.alignment_joint_step_rad)
                        for current, target in zip(follower_position[:6], master_position[:6])
                    ) + (
                        _step_toward(
                            follower_position[6],
                            master_position[6],
                            self.limits.alignment_gripper_step_m,
                        ),
                    )
            else:
                speeds[side] = self.limits.speed_percent
                position = master_position
            if any(abs(value) > self.limits.max_joint_abs_rad for value in position[:6]):
                self._latch(f"command_{side}: joint absolute safety limit exceeded")
                return None
            if abs(position[6]) > self.limits.max_gripper_abs_m:
                self._latch(f"command_{side}: gripper absolute safety limit exceeded")
                return None
            commands[side] = position
        self._alignment_first = False
        if alignment_complete:
            self._aligning = False
        self._command_speeds = speeds
        return commands
