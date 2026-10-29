"""PyInstaller entry point: PowerWidget.exe opens the widget; other commands still work
(PowerWidget.exe probe, ...), though a windowed exe shows no console output."""

import sys

from powerwidget.cli import main

if __name__ == "__main__":
    sys.exit(main())
