; ============================================================================
;  Gemini ERP - Inno Setup installer script
;
;  Produces a single GeminiERP-Setup-<version>.exe from the PyInstaller onedir
;  build in dist\GeminiERP. Per-user install (no admin): the program AND its
;  data (db / documents / logs) live together under the user's LocalAppData,
;  which is writable - so the "data next to the exe" model keeps working and
;  "back up the folder" is still true.
;
;  Build:  run build.bat first (creates dist\GeminiERP), then build_installer.bat
;          (or compile this file in the Inno Setup IDE). Requires Inno Setup 6:
;          https://jrsoftware.org/isdl.php
; ============================================================================

#define MyAppName "Gemini ERP"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Gemini ERP"
#define MyAppExeName "GeminiERP.exe"
#define MyDistDir "dist\GeminiERP"

[Setup]
; AppId uniquely identifies the app for upgrades/uninstall - keep it STABLE
; across versions (never regenerate it, or upgrades install side-by-side).
AppId={{FBC7F949-F3F2-43AF-B94A-AC1CCF792CFA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}

; Per-user install to %LOCALAPPDATA%\Programs\GeminiERP (like VS Code / Slack).
; PrivilegesRequired=lowest => no UAC prompt, no admin rights needed.
DefaultDirName={localappdata}\Programs\GeminiERP
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
AllowNoIcons=yes

; 64-bit build (PyInstaller/PySide6): don't offer to install on 32-bit Windows.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Output installer.
OutputDir=installer
OutputBaseFilename=GeminiERP-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Ship the entire onedir build. Exclude anything the app CREATES at runtime so
; a fresh install never carries a stale database or another user's documents,
; and never bundles the large OCR venv (the user creates that once, post-install).
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
    Excludes: "gemini_erp.db,\logs\*,\documents\*,\ocr_worker\venv_ocr\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove logs on uninstall (regenerated on next run). Deliberately DO NOT list
; gemini_erp.db or documents\ - the user's data survives an uninstall/reinstall.
Type: filesandordirs; Name: "{app}\logs"
