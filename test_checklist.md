# Gemini ERP — Test Build Checklist

For the tester on a clean Windows machine (no Python installed). Unzip the
`GeminiERP` folder and double-click `GeminiERP.exe`. Tick each item; if anything
fails, note it and attach `GeminiERP\logs\gemini_erp.log`.

## Smoke tests (does it run)

- [ ] App installs (unzip) and opens with no errors
- [ ] `gemini_erp.db` is created automatically in the GeminiERP folder on first run
- [ ] All tabs and screens are reachable (Items, Billing, Purchases, Sales Log,
      Purchase Log, Accounts, Banking, GST, Documents)

## Core loop tests (does the data work)

- [ ] Add 3 items with different GST rates (0%, 5%, 18%)
- [ ] Add 2 customers — one in **Andhra Pradesh**, one in a **different state**
- [ ] Add 1 supplier
- [ ] Create a sale to the AP customer → invoice PDF shows **CGST + SGST**
- [ ] Create a sale to the out-of-state customer → invoice PDF shows **IGST**
- [ ] Confirm **stock drops** after each sale
- [ ] Create a purchase → confirm **stock rises**
- [ ] Create a sale to a **walk-in customer** with no GSTIN and no state →
      defaults to AP and shows **CGST + SGST**

## Reports

- [ ] Trial Balance opens and **total debit == total credit**
- [ ] Profit & Loss shows income and expense
- [ ] GST register shows correct invoice data
- [ ] PDF invoice saves to disk and opens correctly

## Edit features

- [ ] **Items:** select an item → **Edit Selected** (or double-click) → change
      name/GST/unit → **Update Item** → the row reflects the change; try a
      duplicate code and confirm it's rejected
- [ ] **Billing (before saving):** add 2 lines → select one → **Edit Line** →
      change qty/rate → **Update Line** → the line is replaced (not duplicated)
      and totals update; then Save the invoice
- [ ] **Purchase Log:** select a saved purchase → **Edit Selected Invoice** →
      it opens in the Purchases tab in **Update Purchase** mode → change a qty →
      **Update Purchase** → confirm the item's **stock changed by the net
      difference** (not double-counted) and the Purchase Log total updated

## Edge cases

- [ ] Try to sell **more than available stock** — the app handles it gracefully
      (message, not a crash)
- [ ] Add an item **inline** from the Purchase screen
- [ ] Open the **Scan Purchase Bill** (OCR) screen — if OCR isn't set up it
      shows "not configured" cleanly (no crash)

## OCR (only if the ocr_worker venv was set up)

- [ ] Scan a JPG/PNG bill — after a few minutes it shows extracted text and
      pre-fills supplier / invoice no / date for review
- [ ] Scan a PDF bill — Poppler is bundled, so it converts without a separate
      install
- [ ] Save a reviewed scan → it creates a purchase and links the document
      (visible in Documents → Document History)

---

### Notes / issues found

(Write anything unexpected here, with the step number. Attach
`GeminiERP\logs\gemini_erp.log` if the app crashed.)
