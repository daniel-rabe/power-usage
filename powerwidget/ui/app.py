"""Start the widget: logging thread, floating window, tray icon, history window."""

from __future__ import annotations

import locale
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import Config
from ..lock import InstanceLock
from ..storage import Storage
from .background import BackgroundLogger


def make_icon() -> QIcon:
    """A lightning bolt, drawn so we don't have to ship image files."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#2a78d6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    p.setBrush(QColor("#ffd34d"))
    bolt = [(36, 6), (14, 36), (30, 36), (26, 58), (50, 26), (34, 26), (40, 6)]
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in bolt]))
    p.end()
    return QIcon(pm)


def run(cfg: Config) -> int:
    from .history import HistoryWindow
    from .widget import PowerWidget

    try:
        locale.setlocale(locale.LC_TIME, "")  # month and weekday names on chart axes in the user's language
    except locale.Error:
        pass
    # One widget at a time: a second start (e.g. autostart plus a double-click) just exits.
    single = InstanceLock(cfg.db_path + ".widget.lock")
    if not single.acquire():
        return 0
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Power Widget")
    app.setQuitOnLastWindowClosed(False)
    icon = make_icon()
    app.setWindowIcon(icon)

    background = BackgroundLogger(cfg)
    background.try_start()
    storage = Storage(cfg.db_path, cfg.raw_retention_days, cfg.minute_retention_days)

    widget = PowerWidget(cfg, storage, background)
    history: list[HistoryWindow] = []

    def show_history() -> None:
        if not history:
            history.append(HistoryWindow(cfg, storage))
            history[0].settings_button.clicked.connect(show_settings)
        w = history[0]
        w.reload()
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def toggle_widget() -> None:
        widget.setVisible(not widget.isVisible())

    def show_settings() -> None:
        from .settings import SettingsDialog
        if SettingsDialog(cfg).exec():
            widget.refresh_today()
            if history:
                history[0].reload()

    widget.open_history.connect(show_history)
    widget.open_settings.connect(show_settings)
    widget.quit_requested.connect(app.quit)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip("Power Widget")
        menu = QMenu()
        menu.addAction("Widget ein-/ausblenden", toggle_widget)
        menu.addAction("Verlauf und Diagramme…", show_history)
        menu.addAction("Einstellungen…", show_settings)
        menu.addSeparator()
        menu.addAction("Beenden", app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: show_history() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        tray.show()

    widget.show()
    try:
        return app.exec()
    finally:
        background.stop()
        storage.close()
        single.release()
