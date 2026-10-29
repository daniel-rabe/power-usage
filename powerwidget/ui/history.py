"""History window: power chart, energy bars, raw samples and CSV export."""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QTableView, QTabWidget, QVBoxLayout, QWidget)

from ..config import Config
from ..storage import Storage
from . import fmt

TOTAL, CPU, GPU = "#2a78d6", "#e8743b", "#3aa66b"
HOUR, DAY = 3600, 86400


@dataclass(frozen=True)
class Range:
    label: str
    span_s: int
    line_bin_s: int       # averaging for the power chart
    bar: str              # "5min", "hour" or "day" energy bars


RANGES = [
    Range("1 Std", HOUR, 5, "5min"),
    Range("24 Std", DAY, 60, "hour"),
    Range("7 Tage", 7 * DAY, 600, "day"),
    Range("30 Tage", 30 * DAY, HOUR, "day"),
    Range("1 Jahr", 365 * DAY, 6 * HOUR, "day"),
]


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


class SamplesModel(QAbstractTableModel):
    HEADERS = ["Zeit", "Gesamt (W)", "CPU (W)", "GPU (W)", "Rest (W)", "Geschätzt", "Quelle"]

    def __init__(self):
        super().__init__()
        self.rows: list[tuple] = []

    def set_rows(self, rows: list[tuple]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        col = index.column()
        if role == Qt.ItemDataRole.TextAlignmentRole and 1 <= col <= 4:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        ts, total, cpu, gpu, other, est, source = self.rows[index.row()]
        if col == 0:
            return f"{datetime.fromtimestamp(ts):%d.%m.%Y %H:%M:%S}"
        if 1 <= col <= 4:
            return fmt.num((total, cpu, gpu, other)[col - 1], 1)
        return ("ja" if est else "") if col == 5 else source


class StatCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        t = QLabel(title)
        t.setStyleSheet("color: gray; font-size: 11px;")
        self.value = QLabel("–")
        self.value.setStyleSheet("font-size: 18px; font-weight: 600;")
        lay.addWidget(t)
        lay.addWidget(self.value)


class HistoryWindow(QWidget):
    def __init__(self, cfg: Config, storage: Storage):
        super().__init__()
        self.cfg = cfg
        self.storage = storage
        self.range = RANGES[1]
        self.points = []
        self.setWindowTitle("Power Widget – Verlauf")
        self.resize(980, 640)

        dark = _is_dark(self)
        pg.setConfigOptions(antialias=True, background=None, foreground="#c8ccd2" if dark else "#3c4043")

        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.range_buttons = QButtonGroup(self)
        for i, r in enumerate(RANGES):
            b = QPushButton(r.label, checkable=True)
            b.setChecked(r is self.range)
            self.range_buttons.addButton(b, i)
            bar.addWidget(b)
        self.range_buttons.idClicked.connect(self.set_range)
        bar.addStretch()
        refresh = QPushButton("Aktualisieren")
        refresh.clicked.connect(self.reload)
        self.settings_button = QPushButton("Strompreis…")
        bar.addWidget(self.settings_button)
        export = QPushButton("CSV exportieren…")
        export.clicked.connect(self.export_csv)
        bar.addWidget(refresh)
        bar.addWidget(export)
        root.addLayout(bar)

        cards = QGridLayout()
        self.c_energy, self.c_cost = StatCard("Verbrauch"), StatCard("Kosten")
        self.c_avg, self.c_max = StatCard("Ø Leistung"), StatCard("Spitze")
        self.c_on, self.c_est = StatCard("Aufgezeichnet"), StatCard("Geschätzte Werte")
        for i, c in enumerate((self.c_energy, self.c_cost, self.c_avg, self.c_max, self.c_on, self.c_est)):
            cards.addWidget(c, 0, i)
        root.addLayout(cards)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # Power over time
        self.power_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.power_plot.getAxis("left").enableAutoSIPrefix(False)
        self.power_plot.setLabel("left", "Leistung (W)")
        self.power_plot.showGrid(x=False, y=True, alpha=0.2)
        self.power_plot.addLegend(offset=(10, 5))
        self.power_plot.setMouseEnabled(x=True, y=False)
        self.curve_total = self.power_plot.plot(name="Gesamt", pen=pg.mkPen(TOTAL, width=2), connect="finite")
        self.curve_cpu = self.power_plot.plot(name="CPU", pen=pg.mkPen(CPU, width=1.5), connect="finite")
        self.curve_gpu = self.power_plot.plot(name="GPU", pen=pg.mkPen(GPU, width=1.5), connect="finite")
        self.hover = pg.TextItem(anchor=(0, 1), color="#c8ccd2" if dark else "#3c4043")
        self.power_plot.addItem(self.hover, ignoreBounds=True)
        self.power_plot.scene().sigMouseMoved.connect(self._on_hover)
        self.tabs.addTab(self.power_plot, "Leistung")

        # Energy per period
        self.energy_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.energy_plot.getAxis("left").enableAutoSIPrefix(False)
        self.energy_plot.showGrid(x=False, y=True, alpha=0.2)
        self.energy_plot.setMouseEnabled(x=False, y=False)
        self.bars = None
        self.tabs.addTab(self.energy_plot, "Verbrauch")

        # Raw samples
        self.samples = SamplesModel()
        self.table = QTableView()
        self.table.setModel(self.samples)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((150, 90, 80, 80, 80, 80)):
            self.table.setColumnWidth(col, width)
        self.table_note = QLabel()
        self.table_note.setStyleSheet("color: gray;")
        samples = QWidget()
        sl = QVBoxLayout(samples)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.table)
        sl.addWidget(self.table_note)
        self.tabs.addTab(samples, "Messwerte")
        self.tabs.currentChanged.connect(lambda _: self._fill_table())

        self._auto = QTimer(self, interval=10_000, timeout=self._auto_reload)
        self._auto.start()
        self.reload()

    # --- loading ------------------------------------------------------------

    def set_range(self, index: int) -> None:
        self.range = RANGES[index]
        self.range_buttons.button(index).setChecked(True)
        self.reload()

    def _auto_reload(self) -> None:
        if self.isVisible() and self.range.span_s <= DAY:
            self.reload()

    def reload(self) -> None:
        end = time.time() + 1
        start = end - self.range.span_s
        self.start, self.end = start, end
        s = self.storage.summary(start, end)
        self.c_energy.value.setText(fmt.kwh(s.energy_wh))
        self.c_cost.value.setText(fmt.money(s.energy_wh / 1000 * self.cfg.price_per_kwh, self.cfg.currency))
        self.c_avg.value.setText(fmt.watts(s.avg_w))
        self.c_max.value.setText(fmt.watts(s.max_w))
        self.c_on.value.setText(fmt.duration(s.covered_s))
        self.c_est.value.setText(f"{fmt.num(s.estimated_fraction * 100)} %")

        self.points = self.storage.series(start, end, self.range.line_bin_s)
        b = self.range.line_bin_s
        self.curve_total.setData(*self._component(b, "avg_w"))
        self.curve_cpu.setData(*self._component(b, "cpu_w"))
        self.curve_gpu.setData(*self._component(b, "gpu_w"))
        self.power_plot.setXRange(start, end, padding=0)
        self.power_plot.setYRange(0, max([p.max_w for p in self.points] + [50]) * 1.05, padding=0)

        self._fill_energy(start, end)
        self._fill_table()

    def _component(self, bin_s, attr):
        xs, ys, prev = [], [], None
        for p in self.points:
            v = getattr(p, attr)
            if prev is not None and p.ts - prev > 2.5 * bin_s:
                xs.append(prev + bin_s)
                ys.append(math.nan)
            xs.append(p.ts)
            ys.append(math.nan if v is None else v)
            prev = p.ts
        return xs, ys

    def _fill_energy(self, start: float, end: float) -> None:
        if self.bars is not None:
            self.energy_plot.removeItem(self.bars)
        if self.range.bar == "day":
            rows = [(datetime.combine(d, datetime.min.time()).timestamp() + DAY / 2, wh)
                    for d, wh in self.storage.energy_by_day(start, end)]
            width = DAY * 0.8
        else:
            size = 300 if self.range.bar == "5min" else HOUR
            rows = [(p.ts + size / 2, p.energy_wh) for p in self.storage.series(start, end, size)]
            width = size * 0.8
        # Daily bars in kWh, shorter periods in Wh so the axis stays readable.
        scale, unit_label = (1000, "kWh") if self.range.bar == "day" else (1, "Wh")
        heights = [r[1] / scale for r in rows]
        self.bars = pg.BarGraphItem(x=[r[0] for r in rows], height=heights, width=width,
                                    brush=QColor(TOTAL), pen=pg.mkPen(None))
        self.energy_plot.addItem(self.bars)
        self.energy_plot.setLabel("left", f"Verbrauch ({unit_label})")
        self.energy_plot.setXRange(start, end, padding=0.01)
        self.energy_plot.setYRange(0, max(heights + [0.01]) * 1.1, padding=0)
        unit = {"5min": "5 Minuten", "hour": "Stunde", "day": "Tag"}[self.range.bar]
        self.tabs.setTabText(1, f"Verbrauch pro {unit}")

    def _fill_table(self) -> None:
        if self.tabs.currentIndex() != 2:
            return
        limit = 2000
        rows = self.storage.recent(self.start, self.end, limit)
        self.samples.set_rows(rows)
        note = f"Neueste {len(rows)} Einzelwerte (alle {fmt.num(self.cfg.sample_interval_s)} s). "
        note += f"Einzelwerte werden {self.cfg.raw_retention_days} Tage aufbewahrt, danach nur Mittelwerte."
        self.table_note.setText(note)

    def _on_hover(self, pos) -> None:
        vb = self.power_plot.getPlotItem().vb
        if not self.points or not self.power_plot.sceneBoundingRect().contains(pos):
            self.hover.setText("")
            return
        x = vb.mapSceneToView(pos).x()
        p = min(self.points, key=lambda p: abs(p.ts - x))
        if abs(p.ts - x) > 3 * self.range.line_bin_s:
            self.hover.setText("")
            return
        text = f"{datetime.fromtimestamp(p.ts):%d.%m. %H:%M}\nGesamt {fmt.watts(p.avg_w)}"
        if p.cpu_w is not None:
            text += f"\nCPU {fmt.watts(p.cpu_w)}"
        if p.gpu_w is not None:
            text += f"\nGPU {fmt.watts(p.gpu_w)}"
        self.hover.setText(text)
        self.hover.setPos(p.ts, p.avg_w)

    # --- export ---------------------------------------------------------------

    def export_csv(self) -> None:
        name = f"stromverbrauch_{datetime.now():%Y-%m-%d}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren", name, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Zeit", "Ø Leistung (W)", "Min (W)", "Max (W)", "CPU (W)", "GPU (W)", "Verbrauch (kWh)"])
            for p in self.points:
                w.writerow([f"{datetime.fromtimestamp(p.ts):%d.%m.%Y %H:%M:%S}", fmt.num(p.avg_w, 1).replace(".", ""),
                            fmt.num(p.min_w, 1).replace(".", ""), fmt.num(p.max_w, 1).replace(".", ""),
                            "" if p.cpu_w is None else fmt.num(p.cpu_w, 1).replace(".", ""),
                            "" if p.gpu_w is None else fmt.num(p.gpu_w, 1).replace(".", ""),
                            fmt.num(p.energy_wh / 1000, 5).replace(".", "")])
        QMessageBox.information(self, "Export", f"{len(self.points)} Zeilen gespeichert:\n{path}")
