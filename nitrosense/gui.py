"""NitroSense-style Qt window + system tray."""

import os
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QSlider, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

from . import audio, auto_sound, config, hw

HERE = Path(__file__).resolve().parent
RED = QColor("#e8112d")
TRACK = QColor("#2a2a33")
MAX_RPM = 6000
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "nitrosense.sock")


def app_icon():
    for path in (HERE.parent / "data" / "nitrosense.svg",
                 Path.home() / ".local/share/icons/hicolor/scalable/apps/nitrosense.svg"):
        if path.exists():
            return QIcon(str(path))
    return QIcon.fromTheme("preferences-system-power")


class Gauge(QWidget):
    """Arc gauge showing fan RPM."""

    def __init__(self, title):
        super().__init__()
        self.title = title
        self.value = None
        self.setMinimumSize(170, 170)

    def set_value(self, value):
        self.value = value
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        start, span = 225 * 16, -270 * 16

        p.setPen(QPen(TRACK, 12, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, start, span)
        if self.value:
            frac = min(self.value / MAX_RPM, 1.0)
            p.setPen(QPen(RED, 12, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, start, int(span * frac))

        p.setPen(QColor("#ffffff"))
        f = QFont(self.font())
        f.setPointSize(18)
        f.setBold(True)
        p.setFont(f)
        cx, cy = rect.center().x(), rect.center().y()
        p.drawText(QRectF(rect.left(), cy - 24, side, 32), Qt.AlignCenter,
                   "--" if self.value is None else str(self.value))
        f.setPointSize(8)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor("#8a8a96"))
        p.drawText(QRectF(rect.left(), cy + 8, side, 16), Qt.AlignCenter, "RPM")
        # Title sits in the open gap at the bottom of the arc.
        p.setPen(QColor("#e8e8ec"))
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - side / 2, rect.bottom() - 22, side, 18), Qt.AlignCenter, self.title)


class EqPreview(QWidget):
    """Read-only bar view of the active preset's gains."""

    def __init__(self):
        super().__init__()
        self.gains = [0.0] * len(audio.BANDS)
        self.setMinimumHeight(120)

    def set_gains(self, gains):
        self.gains = gains
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.gains)
        label_h = 16
        h = self.height() - label_h
        mid = h / 2
        slot = self.width() / n
        p.setPen(QPen(TRACK, 1))
        p.drawLine(0, int(mid), self.width(), int(mid))
        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        for i, (g, label) in enumerate(zip(self.gains, audio.BAND_LABELS)):
            x = i * slot + slot * 0.25
            w = slot * 0.5
            bar = (g / 8.0) * (mid - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(RED if g >= 0 else QColor("#6a6a78"))
            p.drawRoundedRect(QRectF(x, mid - max(bar, 0), w, abs(bar) or 1.5), 2, 2)
            p.setPen(QColor("#8a8a96"))
            p.drawText(QRectF(i * slot, h, slot, label_h), Qt.AlignCenter, label)


def card(title):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("cardTitle")
    layout.addWidget(heading)
    return frame, layout


class Poller(QObject):
    """Background thread: sensors + PipeWire state, so the UI never blocks."""

    sensors = Signal(dict)
    pw_state = Signal(dict)

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        tick = 0
        while not self._stop.is_set():
            data = hw.read_sensors()
            data["mode"] = hw.current_mode()
            data["profile"] = hw.current_profile()
            data["fan_state"] = hw.fan_control_state()
            self.sensors.emit(data)
            if tick % 2 == 0:
                dump = audio.pw_dump()
                self.pw_state.emit({
                    "dump": dump,
                    "eq_node": audio.find_eq_node(dump),
                    "output": audio.default_output(dump),
                    "streams": audio.active_streams(dump),
                })
            tick += 1
            self._stop.wait(1.0)


class MainWindow(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.quitting = False
        self.applied_preset = None   # preset currently pushed to the EQ
        self.eq_node = None
        self.auto_reason = ""
        self.message = ""
        self.fan_state = None        # 'auto' / 'manual' / 'max' from pwm*_enable, None if unsupported
        self.manual_ok = hw.manual_fan_supported()

        self.setWindowTitle("NitroSense")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(720)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(16)

        header = QHBoxLayout()
        t1 = QLabel("NITRO")
        t1.setObjectName("title")
        t2 = QLabel("SENSE")
        t2.setObjectName("titleAccent")
        header.addWidget(t1)
        header.addWidget(t2)
        header.addStretch()
        sub = QLabel("Acer Nitro · Linux")
        sub.setObjectName("muted")
        header.addWidget(sub)
        root.addLayout(header)

        # Fan control
        fan_card, fan_layout = card("FAN CONTROL")
        row = QHBoxLayout()
        self.cpu_gauge = Gauge("CPU FAN")
        self.gpu_gauge = Gauge("GPU FAN")
        row.addWidget(self.cpu_gauge)
        row.addWidget(self.gpu_gauge)
        temps = QVBoxLayout()
        temps.setSpacing(4)
        self.temp_labels = {}
        for key, name in (("cpu_temp", "CPU"), ("gpu_temp", "GPU"), ("sys_temp", "SYSTEM")):
            value = QLabel("--")
            value.setObjectName("tempValue")
            label = QLabel(name)
            label.setObjectName("tempLabel")
            temps.addWidget(value)
            temps.addWidget(label)
            temps.addSpacing(6)
            self.temp_labels[key] = value
        temps.addStretch()
        row.addLayout(temps)
        fan_layout.addLayout(row)

        modes = QHBoxLayout()
        self.fan_group = QButtonGroup(self)
        self.fan_buttons = {}
        available = hw.available_modes()
        for key, label, _ in hw.FAN_MODES:
            if key not in available:
                continue
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.set_fan_mode(k))
            self.fan_group.addButton(btn)
            self.fan_buttons[key] = btn
            modes.addWidget(btn)
        self.manual_btn = QPushButton("Manual")
        self.manual_btn.setCheckable(True)
        self.manual_btn.setEnabled(self.manual_ok)
        if not self.manual_ok:
            self.manual_btn.setToolTip("Run enable-manual-fan.sh to unlock manual fan control")
        self.manual_btn.clicked.connect(lambda: self.set_manual())
        self.fan_group.addButton(self.manual_btn)
        modes.addWidget(self.manual_btn)
        fan_layout.addLayout(modes)

        # Manual fan sliders (shown only in Manual mode)
        self.manual_panel = QWidget()
        self.manual_panel.setObjectName("manualPanel")
        mp = QGridLayout(self.manual_panel)
        mp.setContentsMargins(0, 4, 0, 0)
        self.sliders, self.slider_values = {}, {}
        speeds = self.cfg["fan_manual"]
        for row_i, (key, name) in enumerate((("cpu", "CPU fan"), ("gpu", "GPU fan"))):
            label = QLabel(name)
            label.setObjectName("muted")
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setSingleStep(5)
            slider.setPageStep(10)
            slider.setValue(speeds[key])
            value = QLabel(f"{speeds[key]}%")
            value.setMinimumWidth(44)
            slider.valueChanged.connect(lambda v, l=value: l.setText(f"{v}%"))
            slider.sliderReleased.connect(self.apply_sliders)
            slider.valueChanged.connect(lambda _, sl=slider: sl.isSliderDown() or self.slider_timer.start())
            mp.addWidget(label, row_i, 0)
            mp.addWidget(slider, row_i, 1)
            mp.addWidget(value, row_i, 2)
            self.sliders[key], self.slider_values[key] = slider, value
        max_btn = QPushButton("Max")
        max_btn.clicked.connect(lambda: self.set_manual(100, 100))
        mp.addWidget(max_btn, 0, 3, 2, 1)
        fs = self.cfg["failsafe"]
        note = QLabel(f"Failsafe: returns to automatic fans at CPU {fs['cpu']}°C / GPU {fs['gpu']}°C")
        note.setObjectName("muted")
        mp.addWidget(note, 2, 0, 1, 4)
        fan_layout.addWidget(self.manual_panel)
        # Debounce keyboard / wheel slider changes.
        self.slider_timer = QTimer(self, singleShot=True, interval=400)
        self.slider_timer.timeout.connect(self.apply_sliders)
        root.addWidget(fan_card)

        # Sound
        snd_card, snd_layout = card("SOUND MODE")
        grid = QGridLayout()
        grid.setSpacing(8)
        self.sound_group = QButtonGroup(self)
        self.sound_buttons = {}
        for i, (key, label) in enumerate(audio.SOUND_MODES):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.set_sound_mode(k))
            self.sound_group.addButton(btn)
            self.sound_buttons[key] = btn
            grid.addWidget(btn, i // 5, i % 5)
        snd_layout.addLayout(grid)
        self.eq_preview = EqPreview()
        snd_layout.addWidget(self.eq_preview)
        root.addWidget(snd_card)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.output_name = None
        self.profile = None
        self.refresh_buttons()

    # ---- actions ----
    def set_manual(self, cpu=None, gpu=None):
        """Switch to fixed fan speeds (defaults: the saved slider values)."""
        speeds = self.cfg["fan_manual"]
        cpu = speeds["cpu"] if cpu is None else cpu
        gpu = speeds["gpu"] if gpu is None else gpu
        err = hw.set_fans_manual(cpu, gpu)
        if err:
            self.message = f"Fan: {err}"
        else:
            self.message = ""
            self.cfg["fan_mode"] = "manual"
            self.cfg["fan_manual"] = {"cpu": int(cpu), "gpu": int(gpu)}
            config.save(self.cfg)
            self.fan_state = "manual"
            for key, v in (("cpu", cpu), ("gpu", gpu)):
                self.sliders[key].blockSignals(True)
                self.sliders[key].setValue(int(v))
                self.sliders[key].blockSignals(False)
                self.slider_values[key].setText(f"{int(v)}%")
        self.refresh_buttons()
        self.update_status()
        self.tray_sync()

    def apply_sliders(self):
        self.slider_timer.stop()
        self.set_manual(self.sliders["cpu"].value(), self.sliders["gpu"].value())

    def set_fan_mode(self, mode):
        err = hw.set_mode(mode)
        if err:
            self.message = f"Fan: {err}"
        else:
            self.message = ""
            self.cfg["fan_mode"] = mode
            config.save(self.cfg)
            self.profile = hw.current_profile()
            self.fan_state = hw.fan_control_state()
        self.refresh_buttons()
        self.update_status()

    def set_sound_mode(self, mode):
        self.cfg["sound_mode"] = mode
        config.save(self.cfg)
        if mode == "auto":
            self.applied_preset = None   # force re-evaluation
            self.auto_reason = "waiting for audio..."
            self.eq_preview.set_gains(audio.preset_gains("flat", self.cfg))
        else:
            self.push_preset(mode)
        self.refresh_buttons()
        self.update_status()

    def push_preset(self, preset, dump=None):
        err = audio.apply_preset(preset, self.cfg, dump)
        if err:
            self.message = f"Sound: {err}"
            self.applied_preset = None
        else:
            if self.message.startswith("Sound:"):
                self.message = ""
            self.applied_preset = preset
        self.eq_preview.set_gains(audio.preset_gains(preset, self.cfg))

    def handle_command(self, line):
        parts = line.split()
        if parts[:1] == ["show"]:
            self.show_window()
        elif len(parts) == 2 and parts[0] == "fan" and parts[1] in hw.MODE_TO_PROFILE:
            self.set_fan_mode(parts[1])
        elif parts[:2] == ["fan", "auto"]:
            self.set_fan_mode(hw.current_mode() or "balanced")
        elif parts[:2] == ["fan", "max"]:
            self.set_manual(100, 100)
        elif parts[:2] == ["fan", "manual"] and all(p.isdigit() for p in parts[2:4]):
            nums = [int(p) for p in parts[2:4]]
            if len(nums) == 1:
                nums *= 2   # one value = both fans
            self.set_manual(*nums)
        elif len(parts) == 2 and parts[0] == "sound" and parts[1] in audio.SOUND_LABELS:
            self.set_sound_mode(parts[1])
        self.tray_sync()

    # ---- polling callbacks ----
    def on_sensors(self, d):
        self.cpu_gauge.set_value(d["cpu_fan"])
        self.gpu_gauge.set_value(d["gpu_fan"])
        for key, label in self.temp_labels.items():
            v = d.get(key)
            if v is None and key == "gpu_temp":
                label.setText("sleep" if not d["gpu_awake"] else "--")
            else:
                label.setText("--" if v is None else f"{v}°C")
        profile_changed = d["profile"] != self.profile
        if profile_changed or d["fan_state"] != self.fan_state:
            if (not profile_changed and self.fan_state == "manual" and d["fan_state"] == "auto"
                    and self.cfg.get("fan_mode") == "manual"):
                # Firmware dropped manual mode on its own (e.g. after suspend): restore it.
                self.set_manual()
                d["fan_state"] = self.fan_state
            self.profile = d["profile"]
            self.fan_state = d["fan_state"]
            self.refresh_buttons()
            self.tray_sync()
        self.check_failsafe(d)
        self.update_status()

    def check_failsafe(self, d):
        if self.fan_state != "manual":
            return
        fs = self.cfg["failsafe"]
        hot = [f"{name} {d[key]}°C" for key, name, limit in
               (("cpu_temp", "CPU", fs["cpu"]), ("gpu_temp", "GPU", fs["gpu"]))
               if d.get(key) is not None and d[key] >= limit]
        if hot:
            hw.set_fans_auto()
            self.fan_state = hw.fan_control_state()
            self.cfg["fan_mode"] = hw.current_mode()
            config.save(self.cfg)
            self.message = f"Failsafe: {', '.join(hot)} - switched back to automatic fans"
            self.refresh_buttons()
            self.tray_sync()
            if hasattr(self, "tray"):
                self.tray.showMessage("NitroSense", self.message, QSystemTrayIcon.Warning, 8000)

    def on_pw_state(self, s):
        node = s["eq_node"]
        node_changed = node != self.eq_node
        self.eq_node = node
        self.output_name = s["output"]
        mode = self.cfg["sound_mode"]
        if node is not None:
            if mode == "auto":
                preset, reason = auto_sound.pick_preset(s["streams"], self.cfg)
                self.auto_reason = f"{audio.SOUND_LABELS.get(preset, preset)} ({reason})"
                if preset != self.applied_preset or node_changed:
                    self.push_preset(preset, s["dump"])
            elif node_changed or self.applied_preset != mode:
                # EQ (re)appeared, e.g. after a PipeWire restart: re-apply.
                self.push_preset(mode, s["dump"])
        else:
            self.applied_preset = None
            self.message = "Sound: EQ not loaded (run install.sh, then restart PipeWire)"
        self.update_status()

    # ---- view ----
    def refresh_buttons(self):
        manual = self.fan_state in ("manual", "max")
        mode = None if manual else hw.PROFILE_TO_MODE.get(self.profile or hw.current_profile())
        for key, btn in self.fan_buttons.items():
            btn.setChecked(key == mode)
        self.manual_btn.setChecked(manual)
        self.manual_panel.setVisible(manual)
        for key, btn in self.sound_buttons.items():
            btn.setChecked(key == self.cfg["sound_mode"])

    def update_status(self):
        parts = [f"Profile: {self.profile or '?'}"]
        if self.fan_state in ("manual", "max"):
            sp = self.cfg["fan_manual"]
            parts[0] += f" (fans manual: CPU {sp['cpu']}% / GPU {sp['gpu']}%)" \
                if self.fan_state == "manual" else " (fans: max)"
        if self.output_name:
            parts.append(f"Output: {self.output_name}")
        if self.cfg["sound_mode"] == "auto":
            parts.append(f"Auto → {self.auto_reason}")
        text = "   ·   ".join(parts)
        if self.message:
            text += f"\n⚠ {self.message}"
        self.status.setText(text)

    # ---- tray ----
    def build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("NitroSense")
        menu = QMenu()
        show = menu.addAction("Show NitroSense")
        show.triggered.connect(self.show_window)
        menu.addSeparator()

        fan_menu = menu.addMenu("Fan mode")
        self.fan_actions = {}
        group = QActionGroup(self)
        for key, label, _ in hw.FAN_MODES:
            if key not in self.fan_buttons:
                continue
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _=False, k=key: self.set_fan_mode(k))
            group.addAction(act)
            fan_menu.addAction(act)
            self.fan_actions[key] = act
        if self.manual_ok:
            fan_menu.addSeparator()
            act = QAction("Manual", self, checkable=True)
            act.triggered.connect(lambda: self.set_manual())
            group.addAction(act)
            fan_menu.addAction(act)
            self.fan_actions["manual"] = act
            fan_menu.addAction("Max speed").triggered.connect(lambda: self.set_manual(100, 100))

        snd_menu = menu.addMenu("Sound mode")
        self.sound_actions = {}
        group = QActionGroup(self)
        for key, label in audio.SOUND_MODES:
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda _=False, k=key: (self.set_sound_mode(k), self.tray_sync()))
            group.addAction(act)
            snd_menu.addAction(act)
            self.sound_actions[key] = act

        menu.addSeparator()
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(self.quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()
        self.tray_sync()

    def tray_sync(self):
        if not hasattr(self, "tray"):
            return
        mode = "manual" if self.fan_state in ("manual", "max") else \
            hw.PROFILE_TO_MODE.get(self.profile or hw.current_profile())
        for key, act in self.fan_actions.items():
            act.setChecked(key == mode)
        for key, act in self.sound_actions.items():
            act.setChecked(key == self.cfg["sound_mode"])
        self.tray.setToolTip(f"NitroSense\nFan: {hw.MODE_LABELS.get(mode, mode.title() if mode else '?')}\n"
                             f"Sound: {audio.SOUND_LABELS.get(self.cfg['sound_mode'])}")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if not self.quitting and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.accept()
            QApplication.quit()

    def quit(self):
        self.quitting = True
        QApplication.quit()


def run(start_hidden=False):
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("NitroSense")
    app.setDesktopFileName("nitrosense")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((HERE / "style.qss").read_text())

    cfg = config.load()
    win = MainWindow(cfg)

    # Single instance: CLI / second launch talk to us over a local socket.
    server = QLocalServer()
    QLocalServer.removeServer(SOCKET_PATH)
    server.listen(SOCKET_PATH)

    def on_connection():
        sock = server.nextPendingConnection()

        def read():
            for line in bytes(sock.readAll()).decode(errors="ignore").splitlines():
                win.handle_command(line.strip())
            sock.disconnectFromServer()
        sock.readyRead.connect(read)
    server.newConnection.connect(on_connection)

    # Re-apply the saved fan mode at startup (sound is re-applied once the EQ is seen).
    win.fan_state = hw.fan_control_state()
    win.profile = hw.current_profile()
    if cfg.get("fan_mode") == "manual" and win.manual_ok:
        win.set_manual()
    elif cfg.get("fan_mode") in win.fan_buttons and hw.current_mode() != cfg["fan_mode"]:
        win.set_fan_mode(cfg["fan_mode"])
    win.refresh_buttons()

    poller = Poller()
    poller.sensors.connect(win.on_sensors)
    poller.pw_state.connect(win.on_pw_state)
    poller.start()

    if QSystemTrayIcon.isSystemTrayAvailable():
        win.build_tray()
    if not start_hidden or not QSystemTrayIcon.isSystemTrayAvailable():
        win.show()

    code = app.exec()
    poller.stop()
    server.close()
    return code
