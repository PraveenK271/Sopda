@echo off
REM ============================================================================
REM  Gemini ERP - compile the Windows installer from installer.iss
REM
REM  Prerequisite: run build.bat first so dist\GeminiERP exists, and install
REM  Inno Setup 6 (https://jrsoftware.org/isdl.php).
REM  Output: installer\GeminiERP-Setup-<version>.exe
REM ============================================================================
setlocal

if not exist "dist\GeminiERP\GeminiERP.exe" (
    echo ERROR: dist\GeminiERP not found. Run build.bat first.
    exit /b 1
)

REM --- Locate the Inno Setup command-line compiler (ISCC.exe) ---
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
REM winget installs Inno Setup per-user under LocalAppData.
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
REM Fall back to PATH if a user added it there.
if not defined ISCC (
    where ISCC >nul 2>nul && set "ISCC=ISCC"
)

if not defined ISCC (
    echo ERROR: Inno Setup 6 not found.
    echo Install it from https://jrsoftware.org/isdl.php and re-run this script.
    exit /b 1
)

echo Using compiler: %ISCC%
"%ISCC%" installer.iss
if errorlevel 1 (
    echo ERROR: installer compilation failed.
    exit /b 1
)

echo.
echo ============================================================
echo  Installer built. See the installer\ folder.
echo ============================================================
pause
endlocal
