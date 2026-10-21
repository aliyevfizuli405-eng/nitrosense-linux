"""Fan / thermal hardware access via the stock acer_wmi driver."""

import glob
import shutil
import subprocess
from pathlib import Path

LEGACY_PROFILE = Path("/sys/firmware/acpi/platform_profile")
DGPU_PCI = "0000:01:00.0"

# (key, label, platform_profile value)
FAN_MODES = [
    ("eco", "Eco", "low-power"),
    ("quiet", "Quiet", "quiet"),
    ("balanced", "Balanced", "balanced"),
    ("performance", "Performance", "balanced-performance"),
    ("turbo", "Turbo", "performance"),
]
MODE_TO_PROFILE = {key: profile for key, _, profile in FAN_MODES}
PROFILE_TO_MODE = {profile: key for key, _, profile in FAN_MODES}
MODE_LABELS = {key: label for key, label, _ in FAN_MODES}


def _read(path, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def _read_int(path):
    value = _read(path)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hwmon(name):
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if _read(f"{h}/name") == name:
            return Path(h)
    return None


def _profile_dir():
    """The acer-wmi platform-profile class device (writable after the udev rule)."""
    for d in sorted(glob.glob("/sys/class/platform-profile/platform-profile-*")):
        if _read(f"{d}/name") == "acer-wmi":
            return Path(d)
    dirs = sorted(glob.glob("/sys/class/platform-profile/platform-profile-*"))
    return Path(dirs[0]) if dirs else None


def profile_choices():
    d = _profile_dir()
    raw = _read(d / "choices") if d else _read(LEGACY_PROFILE.with_name("platform_profile_choices"))
    return raw.split() if raw else []


def available_modes():
    choices = set(profile_choices())
    return [key for key, _, profile in FAN_MODES if profile in choices]


def current_profile():
    d = _profile_dir()
    return (_read(d / "profile") if d else None) or _read(LEGACY_PROFILE)


def current_mode():
    return PROFILE_TO_MODE.get(current_profile())


def set_mode(mode):
    """Set fan mode; returns None on success or an error string."""
    profile = MODE_TO_PROFILE[mode]
    if profile not in profile_choices():
        return f"'{profile}' is not supported by this laptop"
    d = _profile_dir()
    target = d / "profile" if d else LEGACY_PROFILE
    err = _write_sysfs(target, profile)
    # A profile means "let the firmware drive the fans" - leave manual mode.
    if not err and fan_control_state() not in (None, "auto"):
        err = set_fans_auto()
    return err


def _write_sysfs(path, value):
    try:
        Path(path).write_text(str(value))
        return None
    except PermissionError:
        pass
    except OSError as e:
        return f"Failed to write {path}: {e}"
    # Fallback when the udev rule is not installed.
    if not shutil.which("pkexec"):
        return "No write permission (run install.sh to add the udev rule)"
    r = subprocess.run(["pkexec", "tee", str(path)], input=str(value), text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return None if r.returncode == 0 else (r.stderr.strip() or "pkexec failed")


# ---- manual fan control (acer_wmi hwmon pwm1 = CPU, pwm2 = GPU) ----
# pwmN_enable: 0 = max (turbo), 1 = manual, 2 = auto (firmware). pwmN: 0-255.
PWM_MAX, PWM_MANUAL, PWM_AUTO = 0, 1, 2
FANS = (("cpu", 1), ("gpu", 2))


def manual_fan_supported():
    acer = _hwmon("acer")
    return bool(acer and (acer / "pwm1").exists() and (acer / "pwm1_enable").exists())


def _write_hwmon(attr, value):
    return _write_sysfs(_hwmon("acer") / attr, value)


def fan_control_state():
    """Return 'auto', 'manual', 'max' (as reported by the CPU fan) or None if unsupported."""
    if not manual_fan_supported():
        return None
    value = _read_int(_hwmon("acer") / "pwm1_enable")
    return {PWM_MAX: "max", PWM_MANUAL: "manual", PWM_AUTO: "auto"}.get(value)


def manual_speeds():
    """Current manual targets in percent: {'cpu': int, 'gpu': int}."""
    acer = _hwmon("acer")
    out = {}
    for name, n in FANS:
        raw = _read_int(acer / f"pwm{n}") if acer else None
        out[name] = None if raw is None else round(raw * 100 / 255)
    return out


def set_fans_manual(cpu_pct, gpu_pct):
    """Fixed fan speeds in percent. Returns None or an error string."""
    for (_, n), pct in zip(FANS, (cpu_pct, gpu_pct)):
        pct = max(0, min(100, int(pct)))
        err = _write_hwmon(f"pwm{n}_enable", PWM_MANUAL) or \
            _write_hwmon(f"pwm{n}", round(pct * 255 / 100))
        if err:
            return err
    return None


def set_fans_auto():
    for _, n in FANS:
        err = _write_hwmon(f"pwm{n}_enable", PWM_AUTO)
        if err:
            return err
    return None


def set_fans_max():
    for _, n in FANS:
        err = _write_hwmon(f"pwm{n}_enable", PWM_MAX)
        if err:
            return err
    return None


def _gpu_temp():
    # Only ask nvidia-smi when the dGPU is already awake; querying it would wake it
    # up and stop runtime power management (battery drain).
    if _read(f"/sys/bus/pci/devices/{DGPU_PCI}/power/runtime_status") != "active":
        return None
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=2)
        return int(r.stdout.split()[0])
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


def read_sensors():
    """Return dict: cpu_fan, gpu_fan (RPM), cpu_temp, gpu_temp, sys_temp (°C), gpu_awake."""
    acer = _hwmon("acer")
    data = {"cpu_fan": None, "gpu_fan": None, "cpu_temp": None, "gpu_temp": None,
            "sys_temp": None, "gpu_awake": False}
    if acer:
        data["cpu_fan"] = _read_int(acer / "fan1_input")
        data["gpu_fan"] = _read_int(acer / "fan2_input")
        t = _read_int(acer / "temp3_input")
        data["sys_temp"] = t // 1000 if t else None

    core = _hwmon("coretemp") or _hwmon("k10temp")
    if core:
        for label in sorted(core.glob("temp*_label")):
            if _read(label) in ("Package id 0", "Tctl"):
                t = _read_int(str(label).replace("_label", "_input"))
                data["cpu_temp"] = t // 1000 if t else None
                break
    if data["cpu_temp"] is None and acer:
        t = _read_int(acer / "temp1_input")
        data["cpu_temp"] = t // 1000 if t else None

    data["gpu_awake"] = _read(f"/sys/bus/pci/devices/{DGPU_PCI}/power/runtime_status") == "active"
    data["gpu_temp"] = _gpu_temp()
    return data
