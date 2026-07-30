"""Settings screen: edit the company profile and back up the database.

UI only — it collects input and shows results. All logic lives in
SettingsService (company profile) and BackupService (backups).
"""

import logging

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
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
from services.settings_service import SettingsService

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

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
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
