# CHECKLIST_ENHANCEMENTS.md — Post-Phase-3 edit features

Small improvements found during testing (2026-07-10). Same rules as every
checklist (`CLAUDE.md`): business logic in services, UI only collects/shows,
the stock rule holds, one transaction = all or nothing, build → test → confirm.

These are independent of Phase 4 (multi-user) and do not change the packaging.

---

## E1 — Edit an item in the Items tab ✅

Select an item in the table and edit its master fields.

- [x] `ItemService.update_item(item_id, …)` — updates code/name/HSN/GST/unit/
      opening_stock/reorder_level; keeps the item **code unique** among
      non-deleted items (excluding itself). Stock stays derived from
      `stock_transactions`, so editing `opening_stock` only shifts the baseline —
      the movement log is never touched (the stock rule holds).
- [x] `ui/item_master.py` — table is row-selectable; **Edit Selected** (or
      double-click) loads the row into the form and enters edit mode (the Add
      button becomes **Update Item**, with **Cancel Edit**). Save routes to
      `add_item` or `update_item` by mode.
- [x] **Test:** `check_item_edit.py` — field updates persist, duplicate code is
      rejected, same-code-on-same-item is allowed, and an `opening_stock` edit
      moves current stock by the delta with no new stock transactions. PASS.

## E2 — Edit a saved purchase invoice ✅

Edit a purchase invoice that was already saved (from the Purchase Log). Because
a saved purchase already moved stock and posted to the ledger, editing must undo
those and re-apply — safely.

- [x] `PurchaseService.update_purchase_invoice(invoice_id, …)` — in **one
      transaction**: soft-delete the original line items, the original IN
      `stock_transactions`, and the original journal entry (+ its lines), then
      re-apply the edited header, lines, IN movements and a fresh **balanced**
      journal entry. Any failure rolls the whole edit back, so billing,
      inventory and the ledger can never drift apart. Shared apply logic
      (`_apply_lines_and_accounting`) is reused by create and update so both stay
      identical.
- [x] `get_purchase_invoice_details` now skips soft-deleted lines and returns
      `supplier_id` / `item_id` / `gst_rate` so the edit screen can rebuild.
- [x] `ui/purchase.py` — `load_invoice_for_edit()` prefills header + lines and
      switches the screen to **Update Purchase** mode; `ui/purchase_log.py` adds
      **Edit Selected Invoice** (emits `edit_requested`); `main.py` loads the
      invoice into the Purchase tab and jumps to it.
- [x] **Test:** `check_purchase_edit.py` — editing a 10-qty purchase down to 4
      leaves net stock **+4** (original IN reversed), exactly one active stock
      movement / line / journal entry, header totals recomputed (taxable 400,
      total 472 @18%), and the trial balance still balances. PASS.

## E3 — Edit a line in the Billing tab before saving ✅

Edit a line already added to the invoice grid, before the invoice is saved.

- [x] `ui/billing.py` — the lines grid is row-selectable; **Edit Line** (or
      double-click) loads the line back into the entry row (item/qty/rate) and
      the Add button becomes **Update Line**; saving the line **replaces** it in
      place. In-memory only — nothing is written until **Save Invoice**, so no
      stock/ledger reversal is involved (unlike E2). The same capability was
      added to the Purchase entry grid (needed by E2's edit mode).
- [x] **Test:** covered by `check_edit_ui.py` (offscreen Qt) — an edited line
      replaces rather than appends, and edit mode resets afterwards. PASS.

---

## Cross-cutting verification

- [x] `check_edit_ui.py` — MainWindow constructs (imports + Purchase Log → Purchase
      wiring), Items edit-mode enter/cancel, Billing line replace, Purchase
      load-for-edit sets update mode and switches tabs. PASS.
- [x] Regression: `check_milestone11` (purchase accounting) and
      `check_milestone18` (GST registers) still PASS after refactoring
      `create_purchase_invoice` onto the shared apply helper.

> Note: `check_milestone7` / `check_milestone3` fail on this dev database due to
> pre-existing stale rows (an old supplier/customer created before ledger
> accounts were linked) — unrelated to these changes; the same create paths pass
> under `check_milestone11` with properly seeded parties.
