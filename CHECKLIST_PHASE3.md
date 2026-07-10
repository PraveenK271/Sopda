# CHECKLIST_PHASE3.md — Phase 3 Part 1: OCR & Document Management

PLANNING DOCUMENT — nothing in this file has been built yet. Phase 2
(Milestones 0-19: Core loop, Purchases, Accounting, Banking, GST returns)
is complete. This is the FIRST chunk of Phase 3 (per `ROADMAP.md` "Documents
& AI"), scoped by `OCR_Instruction.txt`:

- OCR-based purchase bill scanning (PaddleOCR) — spec Module 12 + Module 13
  Feature 1
- Document storage (the `Documents` / `OCRResults` tables from the spec)

The remaining Phase 3 AI features — natural-language reports, inventory
forecasting, smart purchase suggestions (spec Module 13 Features 2-4) — are
NOT covered here. They get their own checklist once this chunk is built,
tested and confirmed. **That later chunk needs an LLM-provider decision
(Claude API / OpenAI-compatible / local / rule-based) — ask before planning
it.**

Same rules as every prior checklist (`CLAUDE.md` still applies):
**build -> test -> confirm -> next, one milestone at a time.** No business
logic in the UI. One transaction = all or nothing on save. Milestone
numbering continues from Phase 2 (next is 20).

---

## Guiding principle (from `OCR_Instruction.txt`)

OCR is a **time-saver, not an auto-importer**. The user always sees what OCR
extracted and confirms/corrects it before anything is saved. Never invent a
field value; a field that can't be extracted is `None` + a warning, and the
user fills it in. OCR must never crash the UI or corrupt stock with guessed
line items.

## The one non-negotiable design rule

`services/ocr_service.py` is the **ONLY** file in the codebase that imports
or talks to PaddleOCR. No UI file, no other service, no report touches
PaddleOCR directly. This is what lets us swap the engine (or add a cloud/LLM
fallback) later by changing one file — it is explicitly listed as future
scope in `OCR_Instruction.txt`.

---

## Runtime constraint (decided during Milestone 20)

PaddlePaddle publishes **no wheels for Python 3.14**, which is the main app's
runtime. Rather than downgrade the whole app, OCR runs in a **separate
Python 3.13 venv (`venv_ocr`)**. The main app (3.14) will invoke OCR as a
**subprocess** and `services/ocr_service.py` is the only bridge to that venv
(Milestone 21 builds the subprocess bridge; the paddleocr import itself lives
in a small runner module executed by `venv_ocr`, preserving the "only the OCR
service touches PaddleOCR" rule). Core deps stay in `requirements.txt`; OCR
deps live in `requirements-ocr.txt`.

---

## Milestone 20 — Dependencies & OCR setup

- [x] Split deps: core app stays in `requirements.txt` (3.14 venv); OCR deps
      (`paddleocr`, `paddlepaddle`, `pdf2image`, `Pillow`) go in
      `requirements-ocr.txt` (3.13 `venv_ocr`)
- [x] Create the OCR venv on Python 3.13: `py -3.13 -m venv venv_ocr`, then
      `pip install -r requirements-ocr.txt` into it; add `venv_ocr/` to
      `.gitignore`
- [x] Add to `README.md`: two-venv setup + pdf2image needs **poppler for
      Windows** (download from
      https://github.com/oschwartz10612/poppler-windows, add its `bin/` to PATH)
- [x] **Test it:** in `venv_ocr`,
      `python -c "import paddleocr, pdf2image, PIL"` runs with no ImportError
      — PASSED (paddleocr 3.7.0, paddlepaddle 3.3.1, pdf2image 1.17.0, Pillow
      12.3.0). Note: `import paddleocr` does NOT download models; that happens
      when `PaddleOCR()` is first instantiated (Milestone 21). Poppler PATH is
      only needed for PDF scanning (Milestone 21+), not for these imports.

---

## Milestone 21 — OCRService (most important part)

**Architecture note (subprocess split):** because OCR runs in the separate
3.13 `venv_ocr`, the single PaddleOCR wrapper is split across two files while
still keeping ALL paddle imports in one place:
- `services/ocr_runner.py` — runs under `venv_ocr` (3.13); the ONLY file that
  imports PaddleOCR/pdf2image and does image preprocessing. Takes a file path,
  emits one JSON line (`raw_text`, `confidence`, `warnings`) on stdout.
- `services/ocr_service.py` — runs in the main app (3.14); invokes the runner
  as a subprocess and does the paddle-free regex parsing. This is why
  `_run_ocr`/`preprocess_image` live in the runner and `_parse_results` lives
  in the service (so `check_ocr_service.py` can test parsing on 3.14).

- [x] Create `services/ocr_service.py` (bridge + parser) and
      `services/ocr_runner.py` (the sole PaddleOCR wrapper)
- [x] Define the **standard output dict** every caller receives regardless of
      engine: `supplier_name`, `invoice_number`, `invoice_date` (raw string),
      `supplier_gstin`, `line_items` (list of `description`, `hsn_code`,
      `quantity`, `rate`, `amount`, `gst_rate`), `taxable_amount`, `cgst`,
      `sgst`, `igst`, `total_amount`, `raw_text` (always populated),
      `confidence` (0.0-1.0), `warnings` (list[str]). Missing field -> `None`
      + a warning; never raise for a missing field
- [x] Engine init (in the runner): `PaddleOCR(lang='en',
      use_textline_orientation=True, enable_mkldnn=False)`, created once per
      runner invocation. NOTE two deviations from the spec text, both required
      by the installed engine: (a) `use_textline_orientation` replaces the
      **deprecated** `use_angle_cls` in PaddleOCR 3.x; (b) `enable_mkldnn=False`
      works around a PaddlePaddle 3.x CPU-backend crash on this machine
      (`ConvertPirAttribute2RuntimeAttribute ... onednn_instruction.cc`).
- [x] `extract_from_file(file_path) -> dict` — entry point for the UI, accepts
      PDF/JPG/JPEG/PNG. PDF -> `pdf2image.convert_from_path()` per page, OCR
      each, merge (bills are 1-2 pages); image -> OCR directly. Wrapped in
      try/except: on failure returns the standard dict with fields `None`,
      `raw_text=""`, `confidence=0.0`, warning `"OCR failed: <msg>"` — never
      crashes the UI (verified: engine error was captured as a warning)
- [x] `_run_ocr` (runner) — joins PaddleOCR `rec_texts` in reading order,
      averages `rec_scores`; calls `_preprocess` first
- [x] `preprocess_image` (runner `_preprocess`) — greyscale, contrast x1.5
      (PIL `ImageEnhance`), upscale 2x if width < 1000px, back to RGB for the
      engine
- [x] `_parse_results(raw_text) -> dict` — regex extraction for Indian bills:
  - GSTIN: `r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}'`
    (first match that is NOT our own GSTIN = supplier's)
  - Invoice number: keywords "invoice no / bill no / inv no / invoice # /
    bill number" (case-insensitive), value after keyword/colon on same line
  - Date: near "date / dt", patterns dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy;
    return raw string (user confirms format)
  - Supplier name: first non-empty line of `raw_text` as candidate
  - Amounts (taxable/cgst/sgst/igst/total/grand total): numeric on the
    labelled line; strip ₹, commas, spaces before `float()`
  - Line items: **implemented conservatively** — always returns `[]` plus a
    warning telling the user to enter/verify items from the raw text. The spec
    permits this ("do not guess line items — wrong items corrupt stock"); a
    generic multi-column row parser is too format-fragile to trust against
    live stock, so it is deferred until real bill formats are seen (M21
    real-bill test / later)
- [x] **Test it:** `check_ocr_service.py` — 5/5 PASS on the main 3.14 venv
      (typical bill extracts GSTIN/invoice/date/amounts; no-GSTIN -> None +
      warning; malformed `"1,234.56"` and `"₹ 1234"` parse correctly; missing
      file -> standard dict, `confidence=0.0`, warning, no raise; confidence
      bands). Also verified the real subprocess bridge on a synthetic bill:
      `confidence 0.989`, supplier/GSTIN/date/amounts all correct (invoice_no
      missed only because the engine misread "Invoice"->"nvoice" on that
      synthetic image — flagged as a warning, not guessed)
- [x] **Real-bill smoke test — DONE** on 3 real supplier bills in
      `Samples_TestOCR/` (intra-state, IGST/inter-state, and a 90°-rotated
      page). Recognition quality was high (confidence 0.90-0.94). Findings that
      shaped the final config + the M23 UI defaults:
  - **Reliable to pre-fill:** supplier GSTIN, invoice date (incl. `dd-Mon-yy`),
    supplier name, and invoice number when it shares the label's line.
  - **Unreliable -> default to MANUAL entry in M23:** all amounts (taxable/
    cgst/sgst/igst/total) and line items. Real bills are tabular, so a value
    can be many lines from its label or collide with a round-off/qty number;
    a wrong pre-fill is worse than a blank. (Per user decision: do not invest
    in geometric/bounding-box parsing now — keep amounts manual.)
  - **Rotated pages read poorly** across the board -> users upload upright
    scans (a rotate step can be added to the UI later).
  - **Engine config chosen from this test** (see `ocr_runner.py`): mobile
    det/rec models (medium models time out at ~350s), doc-orientation/unwarp
    off, mkldnn off (crashes), long side capped at 1600px. ~4 min/bill on this
    CPU — accepted, covered by the M23 loading indicator (`_OCR_TIMEOUT_SECONDS
    = 600`).
  - Parser upgrades from this test: `dd-Mon-yy` dates, invoice-date line
    preference (skip pay/order/due dates), money-aware multi-line amount
    matching, "Integrated Tax" alias for IGST, and supplier-name picking that
    skips logo/QR glyphs + the "Tax Invoice" header.

---

## Milestone 22 — Document storage

- [x] `models/document.py` — `Document`: `id`, `file_name`, `file_path`,
      `upload_date`, `document_type` (`'PURCHASE_BILL'`),
      `linked_purchase_invoice_id` (nullable FK to `purchase_invoices`),
      `ocr_status` (`'PENDING' | 'DONE' | 'FAILED'`), `ocr_raw_text` (Text,
      nullable), `ocr_confidence` (Float, nullable) + AuditMixin. Files live in
      `gemini_erp/documents/` (next to the db + `output/`; gitignored)
- [x] Registered `Document` in `models/__init__.py`; `create_db.py` creates the
      `documents` table (confirmed present)
- [x] `services/document_service.py` — `DocumentService`:
  - `save_document(...)` — copies the file into `documents/` under a unique
    `timestamp_originalname` name, creates a PENDING row; no OCR
  - `run_ocr_on_document(document_id) -> dict` — calls
    `OCRService.extract_from_file()`, sets `ocr_status` (DONE if text found
    else FAILED) / `ocr_raw_text` / `ocr_confidence`, returns the standard dict
  - `link_to_purchase_invoice(document_id, purchase_invoice_id)`
  - `list_documents(document_type=None) -> list[dict]` (returns dicts, not ORM
    objects, mirroring the other services so callers aren't tied to a session)
  - OCR engine is injectable (`DocumentService(ocr_service=...)`) so tests use
    a fake instead of the ~4-min real engine
- [x] **Test it:** `check_milestone22.py` — 5/5 PASS (save -> PENDING + unique
      file in `documents/`; run_ocr DONE with text / FAILED without; link sets
      the FK; list returns the saved doc). Uses a fake OCR engine.

---

## Milestone 23 — OCR review UI + navigation

- [x] `ui/ocr_purchase.py` — `OCRPurchaseScreen` **subclasses `PurchaseScreen`**
      so the line-entry table, GST totals and save path are reused verbatim
      (one save path, no logic duplication). Two stages:
  - **Stage 1 (Upload):** "Browse…" (PDF/JPG/PNG), "Scan Bill" (stores the file
    via `save_document`, then runs `run_ocr_on_document` on a background
    `QThread` so the ~4-min scan doesn't freeze the UI), a status/"Scanning…"
    label, and a read-only text area showing `raw_text` as reference
  - **Stage 2 (Review & confirm):** pre-fills invoice number + date (parsed,
    incl. `dd-Mon-yy`) and selects the supplier by GSTIN/name match (else seeds
    the inline "New Supplier" box); confidence label (High/Medium/Low); scanned
    amounts shown **as reference only** (amounts + line items are manual per the
    M21 findings); OCR warnings shown in an amber label
  - **Save:** the inherited **"Save Purchase Invoice"** button calls the EXISTING
    `PurchaseService.create_purchase_invoice()`; an `_after_save` hook (added to
    the base screen) then calls `link_to_purchase_invoice` and resets OCR state
  - Every field is editable; Save stays DISABLED until a supplier is selected,
    an invoice number is entered, and at least one line item exists (which is
    what yields the total)
- [x] "Documents" top-level tab in `main.py` with sub-tabs "Scan Purchase Bill"
      (`OCRPurchaseScreen`) and "Document History" (`DocumentHistoryScreen`,
      lists `DocumentService.list_documents()` with OCR status + linked invoice
      id). Refreshed from `on_tab_changed`.
- [x] **Test it:** `check_milestone23.py` — headless (offscreen Qt) 4/4 PASS:
      date parsing; store->OCR-done handler->supplier matched by GSTIN->add a
      line->Save creates a purchase invoice via the EXISTING service AND links
      the document; OCR state resets; Document History lists rows. Also
      smoke-tested that `MainWindow` constructs with the Documents tab and
      `on_tab_changed` runs. (Kept the check as a regression test, consistent
      with the other `check_milestone*.py` files.)
  - NOTE (deviation from the spec text): stock still auto-increments correctly
    because save goes through the unchanged `create_purchase_invoice`; there is
    no editable OCR-prefilled line-items table — line items are entered via the
    inherited item picker (M21 decision: don't trust OCR line items against
    live stock). The end-to-end scan of a *real* bill through the UI is a manual
    click-test for the user; the engine path itself was already validated in M21.

---

## Phase 3 Part 1 is DONE when:  ✅ COMPLETE (Milestones 20-23)

You can upload a supplier bill (PDF/JPG/PNG), have OCR pre-fill the purchase
form, correct anything wrong, save it through the SAME purchase service (so
stock and the books stay in sync exactly as before), and see the scanned
file stored and linked to the invoice — all without OCR ever crashing the app
or writing guessed data. **All four milestones built and tested.**

Remaining manual (user) checks, both optional and non-blocking:
- Click-test one real scan through the Documents tab in the running app.
- Install poppler if PDF (not just image) bills are needed (README.md).

**Phase 3 Part 2 (natural-language reports, inventory forecasting, smart
purchase suggestions — spec Module 13 Features 2-4) is NOT started and needs an
LLM-provider decision — plan it separately when the user is ready.**

---

## Deliberately NOT built in this chunk (future scope, per `OCR_Instruction.txt`)

- Cloud OCR fallback (Google Document AI / AWS Textract) — the single-service
  wrapper makes this a drop-in later
- Auto-matching supplier by GSTIN against the suppliers table — add once OCR
  is stable
- Sales bill scanning — reuse the same `OCRService`, different UI
- Bank statement import — already out of scope (Phase 2 Decision 4)
