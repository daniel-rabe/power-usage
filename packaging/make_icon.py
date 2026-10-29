"""Write the app icon (the same bolt the tray uses) to an .ico file for PyInstaller."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from powerwidget.ui.app import make_icon

app = QApplication([])
pixmap = make_icon().pixmap(256, 256)
if not pixmap.save(sys.argv[1], "ICO"):
    raise SystemExit("Qt could not write the .ico file")
