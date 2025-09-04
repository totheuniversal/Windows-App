# main_window.py
from PySide6 import QtCore, QtGui, QtWidgets

from core.utils import IS_WINDOWS, is_admin, relaunch_as_admin
from core.winfx import try_enable_mica
from ui.components import StatusChip
from tabs.audio_tab import AudioTab
from tabs.port_tab import PortTab
from tabs.sfc_tab import SFCTab
from tabs.dism_tab import DISMTab

APP_TITLE = "Windows Toolbox"

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1040, 680)
        self.setMinimumSize(880, 560)
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaVolume))

        # ---- Central: Tabs
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        # Tabs
        self.audio_tab = AudioTab()
        self.tabs.addTab(self.audio_tab, "Audio Manager")

        self.sfc_tab = SFCTab()
        self.tabs.addTab(self.sfc_tab, "SFC /SCANNOW")

        self.dism_tab = DISMTab()
        self.tabs.addTab(self.dism_tab, "DISM Tools")

        self.port_tab = PortTab()
        self.tabs.addTab(self.port_tab, "Port option")


        from tabs.picker_tab import PickerHostTab

        # ...
        self.picker_tab = PickerHostTab()
        self.tabs.addTab(self.picker_tab, "PickerHost")

        # ---- Status bar
        self.status = self.statusBar()
        self.status.setSizeGripEnabled(True)
        self.chip = StatusChip("Admin: YES" if is_admin() else "Admin: NO", ok=is_admin())
        w = QtWidgets.QWidget()
        l = QtWidgets.QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.addStretch(1)
        l.addWidget(self.chip)
        self.status.addPermanentWidget(w, 1)

        # ---- Menu bar (File/Tools/Help)
        self._build_menu()

        # ---- Theme & background (Mica best-effort)
        self._apply_palette()
        if IS_WINDOWS:
            self.show()
            QtCore.QTimer.singleShot(150, lambda: try_enable_mica(self.winId()))

        # Initial data load
        self.audio_tab.refresh()

    def _build_menu(self):
        mb = self.menuBar()

        # File
        m_file = mb.addMenu("&File")
        act_exit = QtGui.QAction("E&xit", self, triggered=self.close)
        act_exit.setShortcut("Ctrl+Q")
        m_file.addAction(act_exit)

        # Tools
        m_tools = mb.addMenu("&Tools")
        act_admin = QtGui.QAction("Run as &Administrator", self, triggered=self._run_as_admin)
        act_refresh = QtGui.QAction("&Refresh Audio Devices", self, triggered=self.audio_tab.refresh)
        m_tools.addAction(act_admin)
        m_tools.addAction(act_refresh)

        # Help
        m_help = mb.addMenu("&Help")
        act_about = QtGui.QAction("&About", self, triggered=self._about)
        m_help.addAction(act_about)

    def _apply_palette(self):
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(245, 246, 248))
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
        self.setPalette(pal)

    def _run_as_admin(self):
        if relaunch_as_admin():
            QtWidgets.QMessageBox.information(self, "Elevation", "Relaunching as Administrator...")
        else:
            QtWidgets.QMessageBox.critical(self, "Elevation failed", "Could not relaunch as administrator.")
        self._update_chip()

    def _about(self):
        QtWidgets.QMessageBox.information(
            self, "About",
            "Windows Toolbox — Fluent\n\n"
            "List & reset audio devices, reset audio service, manage firewall ports.\n"
            "Made by: NG. VAN HAN"
        )

    def _update_chip(self):
        admin = is_admin()
        self.chip.setText("Admin: YES" if admin else "Admin: NO")
        self.chip.apply(ok=admin)  # helper method in components
