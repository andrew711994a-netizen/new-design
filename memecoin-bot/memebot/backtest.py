"""Επανάληψη της αγοράς από τα καταγεγραμμένα γεγονότα (journal/ticks) με όποιες ρυθμίσεις θέλεις.

Ο ίδιος κώδικας με τη ζωντανή λειτουργία, οπότε το αποτέλεσμα είναι ίδιο με το paper
για τις ίδιες ρυθμίσεις. Με άλλες ρυθμίσεις δείχνει «τι θα είχε γίνει», με έναν περιορισμό:
υπάρχουν τιμές μόνο για τα tokens που παρακολουθούσε τότε το bot.

Για να μην «κουρδίσεις» τις ρυθμίσεις πάνω στην τύχη: δοκίμαζε αλλαγές στις πρώτες μέρες
(train) και κράτα μόνο όσες κρατάνε και στις υπόλοιπες (test), που δεν τις κοίταξες.
"""

from __future__ import annotations

import math
from pathlib import Path

from .engine import Engine
from .journal import Journal, read_ticks
from .report import build_report


def replay(cfg: dict, ticks_dir: Path, since: str = "", until: str = "") -> tuple[list[dict], dict]:
    journal = Journal(None)
    engine = Engine(cfg, journal)
    last = None
    t = 0.0
    for rec in read_ticks(ticks_dir, since, until):
        t, kind, ev = float(rec["t"]), rec["k"], rec["e"]
        if last is None:
            last = math.floor(t)
        if t - last > 900:                   # κενό στην καταγραφή (bot κλειστό)
            engine.on_tick(t - 1)
            last = math.floor(t)
        while last + 1 <= t:
            last += 1
            engine.on_tick(last)
        if kind == "c":
            engine.on_create(ev, t)
        elif kind == "t":
            engine.on_trade(ev, t)
        elif kind == "m":
            engine.on_migration(ev, t)
        elif kind == "meta":
            engine.on_meta(ev.get("mint", ""), ev.get("meta"), t)
        elif kind == "trend":
            engine.on_trending(ev.get("words", {}), t)
        elif kind == "creators":
            engine.narrative.load_creators(ev)
        engine.take_actions()
    if last is not None:
        engine.shutdown_paper(t)
    return journal.trades, dict(engine.stats)


def split_report(rows: list[dict], split: float) -> str:
    days = sorted({r["closed_at"][:10] for r in rows})
    if split <= 0 or split >= 1 or len(days) < 2:
        return build_report(rows, "Backtest")
    cut = days[max(1, min(len(days) - 1, round(len(days) * split))) - 1]
    train = [r for r in rows if r["closed_at"][:10] <= cut]
    test = [r for r in rows if r["closed_at"][:10] > cut]
    return (build_report(train, f"Backtest · TRAIN (έως {cut}): εδώ επιτρέπεται να δοκιμάζεις ρυθμίσεις")
            + "\n" + build_report(test, f"Backtest · TEST (μετά το {cut}): ο κριτής, μην το κουρδίζεις"))
