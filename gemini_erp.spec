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
)

# Reference docs — harmless to ship, handy for support. (No .ui files: the Qt UI
# is built in code. No fonts: ReportLab uses its built-in Helvetica.)
datas = [
    ("CLAUDE.md", "."),
    ("CHECKLIST.md", "."),
    ("ROADMAP.md", "."),
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
