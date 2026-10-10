"""Ημερολόγιο: συναλλαγές, εντολές live, tokens που παρακολουθήθηκαν και τα «ακατέργαστα» γεγονότα.

Τα ακατέργαστα γεγονότα (journal/ticks/ΗΜΕΡΑ.jsonl) επιτρέπουν να ξαναπαιχτεί η αγορά
με άλλες ρυθμίσεις: python -m memebot backtest
"""

from __future__ import annotations

import csv
import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

TRADE_FIELDS = ["closed_at", "variant", "mode", "status", "mint", "symbol", "name", "opened_at", "hold_s",
                "cost_sol", "proceeds_sol", "pnl_sol", "pnl_pct", "peak_multiple", "entry_mcap_sol",
                "exit_mcap_sol", "sells", "exit_reason", "entry_age_s", "uniq_buyers", "net_sol", "dev_pct",
                "top_holder_pct", "twitter", "telegram"]
TOKEN_FIELDS = ["mint", "symbol", "name", "creator", "created_at", "watched_s", "trades", "peak_mcap_sol",
                "end_mcap_sol", "migrated", "age_s", "mcap_sol", "uniq_buyers", "buys", "sells", "net_sol",
                "dev_buy_sol", "dev_pct", "dev_sold_pct", "top_holder_pct", "twitter", "telegram", "website"]
ORDER_FIELDS = ["time", "variant", "kind", "mint", "symbol", "amount", "ok", "sol_delta", "token_delta",
                "signature", "error", "reason"]


class Journal:
    def __init__(self, folder: Path | None, record_ticks: bool = False, trades_file: str = "trades.csv"):
        self.dir = folder
        self.record_ticks = record_ticks and folder is not None
        self.trades_file = trades_file
        self.trades: list[dict] = []          # και στη μνήμη, για backtest/σύνοψη
        self._tick_fh = None
        self._tick_day = ""
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            if self.record_ticks:
                (folder / "ticks").mkdir(exist_ok=True)
                self._compress_old_ticks()

    def _append(self, name: str, fields: list[str], row: dict) -> None:
        if self.dir is None:
            return
        f = self.dir / name
        new = not f.exists()
        with f.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    def trade(self, row: dict) -> None:
        self.trades.append(row)
        self._append(self.trades_file, TRADE_FIELDS, row)

    def token(self, row: dict) -> None:
        self._append("tokens.csv", TOKEN_FIELDS, row)

    def order(self, row: dict) -> None:
        self._append("orders.csv", ORDER_FIELDS, row)

    def migration(self, mint: str, when: str) -> None:
        self._append("migrations.csv", ["time", "mint"], {"time": when, "mint": mint})

    # ── ακατέργαστα γεγονότα ──
    def tick(self, kind: str, ev: dict, t: float) -> None:
        if not self.record_ticks:
            return
        day = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        if day != self._tick_day:
            if self._tick_fh:
                self._tick_fh.close()
            self._tick_day = day
            self._tick_fh = (self.dir / "ticks" / f"{day}.jsonl").open("a", encoding="utf-8")
        self._tick_fh.write(json.dumps({"t": round(t, 3), "k": kind, "e": ev}, separators=(",", ":")) + "\n")

    def flush(self) -> None:
        if self._tick_fh:
            self._tick_fh.flush()

    def close(self) -> None:
        if self._tick_fh:
            self._tick_fh.close()
            self._tick_fh = None

    def _compress_old_ticks(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for f in sorted((self.dir / "ticks").glob("*.jsonl")):
            if f.stem < today:
                with f.open("rb") as src, gzip.open(f.with_suffix(".jsonl.gz"), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                f.unlink()

    # ── κατάσταση ──
    def write_text(self, name: str, text: str) -> None:
        if self.dir is not None:
            (self.dir / name).write_text(text, encoding="utf-8")

    def save_json(self, name: str, data) -> None:
        if self.dir is not None:
            tmp = self.dir / (name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.dir / name)

    def load_json(self, name: str, default=None):
        f = self.dir / name if self.dir is not None else None
        if f is None or not f.exists():
            return default
        return json.loads(f.read_text(encoding="utf-8"))


def read_ticks(folder: Path, since: str = "", until: str = ""):
    """Γεγονότα με χρονολογική σειρά από journal/ticks (*.jsonl και *.jsonl.gz)."""
    files = sorted(set(folder.glob("*.jsonl")) | set(folder.glob("*.jsonl.gz")), key=lambda f: f.name)
    for f in files:
        day = f.name[:10]
        if (since and day < since) or (until and day > until):
            continue
        opener = gzip.open if f.suffix == ".gz" else open
        try:
            with opener(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue      # μισογραμμένη γραμμή από απότομο κλείσιμο
        except (EOFError, OSError):
            continue
