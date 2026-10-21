"""Entry point.

  nitrosense                  open the window (or show the running one)
  nitrosense --tray           start minimized to the tray (used by autostart)
  nitrosense status           print fans, temps, modes
  nitrosense fan <mode>       eco | quiet | balanced | performance | turbo
  nitrosense fan manual C [G] fixed fan speed in % (CPU, GPU; one value = both)
  nitrosense fan max          both fans at 100%
  nitrosense fan auto         hand the fans back to the firmware
  nitrosense sound <mode>     auto | flat | shooter | rpg | racing | strategy | music | movie | voice
"""

import os
import socket
import sys

from . import audio, config, hw

SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "nitrosense.sock")


def send_to_running(line):
    """Hand a command to the running GUI instance. Returns True if one answered."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(SOCKET_PATH)
            s.sendall((line + "\n").encode())
        return True
    except OSError:
        return False


def fmt(v, unit):
    return "--" if v is None else f"{v}{unit}"


def cli(args):
    cmd = args[0]
    if cmd == "status":
        d = hw.read_sensors()
        cfg = config.load()
        print(f"Fan mode : {hw.MODE_LABELS.get(hw.current_mode(), '?')} ({hw.current_profile()})")
        state = hw.fan_control_state()
        if state is None:
            print("Fan ctrl : profiles only (run enable-manual-fan.sh for manual control)")
        elif state == "manual":
            sp = hw.manual_speeds()
            print(f"Fan ctrl : manual - CPU {sp['cpu']}% / GPU {sp['gpu']}%")
        else:
            print(f"Fan ctrl : {state}")
        print(f"CPU fan  : {fmt(d['cpu_fan'], ' RPM')}")
        print(f"GPU fan  : {fmt(d['gpu_fan'], ' RPM')}")
        print(f"CPU temp : {fmt(d['cpu_temp'], '°C')}")
        print(f"GPU temp : {fmt(d['gpu_temp'], '°C') if d['gpu_awake'] else 'sleeping'}")
        print(f"Sys temp : {fmt(d['sys_temp'], '°C')}")
        print(f"Sound    : {audio.SOUND_LABELS.get(cfg['sound_mode'], cfg['sound_mode'])}")
        dump = audio.pw_dump()
        print(f"EQ       : {'loaded' if audio.find_eq_node(dump) is not None else 'NOT loaded'}")
        print(f"Output   : {audio.default_output(dump)}")
        print(f"Modes    : {', '.join(hw.available_modes())}")
        return 0

    if cmd == "fan" and len(args) == 2 and args[1] in hw.MODE_TO_PROFILE:
        if send_to_running(f"fan {args[1]}"):
            return 0
        err = hw.set_mode(args[1])
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        cfg = config.load()
        cfg["fan_mode"] = args[1]
        config.save(cfg)
        return 0

    if cmd == "fan" and len(args) >= 2 and args[1] in ("manual", "max", "auto"):
        if not hw.manual_fan_supported():
            print("error: manual fan control is not enabled (run enable-manual-fan.sh)", file=sys.stderr)
            return 1
        nums = args[2:4]
        if not all(n.isdigit() and 0 <= int(n) <= 100 for n in nums) or (args[1] == "manual" and not nums):
            print("usage: nitrosense fan manual <cpu%> [gpu%]", file=sys.stderr)
            return 2
        if args[1] == "auto":
            if send_to_running("fan auto"):
                return 0
            err = hw.set_fans_auto()
            if not err:
                cfg = config.load()
                cfg["fan_mode"] = hw.current_mode()
                config.save(cfg)
        else:
            if args[1] == "max":
                nums = ["100", "100"]
            elif len(nums) == 1:
                nums *= 2
            if send_to_running(f"fan manual {nums[0]} {nums[1]}"):
                return 0
            err = hw.set_fans_manual(int(nums[0]), int(nums[1]))
            if not err:
                cfg = config.load()
                cfg["fan_mode"] = "manual"
                cfg["fan_manual"] = {"cpu": int(nums[0]), "gpu": int(nums[1])}
                config.save(cfg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        if args[1] != "auto":
            print("Note: the temperature failsafe only runs while the NitroSense app/tray is open.")
        return 0

    if cmd == "sound" and len(args) == 2 and args[1] in audio.SOUND_LABELS:
        if send_to_running(f"sound {args[1]}"):
            return 0
        cfg = config.load()
        cfg["sound_mode"] = args[1]
        config.save(cfg)
        if args[1] == "auto":
            print("Auto mode is saved; it runs while the NitroSense app/tray is open.")
            return 0
        err = audio.apply_preset(args[1], cfg)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        return 0

    print(__doc__, file=sys.stderr)
    return 2


def main():
    args = [a for a in sys.argv[1:] if a != "--cli"]
    if args and args[0] in ("status", "fan", "sound", "-h", "--help", "help"):
        return cli(args)
    tray = "--tray" in args
    if send_to_running("noop" if tray else "show"):
        return 0
    from .gui import run
    return run(start_hidden=tray)


if __name__ == "__main__":
    sys.exit(main())
