"""Εντολές:

  python -m memebot             εκκίνηση (paper ή live, από το config.json)
  python -m memebot check       έλεγχος εγκατάστασης (ροή, κλειδί API, ειδοποιήσεις, πορτοφόλι)
  python -m memebot report      αναφορά αποτελεσμάτων από το journal/trades.csv
  python -m memebot backtest    επανάληψη της αγοράς από τα journal/ticks με τις τρέχουσες ρυθμίσεις
  python -m memebot costs       πόσο κοστίζει κάθε αγορά+πώληση ανά μέγεθος θέσης
  python -m memebot wallet      διεύθυνση και υπόλοιπο του πορτοφολιού live
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import JOURNAL, load_config, load_env


def main() -> None:
    for stream in (sys.stdout, sys.stderr):           # ελληνικά και στα παράθυρα των Windows
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="memebot", description="Bot για meme coins του pump.fun")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "check", "report", "backtest", "costs", "wallet"])
    ap.add_argument("--config", type=Path, help="άλλο αρχείο ρυθμίσεων (για backtest)")
    ap.add_argument("--since", default="", help="από ημερομηνία ΕΕΕΕ-ΜΜ-ΗΗ")
    ap.add_argument("--until", default="", help="έως ημερομηνία ΕΕΕΕ-ΜΜ-ΗΗ")
    ap.add_argument("--split", type=float, default=0.7, help="backtest: μερίδιο ημερών για train (0 = χωρίς)")
    args = ap.parse_args()

    load_env()
    cfg = load_config(args.config)

    if args.command == "run":
        from .runner import run
        try:
            asyncio.run(run(cfg))
        except KeyboardInterrupt:
            pass
    elif args.command == "check":
        from .runner import check
        asyncio.run(check(cfg))
    elif args.command == "report":
        from .report import build_report, read_trades
        rows = [r for r in read_trades(JOURNAL / "trades.csv")
                if (not args.since or r["closed_at"][:10] >= args.since)
                and (not args.until or r["closed_at"][:10] <= args.until)]
        from .price import sol_eur
        text = build_report(rows, eur=sol_eur())
        (JOURNAL / "report.md").parent.mkdir(exist_ok=True)
        (JOURNAL / "report.md").write_text(text, encoding="utf-8")
        print(text)
        print(f"(αποθηκεύτηκε στο {JOURNAL / 'report.md'})")
    elif args.command == "backtest":
        from .backtest import replay, split_report
        rows, stats = replay(cfg, JOURNAL / "ticks", args.since, args.until)
        text = split_report(rows, args.split)
        text += "\nΓεγονότα: " + " · ".join(f"{k}: {v}" for k, v in sorted(stats.items())) + "\n"
        (JOURNAL / "backtest.md").write_text(text, encoding="utf-8")
        print(text)
    elif args.command == "costs":
        from .curve import Costs, round_trip_cost_pct
        c = Costs.from_dict(cfg.get("costs"))
        print("Κόστος αγοράς + άμεσης πώλησης (χωρίς κίνηση τιμής), με τις ρυθμίσεις του config.json:")
        for size in (0.02, 0.05, 0.1, 0.25, 0.5, 1.0):
            print(f"  θέση {size:>5} SOL → {round_trip_cost_pct(size, c):5.1f}%")
        print("Το token πρέπει να ανέβει τουλάχιστον τόσο μόνο για να μη χάσεις.")
    elif args.command == "wallet":
        from .curve import Costs
        from .live import LiveBroker
        b = LiveBroker(cfg.get("live", {}), Costs.from_dict(cfg.get("costs")))
        print(f"Πορτοφόλι bot: {b.pubkey}\nΥπόλοιπο: {b.rpc.balance(b.pubkey):.4f} SOL")


if __name__ == "__main__":
    main()
