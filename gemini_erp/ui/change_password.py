"""Change-password dialog.

In forced mode (must_change_password) there is no Cancel: the user either sets a
real password (dialog accepts) or closes it, in which case the caller exits the
app. Either way they cannot reach the main window without changing it.
"""

import logging

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from database import get_session
from services.auth_service import AuthService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)


class ChangePasswordDialog(QDialog):
    def __init__(self, force: bool = False, auth_service: AuthService | None = None, parent=None):
        super().__init__(parent)
        self.auth_service = auth_service or AuthService()
        self._force = force

        self.setWindowTitle("Change Password")
        self.setModal(True)

        self.old_input = QLineEdit()
        self.old_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_input = QLineEdit()
        self.new_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Current Password", self.old_input)
        form.addRow("New Password", self.new_input)
        form.addRow("Confirm New Password", self.confirm_input)

        self.message_label = QLabel(
            "You must set a new password before continuing." if force else ""
        )
        self.message_label.setWordWrap(True)

        self.change_button = QPushButton("Change Password")
        self.change_button.setDefault(True)
        self.change_button.clicked.connect(self.on_change)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.message_label)
        layout.addWidget(self.change_button)

        if not force:
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject)
            layout.addWidget(cancel_button)

        self.setLayout(layout)

    def on_change(self):
        old = self.old_input.text()
        new = self.new_input.text()
        confirm = self.confirm_input.text()

        if new != confirm:
            self.message_label.setText("New password and confirmation do not match.")
            return

        user = SessionContext.get_user()
        session = get_session()
        try:
            ok = self.auth_service.change_password(session, user.id, old, new)
        except ValueError as exc:
            # e.g. password too short — safe message, never contains the password
            self.message_label.setText(str(exc))
            return
        except Exception:
            logger.exception("Change-password error")
            QMessageBox.critical(self, "Change Password", "An error occurred.")
            return
        finally:
            session.close()

        if not ok:
            self.message_label.setText("Current password is incorrect.")
            return

        # Reflect the cleared flag on the in-memory session user.
        if user is not None:
            user.must_change_password = False
        QMessageBox.information(self, "Change Password", "Password changed successfully.")
        self.accept()
