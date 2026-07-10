# Gemini ERP

A Windows desktop application for invoicing, purchases, inventory and GST.

## Running the app

1. Open the **GeminiERP** folder.
2. Double-click **GeminiERP.exe**.

No Python installation is required — everything the app needs is inside this
folder.

## First run

The app creates its database automatically the first time you start it:

- **GeminiERP\gemini_erp.db** — this is your data (items, invoices, stock,
  accounts). **Back it up regularly** by copying this file somewhere safe.

You can start adding items, customers, suppliers and invoices right away.

## Where your data is stored

| What                | Location                        |
|---------------------|---------------------------------|
| Database            | `GeminiERP\gemini_erp.db`       |
| Scanned bills       | `GeminiERP\documents\`          |
| Log file            | `GeminiERP\logs\gemini_erp.log` |

**Back up the entire `GeminiERP` folder regularly** — that captures your
database and all scanned documents together.

If the app ever fails to start, open `logs\gemini_erp.log` — the error is
recorded there.

## OCR setup (optional — only for scanning purchase bills)

Scanning supplier bills is optional. The rest of the app works without it. To
enable it:

1. Install **Python 3.13** from https://www.python.org/downloads/ (it installs
   alongside anything else and adds the `py -3.13` launcher).
2. Open a terminal in the **GeminiERP\ocr_worker** folder and run:
   ```
   py -3.13 -m venv venv_ocr
   venv_ocr\Scripts\activate
   pip install -r requirements.txt
   ```
3. Poppler (for PDF bills) is **already included** — no separate install needed.

The first scan downloads the OCR models (needs internet once). A scan of a real
bill takes a few minutes on a typical machine — this is normal. Until OCR is set
up, the Scan screen simply says it is not configured; you can still enter bills
manually.

Full details: `ocr_worker\README.md`.

## Known limitations of this build

- **AI natural-language reports** — not yet implemented (a later phase).
- **Multi-user / networked database** — not yet implemented; this build is
  single-user with a local database (a later phase).
