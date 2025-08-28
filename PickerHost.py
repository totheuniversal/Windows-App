import sys, time, ctypes, psutil, traceback, platform, threading, os, winreg
from ctypes import wintypes
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSystemTrayIcon, QMenu, QCheckBox
from PySide6.QtGui import QColor, QPainter, QMouseEvent, QFont, QIcon, QAction, QPixmap
from PySide6.QtCore import Qt, QTimer, QPoint, QLockFile, QStandardPaths, QDir, QSettings, QEvent

APP_NAME = "PickerHost Monitor"
ORG = "Pailant"
DOMAIN = "pailant.co.kr"
PROC_NAME = "pickerhost.exe"
BASE_W, BASE_H, TITLE_H = 360, 260, 32
SCAN_MS_MIN = 400
SCAN_MS_NORMAL = 2000
SCAN_MS_MAX = 15000
KILL_WAIT = 0.5
RECHECK_MS = 300
BACKOFF_STEP = 2000
FAIL_BACKOFF_MAX = 12000
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

IS_WINDOWS = platform.system() == "Windows"

# -------- Windows blur --------
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int), ("GradientColor", ctypes.c_int), ("AnimationId", ctypes.c_int)]
class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]
def enable_blur(hwnd: int):
    if not IS_WINDOWS: return
    try:
        accent = ACCENT_POLICY(3, 0, 0xCC000000, 0)
        data = WINCOMPATTRDATA(19, ctypes.addressof(accent), ctypes.sizeof(accent))
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass

# -------- Icons --------
ICON_CACHE = {}
def make_icon(color: str) -> QIcon:
    ic = ICON_CACHE.get(color)
    if ic:
        return ic
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.black)
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    ICON_CACHE[color] = QIcon(pm)
    return ICON_CACHE[color]

# -------- Admin helpers --------
def is_admin() -> bool:
    if not IS_WINDOWS: return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def elevate():
    if not IS_WINDOWS: return
    try:
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{sys.argv[0]}" {params}', None, 1)
    except Exception:
        traceback.print_exc()

# -------- Autostart --------
def is_autostart_enabled() -> bool:
    if not IS_WINDOWS: return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except Exception:
        return False

def set_autostart(enable: bool):
    if not IS_WINDOWS: return
    exe_path = sys.executable
    script_path = os.path.abspath(sys.argv[0])
    cmd = f'"{exe_path}" "{script_path}"'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f"[AutoStart ERROR] {e}")

# -------- Process helpers --------
def find_pickerhost() -> psutil.Process | None:
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                n = proc.info.get("name")
                if n and n.lower() == PROC_NAME:
                    return proc
            except psutil.Error:
                continue
    except psutil.Error:
        return None
    return None

def safe_kill(proc: psutil.Process) -> tuple[bool, str]:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=KILL_WAIT); return True, "terminated"
        except psutil.TimeoutExpired:
            pass
        proc.kill()
        try:
            proc.wait(timeout=KILL_WAIT); return True, "killed"
        except psutil.TimeoutExpired:
            return False, "timeout"
    except psutil.NoSuchProcess:
        return True, "gone"
    except psutil.AccessDenied:
        return False, "access denied"
    except Exception as e:
        return False, f"error: {e}"

# -------- WMI watcher (unchanged) --------
class WMIWatcher:
    def __init__(self, target_name: str, on_detect):
        self.target = target_name.lower()
        self._on_detect = on_detect
        self._thread = None
        self._running = False
        self.available = False
        try:
            import pythoncom, win32com.client
            self._pythoncom = pythoncom
            self._win32 = win32com.client
            self.available = True
        except Exception:
            self.available = False
    def start(self):
        if not self.available or self._running: return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True
    def stop(self):
        self._running = False
    def _run(self):
        try:
            self._pythoncom.CoInitialize()
            wmi = self._win32.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", "root\\cimv2")
            q = ("SELECT * FROM __InstanceCreationEvent WITHIN 1 "
                 "WHERE TargetInstance ISA 'Win32_Process' "
                 f"AND LCASE(TargetInstance.Name)='{self.target}'")
            watcher = wmi.ExecNotificationQuery(q)
            while self._running:
                try:
                    ev = watcher.NextEvent(2000)
                    if ev is None: continue
                    self._on_detect()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try: self._pythoncom.CoUninitialize()
            except Exception: pass

# -------- Mouse transparency --------
GWL_EXSTYLE       = -20
WS_EX_TRANSPARENT = 0x00000020

def _get_set_window_long_funcs():
    if not IS_WINDOWS:
        return None, None
    user32 = ctypes.windll.user32
    SetWindowLongPtrW = getattr(user32, "SetWindowLongPtrW", None)
    GetWindowLongPtrW = getattr(user32, "GetWindowLongPtrW", None)
    if SetWindowLongPtrW is None:  # 32-bit fallback
        SetWindowLongPtrW = user32.SetWindowLongW
        GetWindowLongPtrW = user32.GetWindowLongW
    return GetWindowLongPtrW, SetWindowLongPtrW

def _set_transparent(hwnd: int, enable: bool):
    """Toggle WS_EX_TRANSPARENT for real hit-test pass-through."""
    if not IS_WINDOWS or not hwnd:
        return
    user32 = ctypes.windll.user32
    GetGWL, SetGWL = _get_set_window_long_funcs()
    ex = GetGWL(hwnd, GWL_EXSTYLE)
    if enable:
        ex |= WS_EX_TRANSPARENT
    else:
        ex &= ~WS_EX_TRANSPARENT
    SetGWL(hwnd, GWL_EXSTYLE, ex)

# Poll Shift like Rainmeter’s “hold modifier to interact”
VK_SHIFT = 0x10
def _is_shift_down() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
    except Exception:
        return False

# -------- UI bits --------
class Lamp(QWidget):
    def __init__(self, color="grey", parent=None):
        super().__init__(parent); self._c = QColor(color); self.setFixedSize(56, 56)
    def set(self, color: str):
        c = QColor(color)
        if c != self._c: self._c = c; self.update()
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._c); p.setPen(Qt.black); p.drawEllipse(4, 4, 48, 48)

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG, APP_NAME)
        self.monitoring = self.settings.value("monitoring", True, type=bool)
        self.click_through_enabled = self.settings.value("click_through", False, type=bool)
        self.drag_off = QPoint()
        self.maxed = False
        self.last_text = ""
        self._last_tray_color = None
        self.scan_interval = SCAN_MS_NORMAL
        self.fail_backoff_ms = 0
        self.cooldown_until_ms = 0
        self.shift_down = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Title bar
        self.top = QFrame(); self.top.setFixedHeight(TITLE_H); self.top.setStyleSheet("background:#2D2D30;")
        title = QLabel(f"  {APP_NAME}"); title.setFont(QFont("Segoe UI", 10)); title.setStyleSheet("color:white;")
        self.btnMin = QPushButton("—"); self.btnMin.clicked.connect(self.hide)
        self.btnMax = QPushButton("⬜"); self.btnMax.clicked.connect(self.toggle_max)
        self.btnClose = QPushButton("✕"); self.btnClose.clicked.connect(self.quit)
        for b in (self.btnMin, self.btnMax, self.btnClose):
            b.setFixedSize(40, TITLE_H)
            b.setStyleSheet("QPushButton{background:transparent;color:white;border:0;font:10pt 'Segoe UI'}QPushButton:hover{background:rgba(255,255,255,.15)}")
        self.btnClose.setStyleSheet(self.btnClose.styleSheet()+"QPushButton:hover{background:red}")
        tl = QHBoxLayout(self.top); tl.setContentsMargins(5,0,0,0)
        tl.addWidget(title); tl.addStretch(); tl.addWidget(self.btnMin); tl.addWidget(self.btnMax); tl.addWidget(self.btnClose)

        # Body
        self.lamp = Lamp()
        self.status = QLabel("Checking..."); self.status.setFont(QFont("Segoe UI", 11)); self.status.setStyleSheet("color:white;")
        self.btnToggle = QPushButton(); self.btnToggle.clicked.connect(self.toggle_monitor)
        self.btnFix = QPushButton("Fix Now"); self.btnFix.clicked.connect(self.fix_now)
        self.btnFix.setStyleSheet("QPushButton{background:rgba(50,50,50,.85);color:white;padding:6px 12px;border-radius:6px;font:9pt 'Segoe UI'}QPushButton:hover{background:rgba(80,80,80,.95)}")

        self.chkAutoStart = QCheckBox("Start with Windows")
        self.chkAutoStart.setStyleSheet("color:white;font:9pt 'Segoe UI'")
        self.chkAutoStart.setChecked(is_autostart_enabled())
        self.chkAutoStart.stateChanged.connect(self.toggle_autostart)

        self.chkClickThrough = QCheckBox("Click-through (hold Shift to interact)")
        self.chkClickThrough.setStyleSheet("color:white;font:9pt 'Segoe UI'")
        self.chkClickThrough.setChecked(self.click_through_enabled)
        self.chkClickThrough.stateChanged.connect(self.toggle_click_through)

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(10)
        root.addWidget(self.top); root.addWidget(self.lamp, alignment=Qt.AlignCenter)
        root.addWidget(self.status, alignment=Qt.AlignCenter)
        root.addWidget(self.btnToggle, alignment=Qt.AlignCenter)
        root.addWidget(self.btnFix, alignment=Qt.AlignCenter)
        root.addWidget(self.chkAutoStart, alignment=Qt.AlignCenter)
        root.addWidget(self.chkClickThrough, alignment=Qt.AlignCenter)

        # Tray
        self.tray = QSystemTrayIcon(make_icon("grey"), self)
        menu = QMenu()
        self.actShow = QAction("Show", self, triggered=self.show_normal)
        self.actToggle = QAction("", self, triggered=self.toggle_monitor_from_tray)
        self.actFix = QAction("Fix Now", self, triggered=self.fix_now)
        self.actElevate = QAction("Run as Administrator", self, triggered=self.run_as_admin)
        self.actClickThrough = QAction("Toggle Click-through", self, triggered=lambda: self.chkClickThrough.toggle())
        self.actQuit = QAction("Quit", self, triggered=self.quit)
        for a in (self.actShow, self.actToggle, self.actFix, self.actElevate, self.actClickThrough, self.actQuit): menu.addAction(a)
        self.tray.setContextMenu(menu); self.tray.setToolTip(APP_NAME); self.tray.show()
        self.tray.activated.connect(self.on_tray)

        # DPI
        self.apply_scale(QApplication.primaryScreen())
        QApplication.primaryScreen().logicalDotsPerInchChanged.connect(lambda _: self.apply_scale(QApplication.primaryScreen()))

        if IS_WINDOWS:
            QTimer.singleShot(0, lambda: enable_blur(self.winId().__int__()))

        # WMI
        self._wmi = WMIWatcher(PROC_NAME, on_detect=self._on_wmi_detect)
        self.wmi_running = self._wmi.start()

        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(self.scan_interval)
        self.update_toggle_btn(); self.update_tray_toggle_text()

        # Poll Shift ~30 Hz
        self._shift_timer = QTimer(self)
        self._shift_timer.setInterval(33)
        self._shift_timer.timeout.connect(self._poll_shift)
        self._shift_timer.start()

        self.installEventFilter(self)
        self._apply_click_through_state()

        self.fix_now()
        QTimer.singleShot(500, self.hide)
        QApplication.instance().aboutToQuit.connect(self._cleanup)

    def toggle_click_through(self, state):
        self.click_through_enabled = (state == Qt.Checked)
        self.settings.setValue("click_through", self.click_through_enabled)
        self._apply_click_through_state()

    def _poll_shift(self):
        new_state = _is_shift_down()
        if new_state != self.shift_down:
            self.shift_down = new_state
            self._apply_click_through_state()

    def _apply_click_through_state(self):
        effective = self.click_through_enabled and not self.shift_down
        self.setAttribute(Qt.WA_TransparentForMouseEvents, effective)
        if IS_WINDOWS:
            _set_transparent(int(self.winId().__int__()), effective)

    # Optional: allow only Shift+LeftClick while interactive
    def eventFilter(self, obj, ev):
        if self.click_through_enabled and self.shift_down:
            t = ev.type()
            if t in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                QEvent.MouseButtonDblClick, QEvent.Wheel,
                QEvent.HoverEnter, QEvent.HoverMove, QEvent.HoverLeave
            ):
                if t in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
                    if hasattr(ev, "button") and ev.button() != Qt.LeftButton:
                        return True
                else:
                    return True
        return super().eventFilter(obj, ev)

    # ---- Usual window behaviors ----
    def show_normal(self): self.showNormal(); self.raise_(); self.activateWindow()
    def on_tray(self, reason): 
        if reason == QSystemTrayIcon.DoubleClick: self.show_normal()
    def mousePressEvent(self, e: QMouseEvent):
        if e.button()==Qt.LeftButton and e.position().y()<=TITLE_H:
            self.drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e: QMouseEvent):
        if e.buttons() & Qt.LeftButton and not self.maxed and not self.drag_off.isNull():
            self.move(e.globalPosition().toPoint() - self.drag_off)
    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.position().y()<=TITLE_H: self.toggle_max()
    def toggle_max(self):
        if self.maxed: self.showNormal(); self.maxed=False; self.btnMax.setText("⬜")
        else: self.showMaximized(); self.maxed=True; self.btnMax.setText("❐")
    def quit(self):
        try: self._wmi.stop()
        except Exception: pass
        self.tray.hide(); QApplication.quit()
    def apply_scale(self, screen):
        s = screen.logicalDotsPerInch()/96.0
        self.resize(int(BASE_W*s), int(BASE_H*s))
        self.setFont(QFont("Segoe UI", max(9, int(10*s))))
    def update_toggle_btn(self):
        if self.monitoring:
            self.btnToggle.setText("Stop Monitor")
            self.btnToggle.setStyleSheet("QPushButton{background:red;color:white;padding:6px 12px;border-radius:6px;font:9pt 'Segoe UI'}QPushButton:hover{background:darkred}")
        else:
            self.btnToggle.setText("Start Monitor")
            self.btnToggle.setStyleSheet("QPushButton{background:rgba(50,50,50,.85);color:white;padding:6px 12px;border-radius:6px;font:9pt 'Segoe UI'}QPushButton:hover{background:rgba(80,80,80,.95)}")
    def update_tray_toggle_text(self): self.actToggle.setText("Stop Monitor" if self.monitoring else "Start Monitor")
    def toggle_monitor(self):
        self.monitoring = not self.monitoring
        self.settings.setValue("monitoring", self.monitoring)
        self.update_toggle_btn(); self.update_tray_toggle_text()
    def toggle_monitor_from_tray(self): self.toggle_monitor()
    def toggle_autostart(self, state): set_autostart(state == Qt.Checked)
    def set_state(self, text: str, lamp: str, tray_color: str):
        if text != self.last_text: self.status.setText(text); self.last_text = text
        self.lamp.set(lamp)
        if tray_color != self._last_tray_color:
            self.tray.setIcon(make_icon(tray_color)); self._last_tray_color = tray_color
    def run_as_admin(self):
        if is_admin(): self.set_state("Already running as Administrator", "blue", "blue"); return
        elevate(); QTimer.singleShot(100, self.quit)
    def fix_now(self):
        p = find_pickerhost()
        if not p:
            self._set_quiet(); self.set_state("PickerHost.exe not running", "green", "green"); return
        ok, how = safe_kill(p)
        if ok:
            self._set_burst(); self.set_state(f"PickerHost.exe {how} (manual)", "blue", "blue")
        else:
            self._set_fail_backoff(how)
    def _on_wmi_detect(self):
        QTimer.singleShot(0, self._handle_detect)
    def _handle_detect(self):
        if not self.monitoring:
            self.set_state("PickerHost.exe detected (not killing)", "orange", "orange"); return
        p = find_pickerhost()
        if not p:
            self._set_quiet(); self.set_state("PickerHost.exe vanished", "green", "green"); return
        ok, how = safe_kill(p)
        if ok:
            self._set_burst(); self.set_state("PickerHost.exe detected & auto-killed", "red", "red")
        else:
            self._set_fail_backoff(how)
    def tick(self):
        now_ms = int(time.time()*1000)
        if now_ms < self.cooldown_until_ms: return
        if self.fail_backoff_ms:
            self.fail_backoff_ms -= self.scan_interval
            if self.fail_backoff_ms > 0: return
            self.fail_backoff_ms = 0
        p = find_pickerhost()
        if p:
            if not self.monitoring:
                self._grow_quiet(); self.set_state("PickerHost.exe detected (not killing)", "orange", "orange"); return
            ok, how = safe_kill(p)
            if ok:
                self._set_burst(); self.set_state("PickerHost.exe detected & auto-killed", "red", "red")
            else:
                self._set_fail_backoff(how)
        else:
            self._grow_quiet(); self.set_state("PickerHost.exe not running", "green", "green")
    def _apply_interval(self, ms: int):
        ms = max(SCAN_MS_MIN, min(SCAN_MS_MAX, ms))
        if ms != self.scan_interval:
            self.scan_interval = ms
            self.timer.setInterval(self.scan_interval)
    def _set_burst(self):
        self.cooldown_until_ms = int(time.time()*1000) + RECHECK_MS
        self._apply_interval(SCAN_MS_MIN)
    def _set_quiet(self):
        self._apply_interval(SCAN_MS_NORMAL)
    def _grow_quiet(self):
        self._apply_interval(min(SCAN_MS_MAX, self.scan_interval + BACKOFF_STEP))
    def _set_fail_backoff(self, how: str):
        if "access denied" in how and not is_admin():
            self.set_state("Access denied — try Run as Administrator", "orange", "orange")
        else:
            self.set_state(f"Kill failed: {how}", "orange", "orange")
        self.fail_backoff_ms = min(FAIL_BACKOFF_MAX, max(1500, self.scan_interval * 2))
        self._apply_interval(min(self.scan_interval * 2, SCAN_MS_MAX))
    def _cleanup(self):
        try: self._wmi.stop(); self.timer.stop()
        except Exception: pass

# -------- Single instance lock --------
def single_instance_lock():
    path = QStandardPaths.writableLocation(QStandardPaths.TempLocation) or "."
    lock_path = QDir.toNativeSeparators(path + "/pickerhost_monitor.lock")
    lock = QLockFile(lock_path); lock.setStaleLockTime(2000)
    if not lock.tryLock(100): return None
    return lock

# -------- Main --------
if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setOrganizationName(ORG); app.setOrganizationDomain(DOMAIN); app.setApplicationName(APP_NAME)
    lock = single_instance_lock()
    if lock is None: sys.exit(0)
    w = App(); w.show()
    try:
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc(); sys.exit(1)
