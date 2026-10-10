"""Metadata του token (περιγραφή, X/Twitter, Telegram, ιστοσελίδα) από το IPFS."""

from __future__ import annotations

import requests

KEYS = ("twitter", "telegram", "website")


def fetch_metadata(uri: str, timeout: float = 3.0) -> dict | None:
    """Επιστρέφει μόνο τα social links, ή None αν αποτύχει η λήψη."""
    if not uri.startswith(("https://", "http://")):
        return None
    try:
        r = requests.get(uri, timeout=timeout, headers={"User-Agent": "memebot/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out = {k: str(data.get(k) or "")[:200] for k in KEYS}
    ext = data.get("extensions")
    if isinstance(ext, dict):                     # κάποια tokens τα έχουν εκεί
        for k in KEYS:
            out[k] = out[k] or str(ext.get(k) or "")[:200]
    return out
