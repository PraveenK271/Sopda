"""Single source of truth for the application version.

Shown in the main window title bar and on the Settings screen, and used to name
the automatic pre-patch database backup. Bump it here (and in installer.iss,
whose Inno Setup preprocessor cannot import Python) for every release.
"""

APP_VERSION = "1.2.0"
