# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Gemini ERP (onedir Windows distribution).

Explicit (not auto-generated) so the build is repeatable. Build with:
    build.bat            (activates venv, cleans, runs `pyinstaller gemini_erp.spec`)
or directly:
    pyinstaller gemini_erp.spec

Notes on what is and isn't bundled here:
  * The OCR engine (PaddleOCR) is NOT in this bundle — it has no wheels for the
    app's Python 3.14 and runs as a loose script under its own 3.13 venv. The
    ocr_worker/ folder (runner script + poppler) is copied into the dist by
    build.bat, not frozen here. Consequently PIL/paddle are intentionally absent.
  * The database and documents/ folder are created next to the .exe on first run
    (see main._bootstrap), so nothing user-writable is baked into the bundle.
"""

from PyInstaller.utils.hooks import collect_submodules

# app source root: main.py uses top-level imports (`from ui.x`, `from services.x`),
# so gemini_erp/ must be on the analysis path.
APP_DIR = "gemini_erp"

hiddenimports = (
    collect_submodules("sqlalchemy")   # dialects/drivers are imported dynamically
    + collect_submodules("reportlab")  # PDF backends resolved by name
    + collect_submodules("openpyxl")   # Excel export
    # passlib resolves its bcrypt handler by name at runtime, so static analysis
    # misses it; naming it here (its bcrypt backend is a normal import from it).
    + ["passlib.handlers.bcrypt"]
    # Schema migrations are imported BY NAME at startup (MigrationService), so
    # static analysis cannot see them — same class of problem as passlib above.
    # Every new migrations/mNNN_*.py must be added here.
    + [
        "migrations",
        "migrations.m001_purchase_discounts",
        "migrations.m002_sales_invoice_audit",
        "migrations.m003_supplier_credit_notes",
    ]
)

# Reference docs — harmless to ship, handy for support. (No .ui files: the Qt UI
# is built in code. No fonts: ReportLab uses its built-in Helvetica.)
datas = [
    ("CLAUDE.md", "."),
    ("CHECKLIST.md", "."),
    ("ROADMAP.md", "."),
    # Migration sources shipped alongside for support/inspection; the modules
    # the app actually runs are the frozen copies from hiddenimports.
    (f"{APP_DIR}/migrations", "migrations"),
]

a = Analysis(
    [f"{APP_DIR}/main.py"],
    pathex=[APP_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir: libraries live beside the exe, not inside it
    name="GeminiERP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # desktop GUI: no console window. Startup errors are
                             # logged to logs/gemini_erp.log next to the exe.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="app.ico",        # placeholder — add a real .ico later; not blocking.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GeminiERP",
)
