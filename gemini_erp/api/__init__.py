"""Gemini ERP mobile companion API (Phase 4 M29a).

A thin FastAPI layer over the existing services/ + SQLAlchemy models. It is the
ONLY component a phone talks to — phones never reach SQL Server directly (M28
rule). Read-first: it exposes dashboards/outstanding/stock/invoices/GST returns.
"""
