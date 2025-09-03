# dism_tab.py
import subprocess
from PySide6 import QtCore, QtWidgets
from fluent_widgets import FluentButton, LogBox

# ---- Worker Thread for DISM ----
class DISMWorker(QtCore.QThread):
    progress = QtCore.Signal(int)
    log_line = QtCore.Signal(str)
    finished = QtCore.Signal(int)

    def __init__(self, args: list[str]):
        super().__init__()
        self.args = args

    def run(self):
        try:
            proc = subprocess.Popen(
                ["dism"] + self.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in proc.stdout:
                self.log_line.emit(line.strip())
                # Parse progress percentage if printed
                if "%" in line:
                    try:
                        pct_text = line.strip().split()[0].replace(".", "").replace("%", "")
                        pct = int(pct_text)
                        self.progress.emit(pct)
                    except Exception:
                        pass
            proc.wait()
            self.finished.emit(proc.returncode)
        except Exception as e:
            self.log_line.emit(f"Error running DISM: {e}")
            self.finished.emit(1)

# ---- DISM Tab ----
class DISMTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)

        # Access style for icons
        style = self.style()

        # Buttons with icons
        self.btn_check = FluentButton(
            "DISM /CheckHealth",
            style.standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation)
        )
        self.btn_scan = FluentButton(
            "DISM /ScanHealth",
            style.standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView)
        )
        self.btn_restore = FluentButton(
            "DISM /RestoreHealth",
            style.standardIcon(QtWidgets.QStyle.SP_BrowserReload)
        )

        # Progress + Log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.log = LogBox()

        # Layout
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(self.btn_check)
        hlayout.addWidget(self.btn_scan)
        hlayout.addWidget(self.btn_restore)

        layout.addLayout(hlayout)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

        # Connect buttons
        self.btn_check.clicked.connect(lambda: self.run_dism(["/Online", "/Cleanup-Image", "/CheckHealth"]))
        self.btn_scan.clicked.connect(lambda: self.run_dism(["/Online", "/Cleanup-Image", "/ScanHealth"]))
        self.btn_restore.clicked.connect(lambda: self.run_dism(["/Online", "/Cleanup-Image", "/RestoreHealth"]))

        self.worker = None

    def run_dism(self, args):
        if self.worker and self.worker.isRunning():
            QtWidgets.QMessageBox.warning(self, "Already running", "Another DISM command is already running.")
            return
        self.log.append_line(f"Starting DISM {' '.join(args)} ...")
        self.progress.setValue(0)
        self.worker = DISMWorker(args)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log_line.connect(self.log.append_line)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, code):
        self.log.append_line(f"=== DISM finished with code {code} ===")
        if code == 0:
            self.progress.setValue(100)
