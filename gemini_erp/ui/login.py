"""Login dialog shown before the main window.

UI only — it collects credentials and calls AuthService. It never reveals
whether a username exists (same message for wrong-user and wrong-password) and
applies a small brute-force slowdown after repeated failures.
"""

import logging

from PySide6.QtCore import Qt, QTimer
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

_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 30


class LoginDialog(QDialog):
    def __init__(self, auth_service: AuthService | None = None, parent=None):
        super().__init__(parent)
        self.auth_service = auth_service or AuthService()
        self._failed_attempts = 0

        self.setWindowTitle("Gemini ERP — Login")
        self.setModal(True)

        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Username", self.username_input)
        form.addRow("Password", self.password_input)

        self.login_button = QPushButton("Login")
        self.login_button.setDefault(True)  # Enter submits
        self.login_button.clicked.connect(self.on_login)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #b00020;")

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.message_label)
        layout.addWidget(self.login_button)
        layout.addWidget(self.cancel_button)
        self.setLayout(layout)

    def on_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        session = get_session()
        try:
            user = self.auth_service.authenticate(session, username, password)
        except Exception:
            logger.exception("Login error")
            QMessageBox.critical(self, "Login", "An error occurred during login.")
            return
        finally:
            session.close()

        if user is not None:
            SessionContext.set_user(user)
            self.accept()
            return

        # Failure — identical message for wrong-user and wrong-password.
        self._failed_attempts += 1
        self.message_label.setText("Invalid username or password")
        self.password_input.clear()
        if self._failed_attempts >= _MAX_ATTEMPTS:
            self._start_lockout()

    def _start_lockout(self):
        self.login_button.setEnabled(False)
        self.message_label.setText(
            f"Too many failed attempts. Try again in {_LOCKOUT_SECONDS} seconds."
        )
        QTimer.singleShot(_LOCKOUT_SECONDS * 1000, self._end_lockout)

    def _end_lockout(self):
        self._failed_attempts = 0
        self.login_button.setEnabled(True)
        self.message_label.setText("")

    def keyPressEvent(self, event):
        # Enter triggers the default (Login) button; block Esc-close being
        # treated as a successful path (reject is fine — the app exits).
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.login_button.isEnabled():
                self.on_login()
            return
        super().keyPressEvent(event)
