# First-Time Setup — Gemini ERP

A short guide to getting Gemini ERP running the very first time: how to log in,
the initial administrator tasks, and where your data lives.

---

## 1. Launch and log in

1. Open the **GeminiERP** folder and double-click **GeminiERP.exe**.
   > The **first** launch can take ~10 seconds while Windows scans the program
   > files — this is normal. Later launches are quick.
2. A **login window** appears. Sign in with the built-in administrator account:

   | | |
   |---|---|
   | **Username** | `admin` |
   | **Password** | `Admin@1234` |

3. You will be **required to change the password immediately** — this cannot be
   skipped. In the change-password box:
   - **Current Password:** `Admin@1234`
   - **New Password:** choose your own (at least **8 characters**)
   - **Confirm New Password:** the same again

   After this, the main window opens and you are the **Administrator** (you see
   every tab).

> **Important**
> - `admin` / `Admin@1234` is a one-time default that works **only until you
>   change it**. There is no other built-in account.
> - Choose a strong new password and keep it somewhere safe.
> - Create at least **two** administrator accounts (see step 3) so you are never
>   locked out if one password is lost.

---

## 2. Set your company details

Go to the **Settings** tab and fill in your company profile:

- Company name, address, mobile, **GSTIN**, state
- Bank name / account no. / IFSC / branch (shown on invoices)
- Terms & conditions

These replace the placeholder values and appear on every **invoice PDF**, so do
this before you print real invoices.

---

## 3. Create user accounts for your team

Go to the **Users** tab (Administrator only) and add an account for each person,
choosing the role that matches their job. Each new user is asked to set their own
password the first time they log in.

| Role | Can use |
|---|---|
| **Administrator** | Everything (incl. Settings, Users, Data Import, Verify & Lock) |
| **Accountant** | Billing, Sales Log, Purchases, Purchase Log, Accounts, GST, Documents |
| **Inventory Manager** | Items, Purchases, Purchase Log, Documents |
| **Sales User** | Billing, Sales Log, Items |

Buttons on the Users screen let an administrator **Add User**, **Reset Password**
(the user must then set a new one), and **Deactivate** an account (accounts are
never deleted, so their name stays on old records).

---

## 4. Where your data is stored — and backups

| What | Location |
|---|---|
| Database | `GeminiERP\gemini_erp.db` |
| Scanned bills | `GeminiERP\documents\` |
| Log file | `GeminiERP\logs\gemini_erp.log` |

**Back up the whole `GeminiERP` folder regularly** — that captures your database
and scanned documents together. The Settings tab also has a **Backup now**
button.

---

## 5. Single-user vs. multi-user (which database)

- **Default (nothing to configure):** the app uses a **local file** database
  (`gemini_erp.db`) on this one PC — perfect for a single user.
- **Multiple PCs sharing one database:** point each client at a shared
  **SQL Server** by creating a `gemini_erp\.env` file with a `GEMINI_DB_URL`.
  See the **"Multi-user deployment"** section of `README.md` for the exact steps
  (each client needs the Microsoft ODBC driver installed).

---

## 6. If you're locked out

- **Forgot a user's password:** any Administrator can reset it on the **Users**
  tab (Reset Password → the user sets a new one on next login).
- **Forgot the *only* admin password:** there is no back door by design. This is
  why step 1 recommends keeping a second administrator account. (Deleting
  `gemini_erp.db` starts over with a fresh `admin` / `Admin@1234`, but that
  **erases all your data** — only a last resort on an empty system.)

---

## 7. Optional extras

- **Scanning supplier bills (OCR):** optional; needs a one-time Python 3.13 setup
  — see `DISTRIBUTION_README.md` and `ocr_worker\README.md`.
- **Mobile companion app (read-only dashboards):** runs as a separate service and
  requires a signing key (`GEMINI_JWT_SECRET`). A user must change their password
  on the desktop before they can sign in on mobile. See the **"Mobile companion
  API"** section of `README.md`.

---

## 8. First-launch troubleshooting

- **It takes a while to open the first time** — normal (antivirus scanning the
  new program). Give it up to a minute.
- **It won't start / closes immediately** — open `GeminiERP\logs\gemini_erp.log`;
  the error is recorded there.
