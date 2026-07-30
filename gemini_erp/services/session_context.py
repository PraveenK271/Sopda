"""Holds the currently logged-in user for the running app process.

A single-user desktop app has exactly one logged-in user per process, so a
simple class-level holder is enough. Services never read this — they still take
an explicit created_by — which keeps them testable and unaware of the UI. The UI
call sites read get_username() and pass it in.
"""

from __future__ import annotations


class SessionContext:
    _current_user = None

    @classmethod
    def set_user(cls, user) -> None:
        cls._current_user = user

    @classmethod
    def get_user(cls):
        return cls._current_user

    @classmethod
    def get_username(cls) -> str:
        """The logged-in username, or 'system' if nobody is logged in."""
        if cls._current_user is None:
            return "system"
        return cls._current_user.username

    @classmethod
    def clear(cls) -> None:
        cls._current_user = None
