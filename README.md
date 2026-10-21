# NitroSense for Linux

A NitroSense-style app for Acer Nitro laptops (tested on a Nitro AN517-55, Fedora/CachyOS, KDE).

- **Fan control:** Eco / Quiet / Balanced / Performance / Turbo, using the kernel's `acer_wmi` platform profile. It also shows live CPU and GPU fan RPM and temperatures.
- **Manual fans:** separate CPU and GPU speed sliders (0–100%) and a Max button. A temperature failsafe hands the fans back to automatic control if the CPU or GPU gets too hot.
- **Sound modes:** Auto, Off, Shooter, RPG, Racing, Strategy, Music, Movie and Voice. They come from a 10-band PipeWire EQ that sits in front of whatever output you use.
- **Auto sound:** picks a mode from what is playing. Steam/Proton games use `game_default`, unless the game has a per-game override. Music players get Music, video players and browsers get Movie, and Discord/Zoom get Voice.
- A system tray icon and autostart, so it runs in the background.

## Install
```sh
./install.sh        # needs sudo once, for the udev rule that allows fan mode changes
```
Remove with `./uninstall.sh`.

### Manual fan control (optional)
```sh
./enable-manual-fan.sh --dry-run   # show the value it will use
./enable-manual-fan.sh             # write it and reload acer_wmi (needs sudo)
```
The kernel's `acer_wmi` driver already supports manual fan speed (`pwm1` = CPU, `pwm2` = GPU), but it only turns this on for a few models, such as the Nitro AN515-58. The script keeps every capability the driver currently detects on your laptop and adds the PWM bit, using the `force_caps` option in `/etc/modprobe.d/nitrosense-fan.conf`. On an AN517-55 the value is `0x1C26`.

Undo: `sudo rm /etc/modprobe.d/nitrosense-fan.conf`, then reboot.

## CLI
```sh
nitrosense status
nitrosense fan turbo         # eco | quiet | balanced | performance | turbo
nitrosense fan manual 40 70  # CPU 40%, GPU 70% (one value = both fans)
nitrosense fan max           # both fans at 100%
nitrosense fan auto          # back to firmware control
nitrosense sound shooter     # auto | flat | shooter | rpg | racing | strategy | music | movie | voice
```
Bind these to keyboard shortcuts in KDE (System Settings → Shortcuts) if you want hotkeys.

## Customise
Edit `~/.config/nitrosense/config.json`:
- `game_default`: the preset Auto uses for unknown games.
- `game_overrides`: e.g. `"steam:1245620": "rpg"` or `"mygame.exe": "racing"`.
- `apps`: maps an app or binary name (substring) to a preset.
- `fan_manual`: the saved slider values. `failsafe`: the CPU/GPU temperatures (°C, default 95/87) at which manual mode turns itself off.
- `custom_presets`: 10 gains in dB (31 Hz to 16 kHz), e.g. `"shooter": [-6,-4,-2,0,0,1,5,6,3,0]`.

## Notes
- Choosing a fan profile (Eco to Turbo) always returns the fans to automatic control.
- The failsafe only runs while the app or tray icon is running. A speed set from the CLI with the app closed has no failsafe; the firmware's own thermal protection still applies.
- The KDE power-profile slider (tuned-ppd) changes the same setting. The app follows whatever is set.
- GPU temperature reads "sleep" while the NVIDIA GPU is powered down. The app doesn't wake it just to read the temperature.

## License
MIT - see [LICENSE](LICENSE). Use at your own risk: manual fan control writes to the laptop firmware through `acer_wmi`.
