"""Headless UI check for the edit features (offscreen Qt).

Exercises the in-memory edit flows without a display:
  * MainWindow constructs (all imports + the Purchase Log -> Purchase edit wiring).
  * Items screen enters/leaves edit mode from a selected row.
  * Billing screen edits an added line before saving (replace, not append).
  * Purchase screen loads a saved invoice into edit mode.

Run with: python check_edit_ui.py
"""

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from services.purchase_service import PurchaseService  # noqa: E402

# Never block on a dialog in a headless run.
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)


def main():
    app = QApplication.instance() or QApplication([])

    from main import MainWindow

    window = MainWindow()  # proves imports + signal wiring don't error
    print("[0] MainWindow constructed OK")

    # --- Items edit mode ---
    items_screen = window.item_master_screen
    items_screen.refresh_items()
    if items_screen._items:
        items_screen.table.selectRow(0)
        items_screen.on_edit_selected()
        assert items_screen._editing_item_id == items_screen._items[0]["id"]
        assert items_screen.add_button.text() == "Update Item"
        assert items_screen.code_input.text() == items_screen._items[0]["code"]
        items_screen.on_cancel_edit()
        assert items_screen._editing_item_id is None
        assert items_screen.add_button.text() == "Add Item"
        print("[1] Items screen edit-mode enter/cancel OK")
    else:
        print("[1] Items screen edit-mode SKIPPED (no items in db)")

    # --- Billing line edit (replace, not append) ---
    billing = window.billing_screen
    billing.refresh_lookups()
    if billing.item_combo.count() > 0:
        billing.item_combo.setCurrentIndex(0)
        billing.qty_input.setText("3")
        billing.rate_input.setText("50")
        billing.on_add_line()
        assert len(billing.lines) == 1 and billing.lines[0]["rate"] == Decimal("50")

        billing.lines_table.selectRow(0)
        billing.on_edit_line()
        assert billing._editing_line_index == 0
        assert billing.add_line_button.text() == "Update Line"
        billing.rate_input.setText("75")
        billing.on_add_line()  # acts as "Update Line"
        assert len(billing.lines) == 1, "edit must replace, not append"
        assert billing.lines[0]["rate"] == Decimal("75")
        assert billing._editing_line_index is None
        assert billing.add_line_button.text() == "Add Line"
        print("[2] Billing line edit (replace before save) OK")
    else:
        print("[2] Billing line edit SKIPPED (no items in db)")

    # --- Purchase load-for-edit ---
    invoices = PurchaseService().list_purchase_invoices()
    if invoices:
        inv_id = invoices[0]["id"]
        purchase = window.purchase_screen
        window.on_edit_purchase_invoice(inv_id)  # the wired handler
        assert purchase._editing_invoice_id == inv_id
        assert purchase.save_button.text() == "Update Purchase"
        assert len(purchase.lines) >= 1
        assert window.tabs.currentWidget() is purchase
        print(f"[3] Purchase load-for-edit (invoice {inv_id}) OK")
    else:
        print("[3] Purchase load-for-edit SKIPPED (no purchase invoices)")

    print("\nAll edit-UI checks passed.")


if __name__ == "__main__":
    main()
