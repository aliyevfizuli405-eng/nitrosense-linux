"""Persistent settings in ~/.config/nitrosense/config.json."""

import copy
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nitrosense"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    # Fan mode re-applied at login: a profile key, "manual", or null = leave the system's choice.
    "fan_mode": None,
    # Manual fan speeds in percent (needs enable-manual-fan.sh).
    "fan_manual": {"cpu": 60, "gpu": 60},
    # Manual mode falls back to automatic fans at these temperatures (°C).
    "failsafe": {"cpu": 95, "gpu": 87},
    "sound_mode": "flat",
    # Preset used in Auto mode for any game without an override below.
    "game_default": "shooter",
    # Auto mode: substring of app name / binary (lowercase) -> preset.
    "apps": {
        "spotify": "music",
        "rhythmbox": "music",
        "elisa": "music",
        "strawberry": "music",
        "lollypop": "music",
        "amarok": "music",
        "clementine": "music",
        "audacious": "music",
        "deadbeef": "music",
        "tidal": "music",
        "vlc": "movie",
        "mpv": "movie",
        "haruna": "movie",
        "totem": "movie",
        "celluloid": "movie",
        "smplayer": "movie",
        "kodi": "movie",
        "stremio": "movie",
        "firefox": "movie",
        "chrome": "movie",
        "chromium": "movie",
        "brave": "movie",
        "vivaldi": "movie",
        "discord": "voice",
        "vesktop": "voice",
        "webcord": "voice",
        "zoom": "voice",
        "teams": "voice",
        "skype": "voice",
        "telegram": "voice",
        "mumble": "voice",
        "teamspeak": "voice",
    },
    # Auto mode: per-game overrides, keyed by lowercase binary name or "steam:<appid>".
    "game_overrides": {
        "cs2": "shooter",
        "eldenring.exe": "rpg",
        "witcher3.exe": "rpg",
        "cyberpunk2077.exe": "rpg",
        "bg3.exe": "rpg",
        "forzahorizon5.exe": "racing",
        "steam:730": "shooter",
        "steam:1172470": "shooter",   # Apex Legends
        "steam:578080": "shooter",    # PUBG
        "steam:1245620": "rpg",       # Elden Ring
        "steam:292030": "rpg",        # The Witcher 3
        "steam:1091500": "rpg",       # Cyberpunk 2077
        "steam:1086940": "rpg",       # Baldur's Gate 3
        "steam:1551360": "racing",    # Forza Horizon 5
        "steam:2440510": "racing",    # Forza Motorsport
        "steam:289070": "strategy",   # Civilization VI
        "steam:394360": "strategy",   # Hearts of Iron IV
        "steam:570": "strategy",      # Dota 2
    },
    # Optional custom presets / overrides of built-in ones: name -> 10 gains (dB).
    "custom_presets": {},
}


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            user = json.load(f)
    except (OSError, ValueError):
        return cfg
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    tmp.replace(CONFIG_FILE)
