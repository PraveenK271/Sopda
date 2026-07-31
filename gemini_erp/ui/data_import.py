"""Data Import screen (historical track H1).

UI only — it downloads templates, runs validation, shows the report, and (once a
file validates with zero errors) triggers the import. All rules live in
ImportService. Administrator-only tab.
"""

import logging

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services.import_service import IMPORT_DEFS, ImportService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)

_ERROR_COLOR = QColor("#b00020")
_WARNING_COLOR = QColor("#9c6500")

# Friendly titles + the sub-tab order (matches the "order you actually USE it").
_TABS = [
    ("OPENING_STOCK", "Opening Stock"),
    ("OPENING_BALANCES", "Opening Balances"),
    ("PURCHASES", "Purchases"),
    ("SALES", "Sales"),
    ("RECEIPTS", "Receipts"),
    ("PAYMENTS", "Payments"),
]


class _ImportTab(QWidget):
    def __init__(self, import_type: str, service: ImportService):
        super().__init__()
        self.import_type = import_type
        self.service = service
        self._validated_file: str | None = None  # a path that passed with 0 errors

        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Choose an .xlsx file to validate…")
        self.file_input.textChanged.connect(self._invalidate)

        download_btn = QPushButton("Download Template")
        download_btn.clicked.connect(self.on_download_template)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.on_browse)
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self.on_validate)
        self.import_btn = QPushButton("Import")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self.on_import)

        top = QHBoxLayout()
        top.addWidget(download_btn)
        top.addWidget(self.file_input)
        top.addWidget(browse_btn)
        top.addWidget(validate_btn)
        top.addWidget(self.import_btn)

        self.summary_label = QLabel("")

        self.results = QTableWidget()
        self.results.setColumnCount(3)
        self.results.setHorizontalHeaderLabels(["Type", "Row", "Message"])
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.results)
        self.setLayout(layout)

    def _invalidate(self):
        # Any change to the file path voids a prior validation.
        self._validated_file = None
        self.import_btn.setEnabled(False)

    def on_download_template(self):
        default = f"{self.import_type}_template.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save Template", default, "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            self.service.generate_template(self.import_type, path)
        except Exception as exc:
            logger.exception("Template generation failed")
            QMessageBox.critical(self, "Template", f"Could not create the template:\n{exc}")
            return
        QMessageBox.information(self, "Template", f"Template saved:\n{path}")

    def on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", "", "Excel Files (*.xlsx)")
        if path:
            self.file_input.setText(path)

    def on_validate(self):
        path = self.file_input.text().strip()
        if not path:
            QMessageBox.warning(self, "Validate", "Choose a file first.")
            return
        defn = IMPORT_DEFS[self.import_type]
        try:
            rows = self.service.read_sheet(path, defn.column_names())
            report = self.service.validate(rows, self.import_type)
        except Exception as exc:
            # A header/column problem (or unreadable file) — show it as one error.
            self._show_rows([("Error", "-", str(exc))])
            self.summary_label.setText("Validation failed — fix the file and try again.")
            self._invalidate()
            return

        rows_out = [("Error", str(e["row_number"]), e["message"]) for e in report.errors]
        rows_out += [("Warning", str(w["row_number"]), w["message"]) for w in report.warnings]
        self._show_rows(rows_out)
        s = report.summary
        self.summary_label.setText(
            f"Read {s['rows_read']} rows · {s['error_count']} error(s) · {s['warning_count']} warning(s) · "
            + ("READY TO IMPORT" if s["importable"] else "NOT importable — fix the errors")
        )
        if report.is_importable:
            self._validated_file = path
            self.import_btn.setEnabled(True)
        else:
            self._invalidate()

    def _show_rows(self, rows):
        self.results.setRowCount(len(rows))
        for r, (kind, row_no, message) in enumerate(rows):
            color = _ERROR_COLOR if kind == "Error" else _WARNING_COLOR
            for c, text in enumerate((kind, row_no, message)):
                item = QTableWidgetItem(str(text))
                item.setForeground(QBrush(color))
                self.results.setItem(r, c, item)
        if not rows:
            self.results.setRowCount(0)

    def on_import(self):
        path = self.file_input.text().strip()
        if not path or path != self._validated_file:
            QMessageBox.warning(self, "Import", "Validate this exact file (with zero errors) first.")
            return
        confirm = QMessageBox.question(
            self, "Import",
            f"Import {self.import_type} from this file? Back up the database first if you have not.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            log = self.service.import_data(
                self.import_type, path, created_by=SessionContext.get_username()
            )
        except NotImplementedError as exc:
            QMessageBox.information(self, "Import", str(exc))
            return
        except Exception as exc:
            logger.exception("Import failed")
            QMessageBox.critical(self, "Import", f"Import stopped:\n{exc}")
            return
        QMessageBox.information(
            self, "Import",
            f"Imported {log.records_created} record(s). Status: {log.status}.",
        )
        self._invalidate()


class DataImportScreen(QWidget):
    """Top-level Data Import screen with one sub-tab per import type."""

    def __init__(self, service: ImportService | None = None):
        super().__init__()
        self.service = service or ImportService()

        warning = QLabel(
            "Historical import — writes to the LIVE database. Validation writes nothing; "
            "Import does. Back up the database before each bulk import."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#9c6500; font-weight:600;")

        tabs = QTabWidget()
        for import_type, title in _TABS:
            tabs.addTab(_ImportTab(import_type, self.service), title)

        layout = QVBoxLayout()
        layout.addWidget(warning)
        layout.addWidget(tabs)
        self.setLayout(layout)

    def refresh(self):
        # Nothing cached to refresh; present for the main-window tab protocol.
        pass
