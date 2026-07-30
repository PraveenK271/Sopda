"""User-management screen (Administrator only).

Lists users and lets an admin add, reset-password, and deactivate. UI only —
every mutation goes through AuthService. Password hashes are never shown.
"""

import logging

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import get_session
from models import Role
from services.auth_service import AuthService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)


class AddUserDialog(QDialog):
    def __init__(self, auth_service: AuthService, parent=None):
        super().__init__(parent)
        self.auth_service = auth_service
        self.setWindowTitle("Add User")
        self.setModal(True)

        self.username_input = QLineEdit()
        self.full_name_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox()

        self._roles = self._load_roles()
        for role_id, name in self._roles:
            self.role_combo.addItem(name, role_id)

        form = QFormLayout()
        form.addRow("Username", self.username_input)
        form.addRow("Full Name", self.full_name_input)
        form.addRow("Password", self.password_input)
        form.addRow("Role", self.role_combo)

        save_button = QPushButton("Create User")
        save_button.clicked.connect(self.on_save)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.setLayout(layout)

    @staticmethod
    def _load_roles():
        session = get_session()
        try:
            return [(r.id, r.name) for r in session.query(Role).order_by(Role.name).all()]
        finally:
            session.close()

    def on_save(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        role_id = self.role_combo.currentData()
        if not username:
            QMessageBox.warning(self, "Add User", "Username is required.")
            return

        session = get_session()
        try:
            self.auth_service.create_user(
                session,
                username,
                password,
                self.full_name_input.text().strip() or None,
                role_id,
                must_change_password=True,
                created_by=SessionContext.get_username(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Add User", str(exc))
            return
        except Exception:
            logger.exception("Failed to create user")
            QMessageBox.critical(self, "Add User", "Could not create the user.")
            return
        finally:
            session.close()
        self.accept()


class UserManagementScreen(QWidget):
    COLUMNS = ["ID", "Username", "Full Name", "Role", "Active", "Last Login"]

    def __init__(self, auth_service: AuthService | None = None):
        super().__init__()
        self.auth_service = auth_service or AuthService()

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        add_button = QPushButton("Add User")
        add_button.clicked.connect(self.on_add_user)
        reset_button = QPushButton("Reset Password")
        reset_button.clicked.connect(self.on_reset_password)
        deactivate_button = QPushButton("Deactivate")
        deactivate_button.clicked.connect(self.on_deactivate)

        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(deactivate_button)

        layout = QVBoxLayout()
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh()

    def refresh(self):
        session = get_session()
        try:
            users = self.auth_service.list_users(session)
            self.table.setRowCount(len(users))
            for row, user in enumerate(users):
                last_login = user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else "-"
                values = [
                    user.id,
                    user.username,
                    user.full_name or "",
                    user.role.name if user.role else "",
                    "Yes" if user.is_active else "No",
                    last_login,
                ]
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(str(value)))
        except Exception:
            logger.exception("Failed to list users")
            QMessageBox.critical(self, "Users", "Could not load users.")
        finally:
            session.close()

    def _selected_user_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return int(self.table.item(row, 0).text())

    def on_add_user(self):
        dialog = AddUserDialog(self.auth_service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def on_reset_password(self):
        user_id = self._selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "Reset Password", "Select a user first.")
            return
        new_password, ok = _prompt_password(self, "Reset Password", "New password:")
        if not ok:
            return
        session = get_session()
        try:
            self.auth_service.admin_reset_password(
                session, user_id, new_password, created_by=SessionContext.get_username()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Reset Password", str(exc))
            return
        except Exception:
            logger.exception("Failed to reset password")
            QMessageBox.critical(self, "Reset Password", "Could not reset the password.")
            return
        finally:
            session.close()
        QMessageBox.information(
            self, "Reset Password", "Password reset. The user must change it on next login."
        )
        self.refresh()

    def on_deactivate(self):
        user_id = self._selected_user_id()
        if user_id is None:
            QMessageBox.information(self, "Deactivate", "Select a user first.")
            return
        if user_id == getattr(SessionContext.get_user(), "id", None):
            QMessageBox.warning(self, "Deactivate", "You cannot deactivate your own account.")
            return
        confirm = QMessageBox.question(self, "Deactivate", "Deactivate this user?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            self.auth_service.deactivate_user(
                session, user_id, created_by=SessionContext.get_username()
            )
        except Exception:
            logger.exception("Failed to deactivate user")
            QMessageBox.critical(self, "Deactivate", "Could not deactivate the user.")
            return
        finally:
            session.close()
        self.refresh()


def _prompt_password(parent, title: str, label: str):
    """A small masked-input prompt; returns (text, ok)."""
    from PySide6.QtWidgets import QInputDialog

    return QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Password)
