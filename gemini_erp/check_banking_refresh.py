"""Check: a bank account added in the Bank Accounts tab appears immediately in
the Receipts / Payments / Reconciliation bank dropdowns (offscreen Qt).

Reproduces the reported bug (dropdowns only updated on reopen) and proves the
signal-based refresh fixes it — without calling refresh_all() or re-entering
the Banking tab.

Run with: python check_banking_refresh.py
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)


def _combo_names(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def main():
    app = QApplication.instance() or QApplication([])
    from ui.banking import BankingScreen

    screen = BankingScreen()
    # Prime the dropdowns the way entering the Banking tab would.
    screen.refresh_all()

    before = len(_combo_names(screen.receipts_tab.bank_combo))

    unique = f"CHK-BANK {int(time.time())}"
    tab = screen.bank_accounts_tab
    tab.name_input.setText(unique)
    tab.bank_name_input.setText("Test Bank")
    tab.on_add()  # <-- add account; must notify sibling tabs

    # The new account must be present in ALL three dependent dropdowns NOW,
    # without any refresh_all()/tab re-entry.
    for name, combo in (
        ("Receipts", screen.receipts_tab.bank_combo),
        ("Payments", screen.payments_tab.bank_combo),
        ("Reconciliation", screen.reconciliation_tab.bank_combo),
    ):
        names = _combo_names(combo)
        assert any(unique in n for n in names), f"{name} dropdown missing new account: {names}"
        print(f"[1] {name} dropdown shows the new account immediately OK")

    after = len(_combo_names(screen.receipts_tab.bank_combo))
    assert after == before + 1, (before, after)
    print(f"[2] Receipts dropdown grew {before}->{after} OK")

    # Switching to a sub-tab also refreshes it (currentChanged wiring).
    screen.setCurrentWidget(screen.payments_tab)
    assert any(unique in n for n in _combo_names(screen.payments_tab.bank_combo))
    print("[3] Switching to Payments refreshes its dropdown OK")

    print("\nAll banking-refresh checks passed.")


if __name__ == "__main__":
    main()
