# -*- coding: utf-8 -*-
"""
live_adapters.py — MR-04 bridge between router policy and live dispatch.

The authoritative live dispatch table lives in the runtime module
(abigail_hardened_enhanced.BACKEND_DISPATCH). This module exposes it to the router
layer WITHOUT importing the heavy runtime at module load — the import is lazy and
guarded, and every consumer may inject its own table for tests (no real calls).
"""


def get_live_dispatch():
    """Return {provider: callable}. Lazily reads the runtime BACKEND_DISPATCH.
    Returns {} if the runtime module is unavailable (e.g. isolated test import)."""
    try:
        import abigail_hardened_enhanced as _runtime
        table = getattr(_runtime, "BACKEND_DISPATCH", None)
        return dict(table) if isinstance(table, dict) else {}
    except Exception:
        return {}


def live_providers():
    return sorted(get_live_dispatch().keys())


def is_live_wired(provider, dispatch_table=None):
    table = dispatch_table if dispatch_table is not None else get_live_dispatch()
    return provider in table
