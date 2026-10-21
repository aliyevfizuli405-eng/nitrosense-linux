"""Sound modes via a PipeWire filter-chain EQ ("Nitro Sense Audio", data/nitrosense-eq.conf)."""

import json
import subprocess

EQ_NODE_NAME = "nitrosense_eq"
BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
BAND_NODES = ["eq_31", "eq_62", "eq_125", "eq_250", "eq_500",
              "eq_1k", "eq_2k", "eq_4k", "eq_8k", "eq_16k"]
BAND_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]

# Gains in dB per band (31 Hz ... 16 kHz).
PRESETS = {
    "flat":     [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "shooter":  [-4, -3, -1, 0, 0, 1, 4, 5, 3, 1],
    "rpg":      [3, 3, 2, 1, 0, 0, 1, 2, 3, 3],
    "racing":   [3, 4, 4, 2, 0, 0, 1, 2, 2, 1],
    "strategy": [0, 0, 0, 1, 2, 2, 2, 1, 0, 0],
    "music":    [4, 4, 3, 1, -1, -1, 0, 2, 4, 4],
    "movie":    [4, 4, 3, 1, 0, 1, 3, 2, 1, 1],
    "voice":    [-6, -5, -3, -1, 1, 3, 4, 3, 1, -1],
}

# (key, label) in display order; "auto" picks one of the presets at runtime.
SOUND_MODES = [
    ("auto", "Auto"),
    ("flat", "Off"),
    ("shooter", "Shooter"),
    ("rpg", "RPG"),
    ("racing", "Racing"),
    ("strategy", "Strategy"),
    ("music", "Music"),
    ("movie", "Movie"),
    ("voice", "Voice"),
]
SOUND_LABELS = dict(SOUND_MODES)


def preset_gains(name, cfg=None):
    custom = (cfg or {}).get("custom_presets", {})
    gains = custom.get(name) or PRESETS.get(name) or PRESETS["flat"]
    return [float(g) for g in gains][:len(BANDS)]


def pw_dump():
    try:
        r = subprocess.run(["pw-dump", "--no-colors"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout or "[]")
    except (subprocess.SubprocessError, OSError, ValueError):
        return []


def _nodes(dump):
    for obj in dump:
        if obj.get("type") == "PipeWire:Interface:Node":
            yield obj["id"], (obj.get("info") or {}).get("props", {}), obj.get("info") or {}


def find_eq_node(dump=None):
    for node_id, props, _ in _nodes(dump if dump is not None else pw_dump()):
        if props.get("node.name") == EQ_NODE_NAME:
            return node_id
    return None


def apply_gains(gains, dump=None):
    """Push gains to the live EQ. Returns None on success or an error string."""
    node_id = find_eq_node(dump)
    if node_id is None:
        return "EQ not loaded (run install.sh, then restart PipeWire)"
    # Pre-attenuate by the largest boost so loud presets don't clip.
    preamp = -max(0.0, max(gains))
    params = [f'"preamp:Gain" {preamp:.1f}']
    params += [f'"{band}:Gain" {g:.1f}' for band, g in zip(BAND_NODES, gains)]
    props = "{ params = [ " + " ".join(params) + " ] }"
    r = subprocess.run(["pw-cli", "set-param", str(node_id), "Props", props],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0 or "error" in r.stderr.lower():
        return r.stderr.strip() or "pw-cli set-param failed"
    return None


def apply_preset(name, cfg=None, dump=None):
    return apply_gains(preset_gains(name, cfg), dump)


def default_output(dump=None):
    """Description of the current default sink (the real device behind the EQ)."""
    dump = dump if dump is not None else pw_dump()
    default_name = None
    for obj in dump:
        if obj.get("type") == "PipeWire:Interface:Metadata" and \
                (obj.get("props") or {}).get("metadata.name") == "default":
            for entry in obj.get("metadata") or []:
                if entry.get("key") == "default.audio.sink":
                    value = entry.get("value")
                    default_name = value.get("name") if isinstance(value, dict) else None
    for _, props, _ in _nodes(dump):
        if props.get("node.name") == default_name:
            return props.get("node.description") or default_name
    return default_name


def active_streams(dump=None):
    """Playback streams currently running: list of dicts (app, binary, pid)."""
    streams = []
    for _, props, info in _nodes(dump if dump is not None else pw_dump()):
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        if info.get("state") != "running":
            continue
        # Skip filter-chain / loopback outputs (including our own EQ).
        if props.get("node.passive") or "filter.smart" in props or props.get("node.link-group"):
            continue
        pid = props.get("application.process.id")
        streams.append({
            "app": (props.get("application.name") or "").strip(),
            "binary": (props.get("application.process.binary") or "").strip(),
            "pid": int(pid) if str(pid).isdigit() else None,
        })
    return streams
