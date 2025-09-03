# sfc_tab.py
import subprocess
from PySide6 import QtCore, QtWidgets
from fluent_widgets import FluentButton, LogBox

# ---- Worker Thread for SFC ----
class SFCWorker(QtCore.QThread):
    progress = QtCore.Signal(int)
    log_line = QtCore.Signal(str)
    finished = QtCore.Signal(int)

    def run(self):
        try:
            proc = subprocess.Popen(
                ["sfc", "/scannow"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in proc.stdout:
                self.log_line.emit(line.strip())
                # Parse percentage like "Verification 25% complete"
                if "%" in line and "complete" in line.lower():
                    try:
                        pct = int(line.strip().split("%")[0].split()[-1])
                        self.progress.emit(pct)
                    except Exception:
                        pass
            proc.wait()
            self.finished.emit(proc.returncode)
        except Exception as e:
            self.log_line.emit(f"Error running sfc: {e}")
            self.finished.emit(1)

# ---- SFC Tab ----
class SFCTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)

        # Styled button with icon
        style = self.style()
        self.btn_run = FluentButton(
            "SFC /SCANNOW",
            style.standardIcon(QtWidgets.QStyle.SP_DialogApplyButton)
        )

        # Progress + Log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.log = LogBox()

        layout.addWidget(self.btn_run)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

        self.btn_run.clicked.connect(self.on_run)
        self.worker = None

    def on_run(self):
        if self.worker and self.worker.isRunning():
            QtWidgets.QMessageBox.warning(self, "Already running", "SFC is already running.")
            return
        self.log.append_line("Starting sfc /scannow ...")
        self.progress.setValue(0)
        self.worker = SFCWorker()
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log_line.connect(self.log.append_line)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, code):
        self.log.append_line(f"=== SFC finished with code {code} ===")
        if code == 0:
            self.progress.setValue(100)
