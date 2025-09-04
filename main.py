# main.py
import sys
from PySide6 import QtCore, QtGui, QtWidgets

from main_window import MainWindow
from core.utils import IS_WINDOWS, ensure_admin_elevated

def main():
    # High DPI & crisp icons
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationDisplayName("")
    app.setFont(QtGui.QFont("Segoe UI", 10))

    # Optional: auto elevation (same behavior you had)
    if IS_WINDOWS:
        if not ensure_admin_elevated():
            # Non-admin instance exits after relaunch attempt
            return

    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
