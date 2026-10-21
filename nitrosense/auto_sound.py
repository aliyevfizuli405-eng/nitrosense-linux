"""Auto sound mode: choose a preset from whatever is currently playing."""

import os

# When several things play at once, the highest-priority category wins.
PRIORITY = ["game", "movie", "music", "voice"]
WINE_HINTS = ("wine", "proton", "preloader")


def _steam_app_id(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = dict(item.split(b"=", 1) for item in f.read().split(b"\0") if b"=" in item)
    except OSError:
        return None, False
    app_id = env.get(b"SteamGameId") or env.get(b"SteamAppId")
    app_id = app_id.decode() if app_id and app_id != b"0" else None
    is_game = app_id is not None or b"STEAM_COMPAT_DATA_PATH" in env
    return app_id, is_game


def _exe_name(pid):
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe")).lower()
    except OSError:
        return ""


def classify_stream(stream, cfg):
    """Return (category, preset, label) for one stream, or None if unknown."""
    app = stream["app"].lower()
    binary = stream["binary"].lower()
    label = stream["app"] or stream["binary"] or "?"
    pid = stream["pid"]

    app_id, is_game = _steam_app_id(pid) if pid else (None, False)
    overrides = cfg.get("game_overrides", {})
    for key in (f"steam:{app_id}" if app_id else None, binary, app, _exe_name(pid) if pid else None):
        if key and key in overrides:
            return "game", overrides[key], label
    if is_game or app.endswith(".exe") or binary.endswith(".exe") or any(h in binary for h in WINE_HINTS):
        return "game", cfg.get("game_default", "shooter"), label

    for key, preset in cfg.get("apps", {}).items():
        if key in app or key in binary:
            category = {"music": "music", "movie": "movie", "voice": "voice"}.get(preset, "game")
            return category, preset, label
    return None


def pick_preset(streams, cfg):
    """Return (preset, reason) for the current set of playing streams."""
    best = None
    for stream in streams:
        result = classify_stream(stream, cfg)
        if result and (best is None or PRIORITY.index(result[0]) < PRIORITY.index(best[0])):
            best = result
    if best is None:
        return "flat", "nothing recognised playing"
    return best[1], best[2]
