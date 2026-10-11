"""Αναφορές: τρέχουσα κατάσταση και αποτελέσματα ανά στρατηγική, με έλεγχο «τύχη ή πραγματικό πλεονέκτημα»."""

from __future__ import annotations

import csv
import random
import statistics
from collections import defaultdict
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


def reasons(ok: list[dict], top: int = 6) -> list[tuple[str, int, float]]:
    """(λόγος εξόδου, πλήθος, μέσο αποτέλεσμα %): πού κερδίζει και πού χάνει η στρατηγική."""
    groups: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        groups[r["exit_reason"]].append(_f(r["pnl_pct"]))
    return [(k, len(v), statistics.fmean(v)) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]]


def fee_split(rows: list[dict]) -> tuple[int, float, float] | None:
    """(συναλλαγές με γνωστές χρεώσεις, χρεώσεις SOL, αποτέλεσμα πριν τις χρεώσεις SOL)."""
    known = [r for r in rows if str(r.get("fees_sol", "")).strip() != ""]
    if not known:
        return None
    fees = sum(_f(r["fees_sol"]) for r in known)
    return len(known), fees, sum(_f(r["pnl_sol"]) for r in known) + fees


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
        "ci_lo": lo, "ci_hi": hi, "reasons": reasons(ok),
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
        split = fee_split(rows)
        if split:
            n, fees, gross = split
            if gross >= fees:
                meaning = "Κερδίζει αρκετά ώστε να καλύπτει και τις χρεώσεις."
            elif abs(gross) <= 0.15 * fees:
                meaning = ("Πριν τις χρεώσεις βγαίνει περίπου μηδέν: χάνει όσο είναι οι χρεώσεις, "
                           "η επιλογή coins δεν προσθέτει πλεονέκτημα.")
            elif gross > 0:
                meaning = "Πριν τις χρεώσεις κερδίζει, αλλά όχι αρκετά για να τις καλύψει."
            else:
                meaning = "Χάνει και πριν τις χρεώσεις: οι αγορές ή οι έξοδοι χειροτερεύουν το αποτέλεσμα."
            out.append(f"  - Χρεώσεις (στις {n} συναλλαγές που τις έχουν καταγεγραμμένες): {fees:.4f} SOL. "
                       f"Χωρίς αυτές το αποτέλεσμα θα ήταν {gross:+.4f} SOL. {meaning}")
    out += ["", "Στα ποσά έχουν ήδη αφαιρεθεί όλες οι χρεώσεις, η καθυστέρηση 1,5″ και το slippage. Στην πράξη "
            "μπορεί να βγουν λίγο χειρότερα (ανταγωνισμός από άλλα bots, συναλλαγές που αποτυγχάνουν όταν το δίκτυο "
            "είναι φορτωμένο). Πόσο ακριβώς, θα το μετρήσει η Φάση 2: εκεί τρέχουν δίπλα δίπλα η πραγματική και "
            "η εικονική εκδοχή της ίδιας στρατηγικής.", ""]
    return out


VIRAL_BUCKETS = [(0, 0, "0"), (1, 19, "1–19"), (20, 34, "20–34"), (35, 44, "35–44"), (45, 10_000, "45+")]


def viral_table(rows: list[dict]) -> list[str]:
    """Αποτέλεσμα ανά viral score. Προτιμά το baseline_all (αγοράζει τα πάντα, άρα δίκαιη σύγκριση)."""
    scored = [r for r in rows if r.get("status", "ok") == "ok" and str(r.get("viral_score", "")).strip() != ""]
    base = [r for r in scored if r["variant"] == "baseline_all"]
    use, who = (base, "τα coins του baseline_all, που αγοράζει τα πάντα") if len(base) >= 30 else \
        (scored, "όλες οι στρατηγικές μαζί")
    if len(use) < 10:
        return []
    out = ["## Βοηθάει το viral score;", "",
           f"Από {who} ({len(use)} συναλλαγές): πώς πήγαν ανάλογα με το viral score τους.", "",
           "| Viral score | Συναλλαγές | Μέσο αποτέλεσμα | Κερδοφόρες | Έφτασαν 2× | Έφτασαν 5× |",
           "|---|---:|---:|---:|---:|---:|"]
    for lo, hi, label in VIRAL_BUCKETS:
        b = [r for r in use if lo <= _f(r["viral_score"]) <= hi]
        if not b:
            continue
        n = len(b)
        out.append(f"| {label} | {n} | {statistics.fmean(_f(r['pnl_pct']) for r in b):+.1f}% | "
                   f"{100 * sum(_f(r['pnl_sol']) > 0 for r in b) / n:.0f}% | "
                   f"{100 * sum(_f(r['peak_multiple']) >= 2 for r in b) / n:.0f}% | "
                   f"{100 * sum(_f(r['peak_multiple']) >= 5 for r in b) / n:.0f}% |")
    out += ["", "Αν οι γραμμές με υψηλό score έχουν σαφώς καλύτερο αποτέλεσμα και περισσότερα 2×/5× από τις χαμηλές "
            "(με αρκετές δεκάδες συναλλαγές η καθεμία), η ιδέα των viral coins έχει βάση. Αν είναι ίδιες, το όνομα "
            "και τα social από μόνα τους δεν προβλέπουν τίποτα.", ""]
    return out


def verdict(s: dict) -> str:
    if s["trades"] < MIN_TRADES:
        return f"λίγες συναλλαγές (<{MIN_TRADES}): δεν βγαίνει συμπέρασμα ακόμα"
    if s["ci_lo"] > 0:
        return "κερδοφόρα και μάλλον όχι από τύχη"
    if s["ci_hi"] < 0:
        return "ζημιογόνα με σιγουριά"
    return "χωρίς αποδεδειγμένο πλεονέκτημα (μπορεί να είναι τύχη)"


def forced_close(r: dict) -> bool:
    """Εικονική θέση που έκλεισε επειδή σταμάτησε το bot, όχι από τους κανόνες της στρατηγικής."""
    return r.get("status") == "shutdown" or (r.get("mode") == "paper" and r.get("exit_reason") == "τερματισμός bot")


def build_report(rows: list[dict], title: str = "Αποτελέσματα", eur: float | None = None) -> str:
    forced = [r for r in rows if forced_close(r)]
    rows = [r for r in rows if not forced_close(r)]
    note = (f"*{len(forced)} εικονικές θέσεις έκλεισαν αναγκαστικά επειδή σταμάτησε το bot· δεν μετράνε στα "
            f"αποτελέσματα. Όσο λιγότερο το σταματάς, τόσο καθαρότερη η μέτρηση.*\n" if forced else "")
    by_var: dict[str, list] = defaultdict(list)
    for r in rows:
        by_var[f"{r['variant']}" + (" (LIVE)" if r.get("mode") == "live" and "@live" not in r["variant"] else "")].append(r)
    if not rows:
        return f"# {title}\n\nΔεν υπάρχουν ακόμα κλεισμένες συναλλαγές.\n" + (f"\n{note}" if note else "")
    first = min(r["opened_at"] for r in rows)
    last = max(r["closed_at"] for r in rows)
    stats = {name: variant_stats(by_var[name]) for name in sorted(by_var)}
    out = [f"# {title}", "", f"Περίοδος: {first} → {last} (ώρα Ελλάδας). Όλα τα ποσά μετά από ΟΛΕΣ τις χρεώσεις.", ""]
    if note:
        out += [note]
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
    out += [""] + viral_table(rows)
    out += ["## Γιατί έκλεισαν οι θέσεις", ""]
    for name, s in stats.items():
        out.append(f"- **{name}**: " + ", ".join(f"{k} {n} (μ.ό. {avg:+.0f}%)" for k, n, avg in s["reasons"]))
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
    hot = engine.narrative.hot_themes(8)
    if hot:
        lines += ["", "🔥 Θέματα στο pump.fun την τελευταία ώρα (λέξη × πόσα νέα coins): "
                  + ", ".join(f"{w}×{n}" for w, n in hot)]
    if engine.narrative.trending:
        lines += [f"Trending εκτός crypto τώρα: {len(engine.narrative.trending)} λέξεις, π.χ. "
                  + ", ".join(sorted(engine.narrative.trending)[:12])]
    other = [(k, v) for k, v in st.most_common() if k.startswith(("απόρριψη", "αποτυχ", "live:", "χωρίς θέση", "ακύρωση"))]
    if other:
        lines += ["", "Λεπτομέρειες: " + " · ".join(f"{k}: {v}" for k, v in other)]
    return "\n".join(lines) + "\n"
