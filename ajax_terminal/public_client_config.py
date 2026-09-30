"""Public client configuration shipped with THRIVEBERG Terminal.

Only values designed for distribution belong here. Supabase publishable keys
identify a public client and remain constrained by Auth and Row Level Security.
Never add service-role, secret, or third-party market-data keys to this module.
"""

from __future__ import annotations


SUPABASE_URL = "https://zqgyqhptfvcsjvontlbg.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_fGrFOTiLslbummqsFfRDgA_W2tSxJjz"


def bundled_supabase_configuration() -> tuple[str, str]:
    return SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY
