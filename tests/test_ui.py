import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

from powerwidget.config import Config  # noqa: E402
from powerwidget.sensors.base import PowerReading  # noqa: E402
from powerwidget.storage import Storage  # noqa: E402


class NoLogger:
    error = None

    def try_start(self):
        return False


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_widget_and_history_render(app, tmp_path, monkeypatch):
    from powerwidget.ui.history import RANGES, HistoryWindow
    from powerwidget.ui.widget import PowerWidget

    monkeypatch.setattr("powerwidget.ui.widget.QSettings", lambda *a: _MemSettings())
    cfg = Config(db_path=str(tmp_path / "p.db"))
    st = Storage(cfg.db_path)
    now = time.time()
    for i in range(200):
        st.insert(PowerReading(now - 1000 + i * 5, 150.0, 60.0, 50.0, 40.0, False, {"cpu": "lhm"}), 5)
    w = PowerWidget(cfg, st, NoLogger())
    assert w.total.text() == "150 W"
    assert not w.status.isVisible() or "Logger" not in w.status.text()
    h = HistoryWindow(cfg, st)
    for i in range(len(RANGES)):
        h.set_range(i)
        for tab in range(3):
            h.tabs.setCurrentIndex(tab)
    h.set_range(0)
    assert h.c_avg.value.text() == "150 W"
    assert len(h.points) > 0
    st.close()


class _MemSettings(dict):
    def value(self, key, default=None, type=None):
        return self.get(key, default)

    def setValue(self, key, value):
        self[key] = value


def test_settings_dialog_saves_price(app, tmp_path, monkeypatch):
    from powerwidget import config
    from powerwidget.ui.settings import SettingsDialog

    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    cfg = Config(db_path=str(tmp_path / "p.db"))
    d = SettingsDialog(cfg)
    d.price.setValue(0.4123)
    d.currency.setText("CHF")
    d.accept()
    assert Config.load(tmp_path / "config.toml").price_per_kwh == 0.4123
    assert cfg.currency == "CHF"
