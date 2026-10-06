"""Settings screen: edit the company profile and back up the database.

UI only — it collects input and shows results. All logic lives in
SettingsService (company profile) and BackupService (backups).

Patch v1.2.0: the "GST returns filed up to" date. It is what turns the
cancel / renumber guards from advice into a control, so it has its own box,
its own Save, and an Administrator check in the service (the Settings tab is
Administrator-only already; the service does not rely on that).
"""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.backup_service import BackupService
from services.session_context import SessionContext
from services.settings_service import SettingsService
from version import APP_VERSION

logger = logging.getLogger(__name__)


class SettingsScreen(QWidget):
    def __init__(
        self,
        settings_service: SettingsService | None = None,
        backup_service: BackupService | None = None,
    ):
        super().__init__()
        self.settings_service = settings_service or SettingsService()
        self.backup_service = backup_service or BackupService()

        self.name_input = QLineEdit()
        self.address_input = QPlainTextEdit()
        self.address_input.setFixedHeight(60)
        self.mobile_input = QLineEdit()
        self.gstin_input = QLineEdit()
        self.state_input = QLineEdit()
        self.bank_name_input = QLineEdit()
        self.bank_account_input = QLineEdit()
        self.bank_ifsc_input = QLineEdit()
        self.bank_branch_input = QLineEdit()
        self.terms_input = QPlainTextEdit()
        self.terms_input.setFixedHeight(80)
        self.terms_input.setPlaceholderText("One term per line")

        self.logo_input = QLineEdit()
        logo_browse = QPushButton("Browse…")
        logo_browse.clicked.connect(self.on_browse_logo)
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_input)
        logo_row.addWidget(logo_browse)

        form = QFormLayout()
        form.addRow("Company Name", self.name_input)
        form.addRow("Address", self.address_input)
        form.addRow("Mobile", self.mobile_input)
        form.addRow("GSTIN", self.gstin_input)
        form.addRow("State", self.state_input)
        form.addRow("Bank Name", self.bank_name_input)
        form.addRow("Bank A/c No", self.bank_account_input)
        form.addRow("Bank IFSC", self.bank_ifsc_input)
        form.addRow("Bank Branch", self.bank_branch_input)
        form.addRow("Terms & Conditions", self.terms_input)
        form.addRow("Logo Path", logo_row)

        self.save_button = QPushButton("Save Company Profile")
        self.save_button.clicked.connect(self.on_save)

        self.backup_button = QPushButton("Backup Now")
        self.backup_button.clicked.connect(self.on_backup)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.backup_button)

        self.status_label = QLabel(
            "Tip: schedule a daily backup (Task Scheduler for SQLite, or a SQL "
            "Server Agent job for MSSQL) — see the README."
        )
        self.status_label.setWordWrap(True)

        # --- GST returns filed up to (v1.2.0) ---
        self.gst_filed_set = QCheckBox("GSTR-1 has been filed up to")
        self.gst_filed_date = QDateEdit(QDate.currentDate())
        self.gst_filed_date.setCalendarPopup(True)
        self.gst_filed_date.setDisplayFormat("dd-MM-yyyy")
        self.gst_filed_date.setMaximumDate(QDate.currentDate())
        self.gst_filed_set.toggled.connect(self.gst_filed_date.setEnabled)
        self.gst_filed_save = QPushButton("Save GST Filing Date")
        self.gst_filed_save.clicked.connect(self.on_save_gst_filed)
        gst_row = QHBoxLayout()
        gst_row.addWidget(self.gst_filed_set)
        gst_row.addWidget(self.gst_filed_date)
        gst_row.addWidget(self.gst_filed_save)
        gst_row.addStretch(1)
        gst_help = QLabel(
            "Set this to the last date for which you have filed GSTR-1. Invoices on or before "
            "this date cannot be cancelled or renumbered. Update it each month after filing."
        )
        gst_help.setWordWrap(True)
        self.gst_filed_prompt = QLabel(
            "Not set yet: cancelling or renumbering an invoice only shows a warning until "
            "this date is set."
        )
        self.gst_filed_prompt.setStyleSheet("color: #8a6d00;")
        self.gst_filed_prompt.setWordWrap(True)
        gst_layout = QVBoxLayout()
        gst_layout.addLayout(gst_row)
        gst_layout.addWidget(gst_help)
        gst_layout.addWidget(self.gst_filed_prompt)
        gst_box = QGroupBox("GST returns")
        gst_box.setLayout(gst_layout)

        self.version_label = QLabel(f"Gemini ERP version {APP_VERSION}")
        self.version_label.setStyleSheet("color: #555;")

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(gst_box)
        layout.addWidget(self.status_label)
        layout.addWidget(self.version_label)
        self.setLayout(layout)

        self.refresh()

    def refresh(self):
        """Load the current company profile into the form."""
        try:
            profile = self.settings_service.get_profile()
        except Exception:
            logger.exception("Failed to load company profile")
            QMessageBox.critical(self, "Settings", "Could not load company profile.")
            return
        self.name_input.setText(profile["name"] or "")
        self.address_input.setPlainText(profile["address"] or "")
        self.mobile_input.setText(profile["mobile"] or "")
        self.gstin_input.setText(profile["gstin"] or "")
        self.state_input.setText(profile["state"] or "")
        self.bank_name_input.setText(profile["bank_name"] or "")
        self.bank_account_input.setText(profile["bank_account_no"] or "")
        self.bank_ifsc_input.setText(profile["bank_ifsc"] or "")
        self.bank_branch_input.setText(profile["bank_branch"] or "")
        self.terms_input.setPlainText("\n".join(profile["terms"]))
        self.logo_input.setText(profile["logo_path"] or "")

        filed = profile["gst_filed_upto_date"]
        self.gst_filed_set.setChecked(filed is not None)
        self.gst_filed_date.setEnabled(filed is not None)
        if filed is not None:
            self.gst_filed_date.setDate(QDate(filed.year, filed.month, filed.day))
        self.gst_filed_prompt.setVisible(filed is None)

    def on_browse_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.logo_input.setText(path)

    def on_save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Settings", "Company Name is required.")
            return
        data = {
            "name": name,
            "address": self.address_input.toPlainText().strip(),
            "mobile": self.mobile_input.text().strip(),
            "gstin": self.gstin_input.text().strip(),
            "state": self.state_input.text().strip(),
            "bank_name": self.bank_name_input.text().strip(),
            "bank_account_no": self.bank_account_input.text().strip(),
            "bank_ifsc": self.bank_ifsc_input.text().strip(),
            "bank_branch": self.bank_branch_input.text().strip(),
            "terms": [
                line.strip()
                for line in self.terms_input.toPlainText().splitlines()
                if line.strip()
            ],
            "logo_path": self.logo_input.text().strip() or None,
        }
        try:
            self.settings_service.update_profile(data)
        except Exception:
            logger.exception("Failed to save company profile")
            QMessageBox.critical(self, "Settings", "Could not save the company profile.")
            return
        self.status_label.setText("Company profile saved.")
        QMessageBox.information(self, "Settings", "Company profile saved.")

    def on_save_gst_filed(self):
        value = self.gst_filed_date.date().toPython() if self.gst_filed_set.isChecked() else None
        if value is None:
            answer = QMessageBox.question(
                self, "Clear GST filing date",
                "Clear the GST filing date? Cancelling or renumbering invoices in filed "
                "periods will then only show a warning.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.settings_service.set_gst_filed_upto_date(value, SessionContext.get_username())
        except Exception as exc:
            logger.exception("Failed to save the GST filed-up-to date")
            QMessageBox.critical(self, "Settings", f"Could not save the GST filing date:\n{exc}")
            return
        self.gst_filed_prompt.setVisible(value is None)
        message = (f"GST returns marked as filed up to {value:%d-%m-%Y}." if value
                   else "GST filing date cleared.")
        self.status_label.setText(message)
        QMessageBox.information(self, "Settings", message)

    def on_backup(self):
        self.backup_button.setEnabled(False)
        try:
            path = self.backup_service.backup()
        except Exception as exc:
            logger.exception("Backup failed")
            QMessageBox.critical(self, "Backup", f"Backup failed:\n{exc}")
            return
        finally:
            self.backup_button.setEnabled(True)
        self.status_label.setText(f"Backup created: {path}")
        QMessageBox.information(self, "Backup", f"Backup created:\n{path}")
