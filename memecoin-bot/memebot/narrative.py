"""«Viral score»: πόσο πιθανό είναι ένα νέο coin να «πιάσει», πέρα από τη ροή χρημάτων.

Κοιτάει αυτό που κοιτάει ένας έμπειρος trader στα πρώτα δευτερόλεπτα:
  - Θέμα της στιγμής εκτός crypto: το όνομα ταιριάζει με κάτι που είναι trending
    (Google Trends, ειδήσεις, trending στο CoinGecko).
  - Θέμα της στιγμής μέσα στο pump.fun: πολλά νέα coins με την ίδια λέξη την τελευταία
    ώρα σημαίνει ότι υπάρχει «αφήγημα». Συνήθως κερδίζει το πρώτο ή το δυνατότερο
    (ο «αρχηγός»), όχι οι αντιγραφές.
  - Σύνδεσμος σε tweet πολύ γνωστού λογαριασμού (π.χ. Elon Musk): το coin «πατάει» πάνω του.
  - Κοινότητα: δικός του λογαριασμός X, Telegram, ιστοσελίδα.
  - Δημιουργός που έχει ξαναβγάλει coin που αποφοίτησε.

Όλα αυτά είναι υποθέσεις: αν το score προβλέπει κάτι, θα το δείξουν τα δεδομένα.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict, deque
from urllib.parse import urlparse

STOP = set("""
the a an of and or to in on for at by with from as is it its this that be are was were will can not no yes
you your our we they he she his her him them my me i us all any new old one two top big best real first last
just more most only out up down off over get got how why what who when where which official coin token tokens
sol solana pump fun pumpfun meme memes memecoin inu ai bot app dao defi nft web3 crypto community launch
money moon rich buy sell hold gem today news says said after before about into amid could would should may
than then there here have has had been being does did done make made like love life time day days week year
years world people man men woman women kid kids boy girl baby big small good bad great little king queen
monday tuesday wednesday thursday friday saturday sunday january february march april june july august
september october november december live watch video videos photo photos report update updates breaking
latest full free win wins game games show shows season episode score scores vs tonight tomorrow yesterday
""".split())

DEFAULT_INFLUENCERS = [
    "elonmusk", "realdonaldtrump", "potus", "whitehouse", "cz_binance", "vitalikbuterin", "saylor", "mrbeast",
    "kanyewest", "snoopdogg", "kimkardashian", "taylorswift13", "cristiano", "neymarjr", "jakepaul",
    "loganpaul", "ishowspeed", "andrewtate", "billgates", "jeffbezos", "markzuckerberg", "sama", "solana",
    "aeyakovenko", "rajgokal", "pumpdotfun", "a1lon9", "binance", "coinbase", "brian_armstrong",
]

LINK = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(/status/\d+)?", re.I)


def words(*texts: str) -> set[str]:
    out = set()
    for txt in texts:
        txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
        for w in re.findall(r"[a-z0-9]+", txt):
            if len(w) >= 3 and not w.isdigit() and w not in STOP:
                out.add(w)
    return out


def x_link(url: str) -> tuple[str, bool]:
    """(λογαριασμός X, αν είναι σύνδεσμος σε συγκεκριμένο tweet)."""
    m = LINK.search(url or "")
    return (m.group(1).lower(), bool(m.group(2))) if m else ("", False)


def real_website(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower() if url and "://" in url else ""
    return bool(host) and not any(h in host for h in ("x.com", "twitter.com", "t.me", "telegram", "pump.fun"))


class Narrative:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.w = {"trend": 30, "theme_leader": 25, "theme": 10, "influencer": 15, "own_x": 5, "telegram": 5,
                  "website": 5, "creator_graduated": 20, **cfg.get("weights", {})}
        self.window_s = float(cfg.get("theme_window_s", 3600))
        self.min_copies = int(cfg.get("min_theme_copies", 3))
        self.influencers = {h.lower() for h in cfg.get("influencers", DEFAULT_INFLUENCERS)}
        self.recent: deque = deque()                  # (χρόνος, mint, λέξεις)
        self.count: Counter = Counter()               # λέξη → πόσα coins την έχουν μέσα στο παράθυρο
        self.by_word: dict[str, set] = defaultdict(set)
        self.volume: Counter = Counter()              # mint → SOL αγορών (όσων παρακολουθούμε)
        self.trending: dict[str, str] = {}            # λέξη → από πού (google trends, ειδήσεις, …)
        self.creator_of: dict[str, tuple[str, float]] = {}
        self.creator_grads: Counter = Counter()       # δημιουργός → coins του που αποφοίτησαν

    # ── γεγονότα ──
    def on_create(self, mint: str, creator: str, ws: set[str], t: float) -> None:
        self._prune(t)
        self.recent.append((t, mint, ws))
        for w in ws:
            self.count[w] += 1
            self.by_word[w].add(mint)
        if creator:
            self.creator_of[mint] = (creator, t)

    def on_buy(self, mint: str, sol: float) -> None:
        self.volume[mint] += sol

    def on_migration(self, mint: str) -> None:
        creator = self.creator_of.get(mint, ("", 0))[0]
        if creator:
            self.creator_grads[creator] += 1

    def load_creators(self, saved: dict) -> None:
        for creator, n in (saved or {}).items():
            self.creator_grads[creator] = max(self.creator_grads.get(creator, 0), int(n))

    def hot_themes(self, top: int = 5) -> list[tuple[str, int]]:
        """Οι λέξεις που εμφανίζονται στα περισσότερα νέα coins μέσα στο παράθυρο (π.χ. τελευταία ώρα)."""
        return [(w, n) for w, n in self.count.most_common(top) if n >= self.min_copies]

    def set_trending(self, trending: dict[str, str]) -> None:
        if trending:
            self.trending = dict(trending)

    def _prune(self, t: float) -> None:
        while self.recent and self.recent[0][0] < t - self.window_s:
            _, mint, ws = self.recent.popleft()
            for w in ws:
                self.count[w] -= 1
                self.by_word[w].discard(mint)
                if self.count[w] <= 0:
                    del self.count[w]
                    self.by_word.pop(w, None)
            self.volume.pop(mint, None)
        if len(self.creator_of) > 60_000:             # ~2 μέρες launches· τα παλιά δεν χρειάζονται
            cutoff = t - 86400
            self.creator_of = {m: ct for m, ct in self.creator_of.items() if ct[1] >= cutoff}

    # ── βαθμολογία ──
    def trend_match(self, ws: set[str]) -> str:
        for w in sorted(ws):
            if w in self.trending:
                return w
            for tw in self.trending:                  # π.χ. «trumpcat» περιέχει «trump»
                if len(tw) >= 4 and tw in w:
                    return tw
        return ""

    def theme(self, mint: str, ws: set[str]) -> tuple[str, int, bool]:
        """(λέξη-θέμα, πόσα άλλα coins την έχουν, αν αυτό είναι ο «αρχηγός» σε όγκο)."""
        best, copies = "", 0
        for w in ws:
            n = self.count.get(w, 0) - (1 if mint in self.by_word.get(w, ()) else 0)
            if n > copies:
                best, copies = w, n
        if not best or copies < self.min_copies:
            return best, copies, False
        mine = self.volume.get(mint, 0.0)
        leader = mine > 0 and all(self.volume.get(m, 0.0) <= mine for m in self.by_word.get(best, ()) if m != mint)
        return best, copies, leader

    def score(self, tok) -> tuple[int, str]:
        """(βαθμός 0–100+, εξήγηση) για ένα TokenState."""
        ws = tok.words
        parts, why = 0, []
        trend = self.trend_match(ws)
        if trend:
            parts += self.w["trend"]
            why.append(f"trend:{trend}({self.trending.get(trend, '')})")
        word, copies, leader = self.theme(tok.mint, ws)
        if copies >= self.min_copies:
            parts += self.w["theme_leader"] if leader else self.w["theme"]
            why.append(f"θέμα:{word}×{copies}" + (" αρχηγός" if leader else ""))
        meta = tok.meta or {}
        handle, is_tweet = x_link(str(meta.get("twitter", "")))
        if handle and handle in self.influencers:
            parts += self.w["influencer"]
            why.append(f"tweet:@{handle}")
        elif handle and not is_tweet:
            parts += self.w["own_x"]
            why.append("X")
        if str(meta.get("telegram", "")).strip():
            parts += self.w["telegram"]
            why.append("TG")
        if real_website(str(meta.get("website", ""))):
            parts += self.w["website"]
            why.append("web")
        if tok.creator and self.creator_grads.get(tok.creator, 0) > 0:
            parts += self.w["creator_graduated"]
            why.append(f"δημιουργός με {self.creator_grads[tok.creator]} επιτυχία")
        return parts, " · ".join(why)
