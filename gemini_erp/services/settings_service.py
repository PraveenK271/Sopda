"""Read/update the company profile (Settings).

All business logic for the single-row CompanyProfile lives here (Service Layer
pattern): the UI and the report/PDF code only read the dict this returns. On
first use the profile row is seeded from the ``reports/company_info`` defaults
so an existing database (or a brand-new one) always has something to print.
"""

import logging

from sqlalchemy import false

from database import get_session
from models import CompanyProfile
from reports import company_info

logger = logging.getLogger(__name__)


def _default_terms() -> str:
    return "\n".join(company_info.TERMS_AND_CONDITIONS)


# Seed values for the very first run, taken from the old hardcoded placeholder.
_DEFAULTS = {
    "name": company_info.COMPANY_NAME,
    "address": company_info.COMPANY_ADDRESS,
    "mobile": company_info.COMPANY_MOBILE,
    "gstin": company_info.COMPANY_GSTIN,
    "state": company_info.COMPANY_STATE,
    "bank_name": company_info.BANK_NAME,
    "bank_account_no": company_info.BANK_ACCOUNT_NO,
    "bank_ifsc": company_info.BANK_IFSC,
    "bank_branch": company_info.BANK_BRANCH,
    "terms": _default_terms(),
    "logo_path": None,
}

# Fields the UI/service may edit. ``terms`` is handled specially (list<->text).
_TEXT_FIELDS = (
    "name", "address", "mobile", "gstin", "state",
    "bank_name", "bank_account_no", "bank_ifsc", "bank_branch", "logo_path",
)


def ensure_profile(session) -> CompanyProfile:
    """Return the single company-profile row, creating it from defaults if absent.

    Idempotent — safe to call on every app start (like ensure_system_accounts).
    Commits on the passed-in session when it creates the row.
    """
    profile = (
        session.query(CompanyProfile)
        .filter(CompanyProfile.is_deleted == false())
        .order_by(CompanyProfile.id)
        .first()
    )
    if profile is None:
        profile = CompanyProfile(**_DEFAULTS)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        logger.info("Seeded default company profile")
    return profile


class SettingsService:
    """Read and update the company profile used across invoices and reports."""

    def get_profile(self) -> dict:
        """Return the company profile as a plain dict (``terms`` as a list)."""
        session = get_session()
        try:
            profile = ensure_profile(session)
            return self._to_dict(profile)
        except Exception:
            logger.exception("Failed to read company profile")
            raise
        finally:
            session.close()

    def update_profile(self, data: dict, modified_by: str | None = None) -> dict:
        """Update the company profile from ``data`` and return the saved dict.

        ``data`` may contain any of the text fields plus ``terms`` (a list of
        strings OR a newline-separated string). Missing keys are left unchanged.
        """
        session = get_session()
        try:
            profile = ensure_profile(session)
            for field in _TEXT_FIELDS:
                if field in data:
                    value = data[field]
                    setattr(profile, field, value.strip() if isinstance(value, str) else value)
            if "terms" in data:
                profile.terms = self._terms_to_text(data["terms"])
            profile.modified_by = modified_by
            session.commit()
            session.refresh(profile)
            logger.info("Updated company profile")
            return self._to_dict(profile)
        except Exception:
            session.rollback()
            logger.exception("Failed to update company profile")
            raise
        finally:
            session.close()

    @staticmethod
    def _terms_to_text(terms) -> str:
        if isinstance(terms, str):
            return terms
        return "\n".join(t for t in terms)

    @staticmethod
    def _to_dict(profile: CompanyProfile) -> dict:
        terms_text = profile.terms or ""
        return {
            "id": profile.id,
            "name": profile.name,
            "address": profile.address,
            "mobile": profile.mobile,
            "gstin": profile.gstin,
            "state": profile.state,
            "bank_name": profile.bank_name,
            "bank_account_no": profile.bank_account_no,
            "bank_ifsc": profile.bank_ifsc,
            "bank_branch": profile.bank_branch,
            "terms": [line for line in terms_text.splitlines() if line.strip()],
            "logo_path": profile.logo_path,
        }
