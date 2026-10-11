"""Τιμή του SOL σε ευρώ, για να φαίνονται τα αποτελέσματα και σε €."""

from __future__ import annotations

import time

import requests

_cache: dict = {"t": 0.0, "eur": None}


def sol_eur(timeout: float = 5.0, max_age_s: float = 600) -> float | None:
    """Από το CoinGecko (με εφεδρεία το Binance). None αν δεν απαντά κανένα."""
    if _cache["eur"] and time.time() - _cache["t"] < max_age_s:
        return _cache["eur"]
    sources = [
        ("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=eur",
         lambda d: d["solana"]["eur"]),
        ("https://api.binance.com/api/v3/ticker/price?symbol=SOLEUR", lambda d: d["price"]),
    ]
    for url, pick in sources:
        try:
            eur = float(pick(requests.get(url, timeout=timeout).json()))
            if eur > 0:
                _cache.update(t=time.time(), eur=eur)
                return eur
        except Exception:
            continue
    return _cache["eur"]


def fmt_eur(sol: float, eur: float | None) -> str:
    return f"{sol * eur:+.2f} €" if eur else "—"
