#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fluent-style Audio Driver Manager (Windows, PySide6)
Features:
- List all audio devices (PnP classes: Media, AudioEndpoint)
- Reset All (disable -> enable for each listed device)
- Classic "Reset Windows Audio Service" button
- Elevation button + admin status chip

Requirements:
    pip install PySide6
Notes:
- Uses PowerShell Get-PnpDevice/Disable-PnpDevice/Enable-PnpDevice (requires admin for reset)
- Gracefully logs failures (e.g., device in use or insufficient privileges)
"""

import sys
import os
import json
import ctypes
import subprocess
from PySide6 import QtCore, QtGui, QtWidgets

APP_TITLE = "Audio Driver Manager — Fluent"
IS_WINDOWS = (os.name == "nt")

# ---- Elevation helpers ----
def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_as_admin():
    if not IS_WINDOWS:
        return
    try:
        params = " ".join(['"%s"' % a for a in sys.argv])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Elevation failed", f"Could not relaunch as administrator:\n{e}")

# ---- Windows 11 Mica Backdrop (best effort) ----
def try_enable_mica(win_id):
    if not IS_WINDOWS:
        return
    try:
        DWMWA_SYSTEMBACKDROP_TYPE = 38  # Windows 11
        DWMSBT_MAINWINDOW = 2           # Mica
        DWMWA_MICA_EFFECT = 1029        # legacy/optional

        hwnd = int(win_id)
        dwm = ctypes.windll.dwmapi

        backdrop = ctypes.c_int(DWMSBT_MAINWINDOW)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                  ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
                                  ctypes.byref(backdrop),
                                  ctypes.sizeof(backdrop))

        mica_enabled = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                  ctypes.c_uint(DWMWA_MICA_EFFECT),
                                  ctypes.byref(mica_enabled),
                                  ctypes.sizeof(mica_enabled))
    except Exception:
        pass

# ---- Command helpers ----
def run_cmd(cmd: list[str] | str, use_shell=False):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, shell=use_shell)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)

def run_powershell(ps_script: str):
    """Execute PowerShell with -NoProfile and return (returncode, stdout, stderr)."""
    if not IS_WINDOWS:
        return 1, "", "PowerShell not available on non-Windows"
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
    return run_cmd(cmd)

def list_audio_devices():
    """
    Returns a list of dicts with keys: InstanceId, FriendlyName/Name, Status, Class
    Combines classes: Media and AudioEndpoint
    """
    ps = r"""
$classes = @("Media", "AudioEndpoint")
$devices = @()
foreach ($c in $classes) {
  try {
    $d = Get-PnpDevice -Class $c -ErrorAction SilentlyContinue | Select-Object InstanceId, FriendlyName, Name, Status, Class
    if ($d) { $devices += $d }
  } catch {}
}
$devices | ConvertTo-Json -Depth 3
"""
    rc, out, err = run_powershell(ps)
    if rc != 0:
        return [], f"PowerShell error listing devices: {err.strip()}"
    try:
        data = json.loads(out) if out.strip() else []
        if isinstance(data, dict):
            data = [data]
        # Normalize fields
        norm = []
        for d in data:
            norm.append({
                "InstanceId": d.get("InstanceId"),
                "Name": d.get("FriendlyName") or d.get("Name") or "(unnamed device)",
                "Status": d.get("Status") or "",
                "Class": d.get("Class") or "",
            })
        return norm, ""
    except Exception as e:
        return [], f"JSON parse error: {e}\nRaw: {out[:2000]}"

def reset_device(instance_id: str):
    """
    Disable and then enable the device via PowerShell.
    Returns (ok: bool, log: str)
    """
    ps = fr"""
$inst = \"{instance_id}\"
$err = $null
try {{
  Disable-PnpDevice -InstanceId $inst -Confirm:$false -ErrorAction Stop | Out-Null
}} catch {{ $err = $_.Exception.Message }}
if ($err) {{
  Write-Output (\"Disable failed: \" + $err)
}} else {{
  Write-Output \"Disable: OK\"
}}
Start-Sleep -Milliseconds 600
$err2 = $null
try {{
  Enable-PnpDevice -InstanceId $inst -Confirm:$false -ErrorAction Stop | Out-Null
}} catch {{ $err2 = $_.Exception.Message }}
if ($err2) {{
  Write-Output (\"Enable failed: \" + $err2)
}} else {{
  Write-Output \"Enable: OK\"
}}
"""
    rc, out, err = run_powershell(ps)
    ok = (rc == 0) and ("Enable: OK" in out)
    return ok, (out.strip() + ("\n" + err.strip() if err.strip() else ""))

def reset_windows_audio_service():
    """Run net stop/start audiosrv. Returns combined log text."""
    steps = []
    rc1, out1, err1 = run_cmd(["cmd", "/c", "net stop audiosrv"])
    steps.append("> net stop audiosrv")
    if out1.strip(): steps.append(out1.strip())
    if err1.strip(): steps.append(err1.strip())
    steps.append(f"Exit code: {rc1}")
    rc2, out2, err2 = run_cmd(["cmd", "/c", "net start audiosrv"])
    steps.append("> net start audiosrv")
    if out2.strip(): steps.append(out2.strip())
    if err2.strip(): steps.append(err2.strip())
    steps.append(f"Exit code: {rc2}")
    ok = (rc1 == 0 and rc2 == 0)
    steps.append("✅ Audio service reset completed successfully." if ok else "⚠️ Audio service reset had errors.")
    return "\n".join(steps), ok

# ---- UI widgets ----
class FluentButton(QtWidgets.QPushButton):
    def __init__(self, text="", icon: QtGui.QIcon | None = None, *args, **kwargs):
        super().__init__(text, *args, **kwargs)
        if icon:
            self.setIcon(icon)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setStyleSheet("""
            QPushButton {
                background: rgba(0,0,0,0.04);
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 12px;
                padding: 8px 14px;
                font-size: 12.5pt;
            }
            QPushButton:hover { background: rgba(0,0,0,0.07); }
            QPushButton:pressed { background: rgba(0,0,0,0.12); }
            QPushButton:disabled {
                background: rgba(0,0,0,0.02);
                color: rgba(0,0,0,0.4);
            }
        """)

class StatusChip(QtWidgets.QLabel):
    def __init__(self, text, ok=True, parent=None):
        super().__init__(text, parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMargin(6)
        self.setStyleSheet(f"""
            QLabel {{
                border-radius: 10px;
                padding: 4px 10px;
                color: {'#0F5132' if ok else '#664D03'};
                background: {'#D1E7DD' if ok else '#FFF3CD'};
                border: 1px solid {'#BADBCC' if ok else '#FFE69C'};
                font: 10pt "Segoe UI";
            }}
        """)

class LogBox(QtWidgets.QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(255,255,255,0.7);
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 12px;
                padding: 10px;
                font: 10.5pt "Consolas";
            }
        """)

    def append_line(self, text: str):
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

class DevicesTable(QtWidgets.QTableWidget):
    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["Name", "Status", "Class", "Instance Id"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setWordWrap(False)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)

    def load_devices(self, devices: list[dict]):
        self.setRowCount(0)
        for d in devices:
            row = self.rowCount()
            self.insertRow(row)
            self.setItem(row, 0, QtWidgets.QTableWidgetItem(d.get("Name","")))
            self.setItem(row, 1, QtWidgets.QTableWidgetItem(d.get("Status","")))
            self.setItem(row, 2, QtWidgets.QTableWidgetItem(d.get("Class","")))
            self.setItem(row, 3, QtWidgets.QTableWidgetItem(d.get("InstanceId","")))

# ---- Main Window ----
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(980, 640)
        self.setMinimumSize(820, 520)
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaVolume))

        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        title = QtWidgets.QLabel("Audio Driver Manager")
        title.setStyleSheet('font: 700 18pt "Segoe UI"; margin-bottom: 2px;')
        subtitle = QtWidgets.QLabel("List & reset all audio devices • Also reset Windows Audio service")
        subtitle.setStyleSheet('font: 10.5pt "Segoe UI"; color: #555; margin-bottom: 8px;')

        self.btn_refresh = FluentButton("List Audio Devices", self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        self.btn_refresh.clicked.connect(self.on_refresh)

        self.btn_reset_all = FluentButton("Reset ALL Devices", self.style().standardIcon(QtWidgets.QStyle.SP_MediaSkipForward))
        self.btn_reset_all.clicked.connect(self.on_reset_all)

        self.btn_reset_service = FluentButton("Reset Windows Audio Service", self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.btn_reset_service.clicked.connect(self.on_reset_service)

        self.btn_admin = FluentButton("Run as Administrator", self.style().standardIcon(QtWidgets.QStyle.SP_DialogYesButton))
        self.btn_admin.clicked.connect(relaunch_as_admin)

        self.chip = StatusChip("Admin: YES" if is_admin() else "Admin: NO", ok=is_admin())

        self.table = DevicesTable()
        self.log = LogBox()

        # Layout
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(self.btn_refresh)
        top_row.addWidget(self.btn_reset_all)
        top_row.addWidget(self.btn_reset_service)
        top_row.addStretch(1)
        top_row.addWidget(self.btn_admin)
        top_row.addWidget(self.chip)

        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        v.addWidget(title)
        v.addWidget(subtitle)
        v.addLayout(top_row)
        v.addWidget(self.table, 3)
        v.addWidget(self.log, 2)

        # Try Mica on Win11
        if IS_WINDOWS:
            self.show()
            QtCore.QTimer.singleShot(150, lambda: try_enable_mica(self.winId()))

        # Light palette
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(245, 246, 248))
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
        self.setPalette(pal)

        self.on_refresh()

    def update_chip(self):
        admin = is_admin()
        self.chip.setText("Admin: YES" if admin else "Admin: NO")
        self.chip.setStyleSheet(f"""
            QLabel {{
                border-radius: 10px;
                padding: 4px 10px;
                color: {'#0F5132' if admin else '#664D03'};
                background: {'#D1E7DD' if admin else '#FFF3CD'};
                border: 1px solid {'#BADBCC' if admin else '#FFE69C'};
                font: 10pt "Segoe UI";
            }}
        """)

    def on_refresh(self):
        self.log.append_line("Listing audio devices (Media, AudioEndpoint)...")
        devices, err = list_audio_devices()
        if err:
            self.log.append_line(err)
        else:
            self.log.append_line(f"Found {len(devices)} device(s).")
        self.table.load_devices(devices)

    def on_reset_service(self):
        if not IS_WINDOWS:
            QtWidgets.QMessageBox.critical(self, "Unsupported OS", "This tool requires Windows.")
            return
        self.log.append_line("=== Resetting Windows Audio service ===")
        text, ok = reset_windows_audio_service()
        for line in text.splitlines():
            self.log.append_line(line)

    def on_reset_all(self):
        if not IS_WINDOWS:
            QtWidgets.QMessageBox.critical(self, "Unsupported OS", "This tool requires Windows.")
            return
        if not is_admin():
            QtWidgets.QMessageBox.warning(self, "Administrator required",
                                          "Resetting devices requires Administrator privileges.\nClick 'Run as Administrator' and try again.")
            self.update_chip()
            return
        self.btn_reset_all.setEnabled(False)
        self.log.append_line("=== Resetting ALL audio devices ===")
        devices, err = list_audio_devices()
        if err:
            self.log.append_line(err)
            self.btn_reset_all.setEnabled(True)
            return
        if not devices:
            self.log.append_line("No audio devices found.")
            self.btn_reset_all.setEnabled(True)
            return

        for d in devices:
            name = d.get("Name", "(unnamed)")
            inst = d.get("InstanceId", "")
            self.log.append_line(f"[{name}]")
            self.log.append_line(f"  InstanceId: {inst}")
            ok, out = reset_device(inst)
            for line in out.splitlines():
                self.log.append_line("  " + line)
            self.log.append_line(f"  Result: {'OK' if ok else 'FAILED'}\n")
            QtWidgets.QApplication.processEvents()

        self.log.append_line("=== Reset ALL finished ===\n")
        self.btn_reset_all.setEnabled(True)
        self.update_chip()
if IS_WINDOWS and not is_admin():
    import ctypes
    params = " ".join([f'"{a}"' for a in sys.argv])
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable.replace("python.exe", "pythonw.exe"), params, None, 1
        )
        sys.exit(0)  # Exit the non-admin instance
    except Exception as e:
        from PySide6 import QtWidgets
        QtWidgets.QMessageBox.critical(None, "Elevation failed", str(e))
        sys.exit(1)

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationDisplayName(APP_TITLE)
    app.setFont(QtGui.QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
