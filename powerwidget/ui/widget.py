"""Small always-on-top window showing the current power draw."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QMouseEvent
from PySide6.QtWidgets import QLabel, QMenu, QMessageBox, QVBoxLayout, QWidget

from ..config import Config
from .. import winsetup
from ..storage import Storage
from . import fmt

STYLE = """
#card { background: rgba(24, 26, 31, 225); border-radius: 12px; border: 1px solid rgba(255,255,255,30); }
QLabel { color: #e8eaed; }
#total { font-size: 30px; font-weight: 600; }
#parts { color: #aab0b8; font-size: 11px; }
#today { color: #aab0b8; font-size: 11px; }
#status { color: #f2b84b; font-size: 10px; }
"""


class PowerWidget(QWidget):
    open_history = Signal()
    open_settings = Signal()
    quit_requested = Signal()
    _setup_done = Signal(bool, str)

    def __init__(self, cfg: Config, storage: Storage, background):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.cfg = cfg
        self.storage = storage
        self.background = background
        self.settings = QSettings("PowerWidget", "PowerWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Power Widget")
        self.setStyleSheet(STYLE)

        card = QWidget(self, objectName="card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(1)
        self.total = QLabel("– W", objectName="total")
        self.parts = QLabel("", objectName="parts")
        self.today = QLabel("", objectName="today")
        self.status = QLabel("", objectName="status")
        for w in (self.total, self.parts, self.today, self.status):
            lay.addWidget(w)
        self.status.hide()
        self.setToolTip("Doppelklick: Verlauf · Rechtsklick: Menü · Ziehen: verschieben")

        self._drag_from: QPoint | None = None
        self.set_on_top(self.settings.value("on_top", True, type=bool))
        pos = self.settings.value("pos")
        if isinstance(pos, QPoint):
            self.move(pos)
        else:
            self.move(40, 40)

        self._timer = QTimer(self, interval=2000, timeout=self.refresh)
        self._timer.start()
        self._today_timer = QTimer(self, interval=30_000, timeout=self.refresh_today)
        self._today_timer.start()
        self._takeover_timer = QTimer(self, interval=30_000, timeout=self.background.try_start)
        self._takeover_timer.start()
        self._setup_done.connect(self._show_setup_result)
        self.refresh()
        self.refresh_today()

    # --- data ---------------------------------------------------------------

    def refresh(self) -> None:
        r = self.storage.latest()
        stale = r is None or time.time() - r.timestamp > max(3 * self.cfg.sample_interval_s, 20)
        if r is None:
            self.total.setText("– W")
            self.parts.setText("Noch keine Messwerte")
        else:
            self.total.setText(fmt.watts(r.total_w))
            parts = [f"CPU {fmt.num(r.cpu_w)}", f"GPU {fmt.num(r.gpu_w)}", f"Rest {fmt.num(r.other_w)}"]
            self.parts.setText("  ·  ".join(parts))
        if stale:
            reason = self.background.error or "Logger läuft nicht"
            when = f" (zuletzt {datetime.fromtimestamp(r.timestamp):%d.%m. %H:%M})" if r else ""
            self._set_status(f"⚠ {reason}{when}")
        elif r.estimated:
            hint = getattr(self.background, "hint", None)
            self._set_status(f"≈ geschätzt – {hint}" if hint else "≈ geschätzt")
        else:
            self._set_status(None)
        self.adjustSize()

    def refresh_today(self) -> None:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        s = self.storage.summary(start, time.time() + 1)
        cost = s.energy_wh / 1000 * self.cfg.price_per_kwh
        self.today.setText(f"Heute {fmt.kwh(s.energy_wh)}  ·  {fmt.money(cost, self.cfg.currency)}")

    def _set_status(self, text: str | None) -> None:
        self.status.setVisible(bool(text))
        self.status.setText(text or "")

    # --- window behaviour ---------------------------------------------------

    def set_on_top(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.settings.setValue("on_top", on)
        self.show()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_from is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self.settings.setValue("pos", self.pos())

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.open_history.emit()

    def contextMenuEvent(self, e) -> None:
        menu = self.build_menu()
        menu.exec(e.globalPos())

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Verlauf und Diagramme…", self.open_history.emit)
        top = QAction("Immer im Vordergrund", menu, checkable=True,
                      checked=bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        top.toggled.connect(self.set_on_top)
        menu.addAction(top)
        menu.addAction("Einstellungen…", self.open_settings.emit)
        if winsetup.available():
            auto = QAction("Mit Windows starten", menu, checkable=True, checked=winsetup.autostart_enabled())
            auto.toggled.connect(self.toggle_autostart)
            menu.addAction(auto)
            from ..sensors.lhm_lib import pawnio_installed
            if not pawnio_installed():
                menu.addAction("CPU-Treiber (PawnIO) installieren…", self.install_driver)
        menu.addAction("Datenordner öffnen", self.open_data_folder)
        menu.addSeparator()
        menu.addAction("Beenden", self.quit_requested.emit)
        return menu

    def toggle_autostart(self, on: bool) -> None:
        ok, msg = winsetup.set_autostart(on)
        if not ok:
            self._show_setup_result(False, f"Automatischer Start konnte nicht geändert werden:\n{msg}")

    def install_driver(self) -> None:
        self._set_status("PawnIO wird installiert…")
        threading.Thread(target=lambda: self._setup_done.emit(*winsetup.install_pawnio()), daemon=True).start()

    def _show_setup_result(self, ok: bool, message: str) -> None:
        self.refresh()
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "Power Widget", message)

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.cfg.db_path).parent)))
