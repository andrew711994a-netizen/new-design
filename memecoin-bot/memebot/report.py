"""Αναφορές: τρέχουσα κατάσταση και αποτελέσματα ανά στρατηγική, με έλεγχο «τύχη ή πραγματικό πλεονέκτημα»."""

from __future__ import annotations

import csv
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .engine import local_time
from .price import fmt_eur

MIN_TRADES = 150   # κάτω από αυτό τα αποτελέσματα είναι κυρίως θόρυβος


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def read_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    """Διάστημα 90% για τον μέσο όρο: αν όλο είναι πάνω από 0, το κέρδος μάλλον δεν είναι τύχη."""
    if len(values) < 2:
        return float("nan"), float("nan")
    rnd = random.Random(seed)
    k = len(values)
    means = sorted(sum(rnd.choices(values, k=k)) / k for _ in range(n))
    return means[int(0.05 * n)], means[int(0.95 * n) - 1]


def variant_stats(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status", "ok") == "ok"]
    failed = [r for r in rows if r.get("status") == "failed"]
    pnl = [_f(r["pnl_sol"]) for r in rows]
    pct = [_f(r["pnl_pct"]) for r in ok]
    wins = [_f(r["pnl_sol"]) for r in ok if _f(r["pnl_sol"]) > 0]
    losses = [_f(r["pnl_sol"]) for r in ok if _f(r["pnl_sol"]) <= 0]
    equity = peak = dd = 0.0
    for r in sorted(rows, key=lambda r: r["closed_at"]):
        equity += _f(r["pnl_sol"])
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    lo, hi = bootstrap_ci(pnl)
    cost = sum(_f(r["cost_sol"]) for r in ok)
    return {
        "trades": len(ok), "failed": len(failed), "win_rate": 100 * len(wins) / len(ok) if ok else 0.0,
        "avg_pct": statistics.fmean(pct) if pct else 0.0, "median_pct": statistics.median(pct) if pct else 0.0,
        "pnl_sol": sum(pnl), "roi_pct": 100 * sum(pnl) / cost if cost else 0.0,
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else float("inf") if wins else 0.0,
        "max_dd_sol": dd, "best_pct": max(pct, default=0.0), "worst_pct": min(pct, default=0.0),
        "x2_share": 100 * sum(1 for r in ok if _f(r["peak_multiple"]) >= 2) / len(ok) if ok else 0.0,
        "avg_hold_s": statistics.fmean(_f(r["hold_s"]) for r in ok) if ok else 0.0,
        "ci_lo": lo, "ci_hi": hi, "reasons": Counter(r["exit_reason"] for r in ok).most_common(6),
    }


def peak_capital(rows: list[dict]) -> float:
    """Το μέγιστο ποσό που ήταν δεσμευμένο ταυτόχρονα σε ανοιχτές θέσεις."""
    events = []
    for r in rows:
        if r.get("status", "ok") == "ok":
            events += [(r["opened_at"], 1, _f(r["cost_sol"])), (r["closed_at"], 0, -_f(r["cost_sol"]))]
    now = peak = 0.0
    for _, _, amount in sorted(events):        # στην ίδια στιγμή μετράει πρώτα το κλείσιμο
        now += amount
        peak = max(peak, now)
    return peak


def plain_summary(stats: dict, by_var: dict, eur: float | None) -> list[str]:
    """Τα αποτελέσματα σε απλά λόγια και σε ευρώ."""
    price = f" (τιμή SOL ≈ {eur:.0f} €)" if eur else ""
    out = [f"## Σε απλά λόγια{price}", ""]
    for name, s in stats.items():
        if not s["trades"]:
            continue
        rows = by_var[name]
        avg_cost = statistics.fmean(_f(r["cost_sol"]) for r in rows if r.get("status", "ok") == "ok")
        cap = peak_capital(rows)
        word = "κέρδος" if s["pnl_sol"] > 0 else "ζημιά"
        size = f"~{avg_cost:.2f} SOL" + (f" (≈{avg_cost * eur:.0f} €)" if eur else "")
        money = f"{s['pnl_sol']:+.4f} SOL" + (f" ≈ {fmt_eur(s['pnl_sol'], eur)}" if eur else "")
        out.append(f"- **{name}**: {s['trades']} αγορές των {size}. **{word.capitalize()} {money}** "
                   f"({s['roi_pct']:+.1f}% του ποσού που μπήκε). "
                   f"Χρειάστηκε κεφάλαιο έως {cap:.2f} SOL" + (f" ≈ {cap * eur:.0f} €" if eur else "")
                   + f" ταυτόχρονα· η χειρότερη βουτιά στην πορεία ήταν {s['max_dd_sol']:.4f} SOL"
                   + (f" ≈ {s['max_dd_sol'] * eur:.2f} €." if eur else "."))
    out += ["", "Στα ποσά έχουν ήδη αφαιρεθεί όλες οι χρεώσεις, η καθυστέρηση 1,5″ και το slippage. Στην πράξη "
            "μπορεί να βγουν λίγο χειρότερα (ανταγωνισμός από άλλα bots, συναλλαγές που αποτυγχάνουν όταν το δίκτυο "
            "είναι φορτωμένο). Πόσο ακριβώς, θα το μετρήσει η Φάση 2: εκεί τρέχουν δίπλα δίπλα η πραγματική και "
            "η εικονική εκδοχή της ίδιας στρατηγικής.", ""]
    return out


def verdict(s: dict) -> str:
    if s["trades"] < MIN_TRADES:
        return f"λίγες συναλλαγές (<{MIN_TRADES}): δεν βγαίνει συμπέρασμα ακόμα"
    if s["ci_lo"] > 0:
        return "κερδοφόρα και μάλλον όχι από τύχη"
    if s["ci_hi"] < 0:
        return "ζημιογόνα με σιγουριά"
    return "χωρίς αποδεδειγμένο πλεονέκτημα (μπορεί να είναι τύχη)"


def build_report(rows: list[dict], title: str = "Αποτελέσματα", eur: float | None = None) -> str:
    by_var: dict[str, list] = defaultdict(list)
    for r in rows:
        by_var[f"{r['variant']}" + (" (LIVE)" if r.get("mode") == "live" and "@live" not in r["variant"] else "")].append(r)
    if not rows:
        return f"# {title}\n\nΔεν υπάρχουν ακόμα κλεισμένες συναλλαγές.\n"
    first = min(r["opened_at"] for r in rows)
    last = max(r["closed_at"] for r in rows)
    stats = {name: variant_stats(by_var[name]) for name in sorted(by_var)}
    out = [f"# {title}", "", f"Περίοδος: {first} → {last} (ώρα Ελλάδας). Όλα τα ποσά μετά από ΟΛΕΣ τις χρεώσεις.", ""]
    out += plain_summary(stats, by_var, eur)
    out += ["## Λεπτομέρειες", "",
            "| Στρατηγική | Συναλλαγές | Κερδοφόρες | Μέσο % | Διάμεσο % | Σύνολο SOL | Σύνολο € | Απόδοση κεφ. | "
            "Profit factor | Μέγ. βύθιση SOL | Έφτασαν 2x | Αποτυχ. αγορές | Συμπέρασμα |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for name, s in stats.items():
        pf = "∞" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        out.append(f"| {name} | {s['trades']} | {s['win_rate']:.0f}% | {s['avg_pct']:+.1f}% | {s['median_pct']:+.1f}% | "
                   f"{s['pnl_sol']:+.4f} | {fmt_eur(s['pnl_sol'], eur)} | {s['roi_pct']:+.1f}% | {pf} | "
                   f"{s['max_dd_sol']:.4f} | {s['x2_share']:.0f}% | {s['failed']} | {verdict(s)} |")
    out += ["", "**Πώς διαβάζεται:** «Μέσο %» είναι το μέσο αποτέλεσμα ανά συναλλαγή. Στα meme coins λίγες μεγάλες "
            "επιτυχίες πληρώνουν πολλές μικρές ζημιές, γι' αυτό το διάμεσο είναι συνήθως αρνητικό. Το συμπέρασμα "
            "βγαίνει με bootstrap: αν ακόμα και το απαισιόδοξο άκρο του διαστήματος 90% είναι πάνω από το μηδέν, "
            "το κέρδος μάλλον δεν είναι τύχη.", ""]
    out += ["## Διάστημα 90% για το μέσο αποτέλεσμα ανά συναλλαγή (SOL)", ""]
    for name, s in stats.items():
        if s["ci_lo"] == s["ci_lo"]:
            out.append(f"- **{name}**: από {s['ci_lo']:+.5f} έως {s['ci_hi']:+.5f}")
    out += ["", "## Γιατί έκλεισαν οι θέσεις", ""]
    for name, s in stats.items():
        out.append(f"- **{name}**: " + ", ".join(f"{k} {v}" for k, v in s["reasons"]))
    out += ["", "## Ανά ημέρα (SOL)", ""]
    days = sorted({r["closed_at"][:10] for r in rows})
    out.append("| Ημέρα | " + " | ".join(stats) + " |")
    out.append("|---|" + "---:|" * len(stats))
    for d in days:
        cells = [f"{sum(_f(r['pnl_sol']) for r in by_var[n] if r['closed_at'][:10] == d):+.4f}" for n in stats]
        out.append(f"| {d} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def status_text(engine, cfg: dict, started: float, t: float, connected: bool, eur: float | None = None) -> str:
    st = engine.stats
    streamed = st["συναλλαγές ροής"]
    data_cost = streamed / 10_000 * float(cfg.get("costs", {}).get("data_cost_sol_per_10k_trades", 0.01))
    up = int(t - started)
    mode = "LIVE" if cfg["mode"] == "live" else "PAPER (εικονικά)"
    lines = [f"# Κατάσταση · {local_time(t)} · {mode}", "",
             f"- Σε λειτουργία {up // 3600}ώ {up % 3600 // 60}′ · ροή: {'συνδεδεμένη' if connected else 'ΑΠΟΣΥΝΔΕΔΕΜΕΝΗ'}",
             f"- Νέα tokens: {st['νέα tokens']} · παρακολουθήθηκαν: {st['παρακολουθήθηκαν']} · τώρα: {engine.watching_count()}",
             f"- Συναλλαγές ροής: {streamed} (κόστος δεδομένων ≈ {data_cost:.4f} SOL από την εκκίνηση, "
             f"{engine.data_cost_today(t):.4f} σήμερα) · αποφοιτήσεις: {st['αποφοιτήσεις']}",
             ""]
    if cfg["mode"] == "live":
        g = engine.guard
        lines += [f"- Live σήμερα: {g.trades_today} αγορές · αποτέλεσμα {g.pnl_today:+.4f} SOL"
                  + (f" · **ΔΙΑΚΟΠΗ: {g.halted}**" if g.halted else "") + (" · αρχείο STOP" if g.stop_file else ""), ""]
    lines += ["| Στρατηγική | Κλεισμένες | Κερδοφόρες | Αποτυχ. αγορές | Αποτέλεσμα SOL | Αποτέλεσμα € | Ανοιχτές | "
              "Ανοιχτά κ/ζ SOL |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in engine.summary():
        lines.append(f"| {r['variant']} | {r['closed']} | {r['wins']} | {r['failed']} | {r['pnl_sol']:+.4f} | "
                     f"{fmt_eur(r['pnl_sol'], eur)} | {r['open']} | {r['unrealized_sol']:+.4f} |")
    other = [(k, v) for k, v in st.most_common() if k.startswith(("απόρριψη", "αποτυχ", "live:", "χωρίς θέση", "ακύρωση"))]
    if other:
        lines += ["", "Λεπτομέρειες: " + " · ".join(f"{k}: {v}" for k, v in other)]
    return "\n".join(lines) + "\n"
