"""Credit Notes Received from suppliers (patch v1.1.0, P4) — under Purchases.

UI only: collects the note, shows CreditNoteService's warnings for
confirmation, lists recorded notes with their IMS status, and exports the
register. Validation and the journal entry live in the service.
"""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reports.credit_note_register import export_excel, export_pdf
from services.credit_note_service import (
    IMS_STATUSES,
    NOTE_TYPE_COMMERCIAL,
    NOTE_TYPE_GST,
    CreditNoteService,
)
from services.purchase_service import PurchaseService
from services.session_context import SessionContext
from services.supplier_service import SupplierService

logger = logging.getLogger(__name__)

TYPE_HELP = {
    NOTE_TYPE_GST: (
        "GST credit note — the note shows GST. It reduces the original bill's value AND its "
        "tax, so the input tax credit (ITC) on it is reversed."
    ),
    NOTE_TYPE_COMMERCIAL: (
        "Commercial credit note — the note shows NO GST (a financial discount). No ITC is "
        "reversed and no GST ledger is touched."
    ),
}

REASON_LABELS = [
    ("DISCOUNT", "Discount"),
    ("RATE_DIFFERENCE", "Rate difference"),
    ("QUALITY_CLAIM", "Quality claim"),
    ("SCHEME", "Scheme / incentive"),
    ("GOODS_RETURN", "Goods returned (use Purchase Return)"),
]


class ImsStatusDialog(QDialog):
    """Record the IMS action taken on the GST portal for one note."""

    def __init__(self, note: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Update IMS status — {note['credit_note_no']}")
        self.status_combo = QComboBox()
        self.status_combo.addItems(IMS_STATUSES)
        self.status_combo.setCurrentText(note["ims_status"])
        self.itc_checkbox = QCheckBox("ITC reversed (declared on IMS)")
        self.itc_checkbox.setChecked(note["itc_reversed"])
        self.amount_input = QLineEdit(f"{note['itc_reversal_amount']:.2f}" if note["itc_reversal_amount"] else "")
        self.amount_input.setPlaceholderText(f"blank = full GST ({note['gst_total']:.2f})")
        if note["note_type"] == NOTE_TYPE_COMMERCIAL:
            self.itc_checkbox.setEnabled(False)
            self.amount_input.setEnabled(False)
            self.amount_input.setPlaceholderText("no GST on a commercial note")

        form = QFormLayout()
        form.addRow("IMS status", self.status_combo)
        form.addRow(self.itc_checkbox)
        form.addRow("ITC reversal amount", self.amount_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)


class CreditNotesScreen(QWidget):
    COLUMNS = [
        "Date", "Supplier", "Note No", "Type", "Reason", "Against Invoice",
        "Taxable", "GST", "Total", "IMS Status", "ITC Reversed", "Declare By", "Flag",
    ]
    FILTERS = [("All notes", {}), ("Pending in IMS", {"pending_only": True}),
               ("Pending & near/past 30 Nov cut-off", {"deadline_only": True})]

    def __init__(
        self,
        credit_note_service: CreditNoteService | None = None,
        supplier_service: SupplierService | None = None,
        purchase_service: PurchaseService | None = None,
    ):
        super().__init__()
        self.service = credit_note_service or CreditNoteService()
        self.supplier_service = supplier_service or SupplierService()
        self.purchase_service = purchase_service or PurchaseService()
        self.notes: list[dict] = []
        self._build_ui()
        self.refresh()

    # ----- layout ------------------------------------------------------------

    def _build_ui(self):
        # Type selector first and prominent: it decides the books. No default.
        self.gst_radio = QRadioButton("GST credit note")
        self.commercial_radio = QRadioButton("Commercial credit note (no GST)")
        self.type_group = QButtonGroup(self)
        self.type_group.addButton(self.gst_radio)
        self.type_group.addButton(self.commercial_radio)
        self.type_group.buttonToggled.connect(self._on_type_changed)
        self.type_help = QLabel("Choose the type shown on the supplier's note.")
        self.type_help.setWordWrap(True)
        type_row = QHBoxLayout()
        type_row.addWidget(self.gst_radio)
        type_row.addWidget(self.commercial_radio)
        type_row.addStretch(1)
        type_layout = QVBoxLayout()
        type_layout.addLayout(type_row)
        type_layout.addWidget(self.type_help)
        type_box = QGroupBox("1. Credit note type")
        type_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        type_box.setLayout(type_layout)

        self.supplier_combo = QComboBox()
        self.supplier_combo.currentIndexChanged.connect(self._refresh_linked_invoices)
        self.note_no_input = QLineEdit()
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.reason_combo = QComboBox()
        for code, label in REASON_LABELS:
            self.reason_combo.addItem(label, code)
        self.linked_combo = QComboBox()
        self.taxable_input = QLineEdit()
        self.cgst_input = QLineEdit()
        self.sgst_input = QLineEdit()
        self.igst_input = QLineEdit()
        self.total_input = QLineEdit()
        self.notes_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Supplier", self.supplier_combo)
        form.addRow("Supplier's Credit Note No", self.note_no_input)
        form.addRow("Credit Note Date", self.date_input)
        form.addRow("Reason", self.reason_combo)
        form.addRow("Against Purchase Invoice", self.linked_combo)
        form.addRow("Taxable Value", self.taxable_input)
        form.addRow("CGST", self.cgst_input)
        form.addRow("SGST", self.sgst_input)
        form.addRow("IGST", self.igst_input)
        form.addRow("Total Amount", self.total_input)
        form.addRow("Notes", self.notes_input)
        self.save_button = QPushButton("Save Credit Note")
        self.save_button.clicked.connect(self.on_save)
        entry_layout = QVBoxLayout()
        entry_layout.addLayout(form)
        entry_layout.addWidget(QLabel(
            "Discounts only — this does not change stock. Goods sent back go through Purchase Return."
        ))
        entry_layout.addWidget(self.save_button)
        entry_box = QGroupBox("2. Credit note details")
        entry_box.setLayout(entry_layout)

        self.filter_combo = QComboBox()
        for label, _kwargs in self.FILTERS:
            self.filter_combo.addItem(label)
        self.filter_combo.currentIndexChanged.connect(self.refresh_list)
        self.ims_button = QPushButton("Update IMS status")
        self.ims_button.clicked.connect(self.on_update_ims)
        self.excel_button = QPushButton("Export Register (Excel)")
        self.excel_button.clicked.connect(lambda: self.on_export("xlsx"))
        self.pdf_button = QPushButton("Export Register (PDF)")
        self.pdf_button.clicked.connect(lambda: self.on_export("pdf"))
        list_bar = QHBoxLayout()
        list_bar.addWidget(QLabel("Show"))
        list_bar.addWidget(self.filter_combo)
        list_bar.addStretch(1)
        list_bar.addWidget(self.ims_button)
        list_bar.addWidget(self.excel_button)
        list_bar.addWidget(self.pdf_button)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        list_layout = QVBoxLayout()
        list_layout.addLayout(list_bar)
        list_layout.addWidget(self.table)
        list_box = QGroupBox("Credit Notes Received Register")
        list_box.setLayout(list_layout)

        layout = QVBoxLayout()
        layout.addWidget(type_box)
        layout.addWidget(entry_box)
        layout.addWidget(list_box, 1)
        self.setLayout(layout)
        self._set_gst_fields_enabled(False)

    def _selected_type(self) -> str | None:
        if self.gst_radio.isChecked():
            return NOTE_TYPE_GST
        if self.commercial_radio.isChecked():
            return NOTE_TYPE_COMMERCIAL
        return None

    def _on_type_changed(self, *_args):
        note_type = self._selected_type()
        self.type_help.setText(TYPE_HELP.get(note_type, "Choose the type shown on the supplier's note."))
        self._set_gst_fields_enabled(note_type == NOTE_TYPE_GST)

    def _set_gst_fields_enabled(self, enabled: bool):
        for field in (self.taxable_input, self.cgst_input, self.sgst_input, self.igst_input):
            field.setEnabled(enabled)
            if not enabled:
                field.clear()

    # ----- data --------------------------------------------------------------

    def refresh(self):
        current = self.supplier_combo.currentData()
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("— select supplier —", None)
        for supplier in self.supplier_service.list_suppliers():
            self.supplier_combo.addItem(f"{supplier['name']} ({supplier['state']})", supplier["id"])
            if supplier["id"] == current:
                self.supplier_combo.setCurrentIndex(self.supplier_combo.count() - 1)
        self.supplier_combo.blockSignals(False)
        self._refresh_linked_invoices()
        self.refresh_list()

    def _refresh_linked_invoices(self):
        supplier_id = self.supplier_combo.currentData()
        self.linked_combo.clear()
        self.linked_combo.addItem("— not against a specific invoice —", None)
        if supplier_id is None:
            return
        for inv in self.purchase_service.list_purchase_invoices():
            if inv["supplier_id"] == supplier_id:
                self.linked_combo.addItem(
                    f"{inv['invoice_no']}  ({inv['date'].strftime('%d-%m-%Y')}, {inv['total']:.2f})",
                    inv["id"],
                )

    def refresh_list(self):
        _label, kwargs = self.FILTERS[max(self.filter_combo.currentIndex(), 0)]
        self.notes = self.service.list_credit_notes(**kwargs)
        self.table.setRowCount(len(self.notes))
        for row, n in enumerate(self.notes):
            flag = ""
            if n["needs_attention"]:
                flag = "Cut-off passed" if n["deadline_status"] == "PASSED" else "Cut-off near"
            values = [
                n["credit_note_date"].strftime("%d-%m-%Y"), n["supplier_name"], n["credit_note_no"],
                n["note_type"], n["reason"], n["linked_invoice_no"] or "",
                f"{n['taxable_value']:.2f}", f"{n['gst_total']:.2f}", f"{n['total_amount']:.2f}",
                n["ims_status"], f"{n['itc_reversal_amount']:.2f}" if n["itc_reversed"] else "",
                n["declaration_deadline"].strftime("%d-%m-%Y") if n["declaration_deadline"] else "",
                flag,
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    # ----- actions -----------------------------------------------------------

    def _form_data(self) -> dict:
        return {
            "note_type": self._selected_type(),
            "supplier_id": self.supplier_combo.currentData(),
            "credit_note_no": self.note_no_input.text(),
            "credit_note_date": self.date_input.date().toPython(),
            "reason": self.reason_combo.currentData(),
            "linked_purchase_invoice_id": self.linked_combo.currentData(),
            "taxable_value": self.taxable_input.text(),
            "cgst": self.cgst_input.text(),
            "sgst": self.sgst_input.text(),
            "igst": self.igst_input.text(),
            "total_amount": self.total_input.text(),
            "notes": self.notes_input.text(),
        }

    def on_save(self):
        data = self._form_data()
        try:
            warnings = self.service.validate(data)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save credit note", str(exc))
            return
        if warnings:
            answer = QMessageBox.question(
                self, "Please confirm",
                "\n\n".join(f"• {w}" for w in warnings) + "\n\nSave anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            note = self.service.create_credit_note(data, created_by=SessionContext.get_username())
        except Exception as exc:
            logger.exception("Failed to save credit note")
            QMessageBox.critical(self, "Error", f"Could not save credit note:\n{exc}")
            return
        QMessageBox.information(
            self, "Saved", f"{note.note_type.title()} credit note {note.credit_note_no} recorded."
        )
        for field in (self.note_no_input, self.taxable_input, self.cgst_input, self.sgst_input,
                      self.igst_input, self.total_input, self.notes_input):
            field.clear()
        self.refresh_list()

    def on_update_ims(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.notes):
            QMessageBox.warning(self, "No selection", "Select a credit note in the list first.")
            return
        note = self.notes[row]
        dialog = ImsStatusDialog(note, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update_ims_status(
                note["id"], dialog.status_combo.currentText(), dialog.itc_checkbox.isChecked(),
                dialog.amount_input.text(), modified_by=SessionContext.get_username(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Cannot update", str(exc))
            return
        self.refresh_list()

    def on_export(self, kind: str):
        label = self.filter_combo.currentText()
        default = f"credit_notes_register.{kind}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export register", default,
            "Excel Files (*.xlsx)" if kind == "xlsx" else "PDF Files (*.pdf)",
        )
        if not path:
            return
        title = f"Credit Notes Received Register — {label}"
        try:
            (export_excel if kind == "xlsx" else export_pdf)(self.notes, path, title)
        except Exception as exc:
            logger.exception("Failed to export credit note register")
            QMessageBox.critical(self, "Error", f"Could not export:\n{exc}")
            return
        QMessageBox.information(self, "Exported", f"Register saved to:\n{path}")
