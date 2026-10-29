"""Settings dialog for the cost display."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit

from ..config import Config


class SettingsDialog(QDialog):
    KEYS = ["price_per_kwh", "currency"]

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Power Widget – Einstellungen")
        self.setMinimumWidth(340)
        form = QFormLayout(self)

        self.currency = QLineEdit(cfg.currency)
        self.currency.setMaxLength(5)
        self.price = QDoubleSpinBox(decimals=4, minimum=0.0, maximum=10.0, singleStep=0.01)
        self.price.setValue(cfg.price_per_kwh)
        self.currency.textChanged.connect(self._update_suffix)
        self._update_suffix()
        form.addRow("Strompreis:", self.price)
        form.addRow("Währung:", self.currency)
        hint = QLabel("Der Preis gilt für alle Kostenangaben, auch für zurückliegende Zeiträume.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_suffix(self) -> None:
        self.price.setSuffix(f" {self.currency.text().strip() or '€'}/kWh")

    def accept(self) -> None:
        self.cfg.price_per_kwh = round(self.price.value(), 4)
        self.cfg.currency = self.currency.text().strip() or "€"
        self.cfg.save(self.KEYS)
        super().accept()
