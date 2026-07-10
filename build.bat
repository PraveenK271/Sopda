@echo off
REM ============================================================================
REM  Gemini ERP - Windows build (onedir distribution folder)
REM  Produces dist\GeminiERP\ : a self-contained folder that runs on a clean
REM  machine with no Python installed. Zip it to distribute.
REM
REM  OCR is optional and lives in dist\GeminiERP\ocr_worker\ (a loose 3.13
REM  script + bundled Poppler); the tester creates its venv once - see
REM  ocr_worker\README.md. The main app never needs it to run.
REM ============================================================================
setlocal

REM --- Poppler source (bundled so PDF bills work without a system install) ---
set "POPPLER_BIN=C:\Program Files\Poppler\poppler-26.02.0\Library\bin"

echo Building Gemini ERP...

REM --- Activate the main venv (Python 3.14) ---
call venv\Scripts\activate
if errorlevel 1 (
    echo ERROR: could not activate venv. Create it first: python -m venv venv
    exit /b 1
)

REM --- Clean previous build output ---
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM --- Freeze the app ---
pyinstaller gemini_erp.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

REM --- Assemble the OCR worker folder inside the dist -------------------------
REM Single source of truth: the runner is copied from gemini_erp\services and
REM the deps from requirements-ocr.txt, so they never drift from the app.
set "OCR_DEST=dist\GeminiERP\ocr_worker"
mkdir "%OCR_DEST%"
copy /y "gemini_erp\services\ocr_runner.py" "%OCR_DEST%\ocr_runner.py"
copy /y "requirements-ocr.txt"              "%OCR_DEST%\requirements.txt"
copy /y "ocr_worker\README.md"              "%OCR_DEST%\README.md"

REM --- Bundle Poppler next to the runner (ocr_worker\poppler\bin) -------------
if exist "%POPPLER_BIN%" (
    xcopy /e /i /y "%POPPLER_BIN%" "%OCR_DEST%\poppler\bin"
) else (
    echo WARNING: Poppler not found at "%POPPLER_BIN%".
    echo          PDF bills will not scan until Poppler is bundled or on PATH.
    echo          Image bills ^(JPG/PNG^) are unaffected.
)

REM --- Distribution README at the top of the folder --------------------------
copy /y "DISTRIBUTION_README.md" "dist\GeminiERP\README.md"

echo.
echo ============================================================
echo  Build complete. Output: dist\GeminiERP\
echo  Test it: double-click dist\GeminiERP\GeminiERP.exe
echo  Distribute: zip the dist\GeminiERP folder.
echo ============================================================
pause
endlocal
