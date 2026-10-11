"""Τι είναι trending αυτή τη στιγμή έξω από το pump.fun (δωρεάν πηγές, χωρίς κλειδί)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .narrative import STOP

DEFAULT_SOURCES = {
    "google trends": "https://trends.google.com/trending/rss?geo=US",
    "ειδήσεις": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "coingecko": "https://api.coingecko.com/api/v3/search/trending",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (memebot)"}


def keywords(title: str, proper_only: bool) -> set[str]:
    """Λέξεις-κλειδιά από έναν τίτλο. Στις ειδήσεις κρατά μόνο κύρια ονόματα (με κεφαλαίο)."""
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", title):
        if proper_only and not w[0].isupper():
            continue
        lw = w.lower()
        if len(lw) >= 3 and lw not in STOP:
            out.add(lw)
    return out


def parse_rss(text: str, proper_only: bool) -> set[str]:
    out = set()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        title = title.rsplit(" - ", 1)[0] if proper_only else title      # χωρίς «- Πηγή» στις ειδήσεις
        out |= keywords(title, proper_only)
    return out


def parse_coingecko(data: dict) -> set[str]:
    out = set()
    for c in (data or {}).get("coins", []):
        item = c.get("item", {}) if isinstance(c, dict) else {}
        out |= keywords(f"{item.get('name', '')} {item.get('symbol', '')}", False)
    return out


def fetch_trending(sources: dict[str, str] | None = None, timeout: float = 10) -> dict[str, str]:
    """Λέξη → πηγή. Ό,τι αποτύχει απλώς παραλείπεται."""
    found: dict[str, str] = {}
    for label, url in (sources or DEFAULT_SOURCES).items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code != 200:
                continue
            if "coingecko" in url:
                ws = parse_coingecko(r.json())
            else:
                ws = parse_rss(r.text, proper_only="news.google" in url)
        except Exception:
            continue
        for w in ws:
            found.setdefault(w, label)
    return found
