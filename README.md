# Gemini ERP

A Windows desktop ERP for an Indian trading business (billing, inventory,
purchases, accounting, GST, and OCR-based bill scanning).

See `ROADMAP.md` for the phase plan, `CLAUDE.md` for the working rules, and the
`CHECKLIST*.md` files for the per-phase build order.

## Tech stack

- Python + PySide6 (Qt) UI
- SQLAlchemy ORM over SQLite (SQL Server later, Phase 4)
- ReportLab (PDF), OpenPyXL (Excel)
- PaddleOCR (Phase 3 supplier-bill scanning)

## Setup (main app — Python 3.14)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python gemini_erp/create_db.py   # creates the SQLite database and tables
python gemini_erp/main.py        # launches the app
```

## OCR setup (Phase 3 — separate Python 3.13 venv)

PaddlePaddle (PaddleOCR's backend) has no wheels for Python 3.14, so OCR runs
in its own **Python 3.13** venv. The main app invokes it as a subprocess;
`services/ocr_service.py` is the only bridge. You need Python 3.13 installed.

```
py -3.13 -m venv venv_ocr
venv_ocr\Scripts\activate
pip install -r requirements-ocr.txt
```

### OCR also requires poppler (Windows)

Bill scanning uses `pdf2image`, which needs **poppler** to convert PDF pages to
images. Without it, PDF scanning fails (image files still work).

1. Download the poppler Windows build from
   https://github.com/oschwartz10612/poppler-windows
2. Extract it (e.g. `C:\poppler`).
3. Add its `bin\` folder (e.g. `C:\poppler\Library\bin`) to your system PATH.
4. Open a new terminal and confirm with `pdftoppm -h`.

## Packaging (Windows distribution)

The app ships as a PyInstaller **onedir** build plus an optional Inno Setup
installer. Nothing user-writable is baked in: on first run the app creates its
database, `documents\` and `logs\` next to the exe (`get_app_root()` resolves
this whether run from source or frozen).

### 1. Build the distribution folder

```
build.bat
```

Produces `dist\GeminiERP\` — a self-contained folder that runs on a clean
machine with no Python installed (double-click `GeminiERP.exe`). It also
assembles `dist\GeminiERP\ocr_worker\` (the 3.13 OCR runner + bundled Poppler);
the OCR `venv_ocr` is created once on the target machine — see
`ocr_worker\README.md`. `build.bat` reads Poppler from
`C:\Program Files\Poppler\poppler-26.02.0\Library\bin` (edit `POPPLER_BIN` at
the top if yours differs).

### 2. Build the installer (optional)

Install **Inno Setup 6** (https://jrsoftware.org/isdl.php), then:

```
build_installer.bat
```

Compiles `installer.iss` into `installer\GeminiERP-Setup-<version>.exe`. It is a
**per-user** installer (installs to `%LOCALAPPDATA%\Programs\GeminiERP`, no admin
prompt); the user's database and documents survive an uninstall/reinstall.

`DISTRIBUTION_README.md` is the end-user guide; `test_checklist.md` is for
testing the build on a clean machine.
