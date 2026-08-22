# Gemini ERP

A Windows desktop application for invoicing, purchases, inventory and GST.

## Running the app

1. Open the **GeminiERP** folder.
2. Double-click **GeminiERP.exe**.

No Python installation is required — everything the app needs is inside this
folder.

## First run

The first time you start the app it creates its database and shows a **login
screen**. Sign in with the built-in administrator account and you will be asked
to set your own password straight away:

| Username | Password |
|---|---|
| `admin` | `Admin@1234` (you must change it on first login) |

Then set your company details on the **Settings** tab and add accounts for your
team on the **Users** tab. **See [`FIRST_TIME_SETUP.md`](FIRST_TIME_SETUP.md) for
the full first-time walkthrough.**

Your data lives in **GeminiERP\gemini_erp.db** — **back it up regularly** by
copying it (or the whole folder) somewhere safe.

> The very first launch can take ~10 seconds while Windows scans the new program
> — this is normal; later launches are quick.

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

## Multi-user / networked use

Out of the box the app is single-user with a local database. It can also run
**multi-user** with several PCs sharing one Microsoft SQL Server database, and
there is a read-only **mobile companion** app. Both are optional and need a bit
of setup — see the "Multi-user deployment" and "Mobile companion API" sections
of `README.md`.

## Known limitations of this build

- **AI natural-language reports** — not yet implemented (a later phase).
