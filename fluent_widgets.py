from PySide6 import QtCore, QtGui, QtWidgets

class FluentButton(QtWidgets.QPushButton):
    def __init__(self, text="", icon: QtGui.QIcon | None = None, *args, **kwargs):
        if icon:
            super().__init__(icon, text, *args, **kwargs)
        else:
            super().__init__(text, *args, **kwargs)
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

class LogBox(QtWidgets.QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(255,255,255,0.7);
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 12px;
                padding: 10px;
                font: 10.5pt "Consolas";
            }
        """)
        self._last_line = None  # store last printed line

    def append_line(self, text: str):
        if text == self._last_line:
            return  # skip duplicate
        self._last_line = text
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())