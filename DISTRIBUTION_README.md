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
| Backups             | `GeminiERP\backups\`            |

**Back up the entire `GeminiERP` folder regularly** — that captures your
database and all scanned documents together.

If the app ever fails to start, open `logs\gemini_erp.log` — the error is
recorded there.

## Updating from an earlier version

To update, **install the new version over the existing one**. Run the new
installer, which installs into the same folder by default. If you use the
zipped folder, copy the new files over the old `GeminiERP` folder. Your data
is kept:

- **Keep** `gemini_erp.db` (your database), the `documents\` folder and, if you
  use one, the `.env` file. The installer never overwrites or removes them.
  When copying a zip by hand, do not delete them.

The **first launch after an update** shows a one-time **"Updating database,
please wait"** message. The app then:

1. **backs up your database automatically**, before changing anything:
   - Single-user (SQLite): to `GeminiERP\backups\pre_patch_<version>_<date>_<time>.db`
   - SQL Server: a `.bak` in the SQL Server instance's own backup folder, named
     `GeminiERP_pre_patch_<version>_<date>_<time>.bak`
2. adds the new columns and tables the update needs. Existing invoices, stock
   and balances are not changed.
3. tells you which updates were applied and where the backup is.

If the backup cannot be written, **nothing is changed** and the app closes
with a message. If an update step fails, the app closes rather than open a
half-updated database, and names the backup file.

**Multi-user (SQL Server):** update and launch **one** PC first and let it
finish the database update, then update the other PCs. That first launch must
be by a Windows account that SQL Server allows to back up the database
(e.g. the administrator's). Otherwise the backup fails and the update will
not start. If you run the mobile
companion API, start it only after that first launch.

**After updating to 1.2.0:** an Administrator should open **Settings → GST
returns** and set "GSTR-1 has been filed up to" to the last date you have
filed GSTR-1 for. Invoices on or before that date cannot then be cancelled or
renumbered (the correct route there is a credit note). Update it each month
after filing.

### Going back to the previous version (rollback)

Updates only ever ADD to the database, so going back is simply:

1. Close the application (on every PC).
2. Restore the automatic pre-update backup:
   - SQLite: copy `backups\pre_patch_<version>_….db` over `gemini_erp.db`
     (keep a copy of the current file first).
   - SQL Server: restore the `GeminiERP_pre_patch_….bak` in SQL Server
     Management Studio (Restore Database → From device).
3. Reinstall the previous version's folder or installer.

Anything entered after the update is not in that backup, so re-enter it.
Never try to "undo" an update by editing the database by hand.

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
