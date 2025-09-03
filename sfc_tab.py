# sfc_tab_pro_animated.py
import sys
import re
from enum import Enum
from PySide6 import QtCore, QtWidgets, QtGui

# ---- Constants and Configuration ----
class SfcMode(Enum):
    SCAN_NOW = ("/scannow", "Finds and repairs corrupt system files.")
    VERIFY_ONLY = ("/verifyonly", "Finds but does not repair corrupt system files.")

    def __str__(self):
        return self.name.replace('_', ' ').title()

PROGRESS_RE = re.compile(r"(\d{1,3})%")

# ---- Main SFC Tab Widget ----
class SFCTab(QtWidgets.QWidget):
    """
    An advanced widget to run and monitor Windows System File Checker (SFC).
    It uses QProcess for robust, non-blocking execution and provides
    an animated progress bar for a smoother user experience.
    """
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.process: QtCore.QProcess | None = None
        self._init_ui()
        self._connect_signals()
        self.setWindowTitle("SFC Utility")

    def _init_ui(self) -> None:
        """Initializes the user interface components."""
        main_layout = QtWidgets.QVBoxLayout(self)
        controls_layout = QtWidgets.QHBoxLayout()

        # --- Scan Mode Selection ---
        self.mode_combo = QtWidgets.QComboBox()
        for mode in SfcMode:
            self.mode_combo.addItem(str(mode), userData=mode)
            self.mode_combo.setItemData(self.mode_combo.count() - 1, mode.value[1], QtCore.Qt.ToolTipRole)

        # --- Run Button ---
        self.btn_run = QtWidgets.QPushButton("Start Scan")
        self.btn_run.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        
        controls_layout.addWidget(QtWidgets.QLabel("Mode:"))
        controls_layout.addWidget(self.mode_combo, 1)
        controls_layout.addWidget(self.btn_run, 1)

        # --- Progress and Logging ---
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        # <<< CHANGE: Set up the property animation for the progress bar
        self.progress_animation = QtCore.QPropertyAnimation(self.progress, b"value")
        self.progress_animation.setDuration(250) # Animate over 250ms
        self.progress_animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QtGui.QFont("Consolas", 10))
        self.log.append("Select a scan mode and press 'Start Scan'.\n"
                        "NOTE: This tool must be run with administrator privileges.\n")

        main_layout.addLayout(controls_layout)
        main_layout.addWidget(self.progress)
        main_layout.addWidget(self.log, 1)

    def _connect_signals(self) -> None:
        self.btn_run.clicked.connect(self.toggle_scan)

    def _update_ui_state(self, is_running: bool) -> None:
        self.mode_combo.setEnabled(not is_running)
        if is_running:
            self.btn_run.setText("Cancel Scan")
            self.btn_run.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
        else:
            self.btn_run.setText("Start Scan")
            self.btn_run.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))

    @QtCore.Slot()
    def toggle_scan(self) -> None:
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.log.append("\n=== SCAN CANCELLED BY USER ===")
            return

        self.log.clear()
        selected_mode: SfcMode = self.mode_combo.currentData()
        command, _ = selected_mode.value
        self.log.append(f"Starting 'sfc {command}'...")
        
        self.progress.setValue(0) # Reset instantly
        self.progress.setRange(0, 0)
        self._update_ui_state(is_running=True)

        self.process = QtCore.QProcess()
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_ready_read)
        self.process.finished.connect(self.on_finished)
        self.process.start("sfc", [command])

    @QtCore.Slot()
    def on_ready_read(self) -> None:
        if not self.process:
            return
            
        output = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        for line in output.strip().splitlines():
            clean_line = line.strip()
            if not clean_line:
                continue
            
            self.log.append(clean_line)
            
            match = PROGRESS_RE.search(clean_line)
            if match:
                if self.progress.minimum() == 0 and self.progress.maximum() == 0:
                    self.progress.setRange(0, 100)
                
                pct = int(match.group(1))

                # <<< CHANGE: Instead of setValue, run the animation
                # Only animate if the new value is greater to avoid backward animation
                if pct > self.progress.value():
                    self.progress_animation.stop() # Stop previous animation if any
                    self.progress_animation.setStartValue(self.progress.value())
                    self.progress_animation.setEndValue(pct)
                    self.progress_animation.start()

    @QtCore.Slot(int, QtCore.QProcess.ExitStatus)
    def on_finished(self, exit_code: int, exit_status: QtCore.QProcess.ExitStatus) -> None:
        if exit_status == QtCore.QProcess.ExitStatus.CrashExit:
            self.log.append("\n=== SCAN FAILED: The process crashed. ===")
        elif exit_code == 0:
            self.log.append("\n=== SCAN COMPLETE: No integrity violations found. ===")
        else:
            self.log.append(f"\n=== SCAN FINISHED (Code: {exit_code}): Check logs for details. ===")
        
        # <<< CHANGE: Animate the final jump to 100% for a consistent feel
        self.progress.setRange(0, 100)
        if self.progress.value() < 100 and exit_code == 0:
            self.progress_animation.stop()
            self.progress_animation.setStartValue(self.progress.value())
            self.progress_animation.setEndValue(100)
            self.progress_animation.start()
        
        self._update_ui_state(is_running=False)
        self.process = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Scan in Progress",
                "An SFC scan is still running. Are you sure you want to exit? The scan will be terminated.",
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
    window = SFCTab()
    window.resize(600, 400)
    window.show()
    sys.exit(app.exec())