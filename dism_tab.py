# dism_tab_pro.py
import sys
import re
from enum import Enum
from functools import partial
from PySide6 import QtCore, QtWidgets, QtGui

# ---- For standalone testing if fluent_widgets is not available ----
try:
    from fluent_widgets import FluentButton, LogBox
except ImportError:
    class FluentButton(QtWidgets.QPushButton):
        def __init__(self, text, icon=None):
            super().__init__(text)
            if icon: self.setIcon(icon)
    class LogBox(QtWidgets.QTextEdit):
        def __init__(self):
            super().__init__(); self.setReadOnly(True)
        def append_line(self, text: str): self.append(text)

# ---- Constants and Configuration ----
class DismMode(Enum):
    CHECK_HEALTH = ("/CheckHealth", "Quickly checks for component store corruption.", QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation)
    SCAN_HEALTH = ("/ScanHealth", "Performs a more thorough scan for corruption.", QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView)
    RESTORE_HEALTH = ("/RestoreHealth", "Scans and automatically repairs corruption.", QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)

DISM_PROGRESS_RE = re.compile(r"\[.*?(\d{1,3}\.\d)%.*?\]")

# ---- Main DISM Tab Widget ----
class DISMTab(QtWidgets.QWidget):
    """
    An advanced widget to run and monitor Windows DISM operations,
    featuring a responsive UI with animated progress.
    """
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.process: QtCore.QProcess | None = None
        self.buttons: list[QtWidgets.QPushButton] = []
        self._init_ui()
        self._connect_signals()
        self.setWindowTitle("DISM Utility")

    def _init_ui(self) -> None:
        """Initializes the user interface components."""
        main_layout = QtWidgets.QVBoxLayout(self)
        controls_layout = QtWidgets.QHBoxLayout()
        style = self.style()

        for mode in DismMode:
            command_str, tooltip, icon_enum = mode.value
            button = FluentButton(f"DISM {command_str}", style.standardIcon(icon_enum))
            button.setToolTip(tooltip)
            controls_layout.addWidget(button)
            self.buttons.append(button)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.progress_animation = QtCore.QPropertyAnimation(self.progress, b"value")
        self.progress_animation.setDuration(300)
        self.progress_animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        self.log = LogBox()
        self.log.setFont(QtGui.QFont("Consolas", 10))
        # <<< FIX: Use append_line() for the initial messages.
        self.log.append_line("Select a DISM command to run.")
        self.log.append_line("NOTE: This tool must be run with administrator privileges.")
        self.log.append_line("") # Add a blank line for spacing

        main_layout.addLayout(controls_layout)
        main_layout.addWidget(self.progress)
        main_layout.addWidget(self.log, 1)

    def _connect_signals(self) -> None:
        for i, mode in enumerate(DismMode):
            self.buttons[i].clicked.connect(partial(self.start_dism_command, mode))

    def _update_ui_state(self, is_running: bool) -> None:
        for button in self.buttons:
            button.setEnabled(not is_running)

    @QtCore.Slot(DismMode)
    def start_dism_command(self, mode: DismMode) -> None:
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            QtWidgets.QMessageBox.warning(self, "In Progress", "Another DISM command is already running.")
            return

        self.log.clear() # Assuming LogBox has a clear method, inherited from QTextEdit
        command_arg, _, _ = mode.value
        full_args = ["/Online", "/Cleanup-Image", command_arg]
        
        # <<< FIX: Use append_line()
        self.log.append_line(f"Starting 'dism {' '.join(full_args)}'...\n")
        
        self.progress.setValue(0)
        if mode is not DismMode.CHECK_HEALTH:
            self.progress.setRange(0, 0)

        self._update_ui_state(is_running=True)

        self.process = QtCore.QProcess()
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_ready_read)
        self.process.finished.connect(self.on_finished)
        self.process.start("dism", full_args)

    @QtCore.Slot()
    def on_ready_read(self) -> None:
        if not self.process: return
            
        output = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        for line in output.strip().splitlines():
            clean_line = line.strip()
            if not clean_line: continue
            
            # <<< FIX: Use append_line() to log output
            self.log.append_line(clean_line)
            
            match = DISM_PROGRESS_RE.search(clean_line)
            if match:
                if self.progress.minimum() == 0 and self.progress.maximum() == 0:
                    self.progress.setRange(0, 100)
                
                pct = int(float(match.group(1)))
                if pct > self.progress.value():
                    self.progress_animation.stop()
                    self.progress_animation.setStartValue(self.progress.value())
                    self.progress_animation.setEndValue(pct)
                    self.progress_animation.start()

    @QtCore.Slot(int, QtCore.QProcess.ExitStatus)
    def on_finished(self, exit_code: int, exit_status: QtCore.QProcess.ExitStatus) -> None:
        self.progress.setRange(0, 100)

        # <<< FIX: Use append_line() for final status messages
        if exit_status == QtCore.QProcess.ExitStatus.CrashExit:
            self.log.append_line("\n=== DISM FAILED: The process crashed. ===")
        elif exit_code == 0:
            self.log.append_line("\n=== DISM COMPLETE: The operation completed successfully. ===")
            if self.progress.value() < 100:
                self.progress_animation.stop()
                self.progress_animation.setStartValue(self.progress.value())
                self.progress_animation.setEndValue(100)
                self.progress_animation.start()
        else:
            self.log.append_line(f"\n=== DISM FINISHED (Code: {exit_code}): An error occurred. Check logs. ===")

        self._update_ui_state(is_running=False)
        self.process = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            reply = QtWidgets.QMessageBox.question(
                self, "Process in Progress",
                "A DISM command is running. Are you sure you want to exit? The process will be terminated.",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                self.process.kill()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

# --- For standalone testing ---
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = DISMTab()
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())