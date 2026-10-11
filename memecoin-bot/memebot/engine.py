"""Ο πυρήνας του bot: διαλέγει ποια tokens παρακολουθεί, ανοίγει και κλείνει θέσεις.

Δεν ξέρει τίποτα για δίκτυο ή ρολόι: παίρνει γεγονότα με τον χρόνο τους και αφήνει
«ενέργειες» (εγγραφές, εντολές, ειδοποιήσεις) που τις εκτελεί ο runner. Έτσι ο ίδιος
κώδικας τρέχει ζωντανά, εικονικά και σε επανάληψη ιστορικού (backtest).

Εικονικές εκτελέσεις (paper): η εντολή «προσγειώνεται» latency_ms αργότερα, στην τιμή
που έχει τότε το token, με όλες τις χρεώσεις. Αν η τιμή έχει φύγει πέρα από το slippage,
η εντολή αποτυγχάνει και πληρώνεται μόνο η χρέωση δικτύου, όπως στην πραγματικότητα.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .curve import Costs, simulate_buy, simulate_sell
from .market import TokenState
from .strategy import Variant

ATHENS = ZoneInfo("Europe/Athens")


def local_time(t: float) -> str:
    return datetime.fromtimestamp(t, ATHENS).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Order:
    id: int
    kind: str                 # "buy" ή "sell"
    variant: str
    mint: str
    symbol: str
    t: float
    decision_price: float
    amount_sol: float = 0.0
    frac: float = 1.0
    final: bool = True
    reason: str = ""
    slippage_pct: float = 15.0
    live: bool = False
    feats: dict = field(default_factory=dict)


@dataclass
class Position:
    variant: str
    mint: str
    symbol: str
    name: str
    live: bool
    opened_t: float
    entry_price: float
    tokens: float
    cost_sol: float
    entry_mcap: float
    feats: dict = field(default_factory=dict)
    peak_price: float = 0.0
    realized_sol: float = 0.0
    tp_done: bool = False
    sells: int = 0
    pending: Order | None = None
    sell_attempt: int = 0
    next_try_t: float = 0.0


@dataclass
class LiveResult:
    ok: bool
    sol_delta: float = 0.0       # αλλαγή SOL στο πορτοφόλι (αρνητική στην αγορά)
    token_delta: float = 0.0     # αλλαγή tokens στο πορτοφόλι
    signature: str = ""
    error: str = ""
    exception: bool = False      # σφάλμα συστήματος (όχι απλή απόρριψη λόγω slippage)


class LiveGuard:
    """Φρένα για τα πραγματικά χρήματα: όριο συναλλαγών/ζημιάς ανά μέρα, συνεχόμενα σφάλματα."""

    def __init__(self, live_cfg: dict):
        self.max_open = int(live_cfg.get("max_open_positions", 2))
        self.max_trades = int(live_cfg.get("max_trades_per_day", 20))
        self.loss_limit = float(live_cfg.get("daily_loss_limit_sol", 0.2))
        self.max_errors = int(live_cfg.get("max_consecutive_errors", 3))
        self.day = None
        self.trades_today = 0
        self.pnl_today = 0.0
        self.errors = 0
        self.halted = ""          # λόγος μόνιμης διακοπής (ως την επανεκκίνηση)
        self.stop_file = False    # υπάρχει αρχείο STOP

    def _roll(self, t: float) -> None:
        day = datetime.fromtimestamp(t, ATHENS).date()
        if day != self.day:
            self.day, self.trades_today, self.pnl_today = day, 0, 0.0

    def can_open(self, t: float, open_now: int) -> tuple[bool, str]:
        self._roll(t)
        if self.halted:
            return False, self.halted
        if self.stop_file:
            return False, "αρχείο STOP"
        if open_now >= self.max_open:
            return False, "μέγιστες θέσεις"
        if self.trades_today >= self.max_trades:
            return False, "όριο συναλλαγών ημέρας"
        if self.pnl_today <= -self.loss_limit:
            return False, "όριο ζημιάς ημέρας"
        return True, ""

    def on_order(self, t: float) -> None:
        self._roll(t)
        self.trades_today += 1

    def on_close(self, pnl: float, t: float) -> None:
        self._roll(t)
        self.pnl_today += pnl

    def on_error(self) -> bool:
        self.errors += 1
        if self.errors >= self.max_errors and not self.halted:
            self.halted = f"{self.errors} συνεχόμενα σφάλματα"
            return True
        return False

    def on_success(self) -> None:
        self.errors = 0


@dataclass
class Actions:
    subscribe: list = field(default_factory=list)
    unsubscribe: list = field(default_factory=list)
    meta: list = field(default_factory=list)          # (mint, uri)
    live_orders: list = field(default_factory=list)
    notes: list = field(default_factory=list)         # (τίτλος, κείμενο) για ειδοποίηση


class Engine:
    def __init__(self, cfg: dict, journal, live_variant: str | None = None, own_wallet: str = ""):
        self.cfg = cfg
        self.costs = Costs.from_dict(cfg.get("costs"))
        self.feed_cfg = cfg.get("feed", {})
        self.pf = cfg.get("prefilter", {})
        self.fetch_meta = bool(cfg.get("metadata", {}).get("fetch", True))
        self.journal = journal
        self.own = own_wallet
        all_variants = [Variant.from_dict(d) for d in cfg["strategies"]]
        self.variants: dict[str, Variant] = {v.name: v for v in all_variants if v.enabled}
        live_cfg = cfg.get("live", {})
        self.guard = LiveGuard(live_cfg)
        if live_variant:
            base = next((v for v in all_variants if v.name == live_variant), None)
            if base is None:
                raise SystemExit(f"Η στρατηγική «{live_variant}» του live δεν υπάρχει στο config.json.")
            lv = copy.deepcopy(base)
            lv.name, lv.live, lv.enabled = base.name + "@live", True, True
            lv.trade_sol = float(live_cfg.get("trade_sol", 0.05))
            lv.max_open = self.guard.max_open
            self.variants[lv.name] = lv
        self.needs_meta = self.fetch_meta and (bool(self.pf.get("require_socials"))
                                               or any(v.needs_meta for v in self.variants.values()))
        self.tokens: dict[str, TokenState] = {}
        self.positions: dict[tuple, Position] = {}
        self.entered: set[tuple] = set()
        self.pending: list[Order] = []           # εικονικές εντολές σε αναμονή
        self.pending_live_buys: dict[tuple, Order] = {}
        self.creators: dict[str, deque] = {}
        self.stats: Counter = Counter()
        self.results: dict[str, Counter] = {name: Counter() for name in self.variants}
        self.actions = Actions()
        self._ids = itertools.count(1)
        self._last_prune = 0.0
        self.last_t = 0.0
        self.data_day = None
        self.data_trades_today = 0

    # ── γεγονότα ──
    def on_create(self, ev: dict, t: float) -> None:
        self.last_t = t
        self.stats["νέα tokens"] += 1
        mint = str(ev.get("mint", ""))
        if not mint or mint in self.tokens:
            return
        tok = TokenState.from_create(ev, t)
        ok, why = self._prefilter(tok, t)
        if not ok:
            self.stats[f"απόρριψη: {why}"] += 1
            return
        tok.passed_prefilter = True
        if self.needs_meta and tok.uri:
            self.actions.meta.append((mint, tok.uri))
        else:
            tok.meta_done = True
        if self.pf.get("require_socials") and not tok.meta_done:
            self.tokens[mint] = tok          # περιμένει τα metadata πριν το παρακολουθήσουμε
            return
        if self.pf.get("require_socials") and not tok.has_socials():
            self.stats["απόρριψη: χωρίς social"] += 1
            return
        self._watch(tok, t)

    def on_meta(self, mint: str, meta: dict | None, t: float) -> None:
        self.last_t = t
        tok = self.tokens.get(mint)
        if tok is None or tok.meta_done:
            return
        tok.meta, tok.meta_done = meta or {}, True
        if tok.watching:
            self._consider_entries(tok, t)
            return
        if self.pf.get("require_socials") and not tok.has_socials():
            self.stats["απόρριψη: χωρίς social"] += 1
            del self.tokens[mint]
            return
        self._watch(tok, t)

    def on_trade(self, ev: dict, t: float) -> None:
        self.last_t = t
        self.stats["συναλλαγές ροής"] += 1
        self._roll_data_day(t)
        self.data_trades_today += 1
        tok = self.tokens.get(str(ev.get("mint", "")))
        if tok is None or not tok.watching:
            return
        tok.apply_trade(ev, t)
        self._step(tok, t)

    def on_migration(self, ev: dict, t: float) -> None:
        self.last_t = t
        self.stats["αποφοιτήσεις"] += 1
        tok = self.tokens.get(str(ev.get("mint", "")))
        if tok is None:
            return
        tok.migrated = True
        self._fill_pending(tok, t, force=True)
        self._manage(tok, t)

    def on_tick(self, t: float) -> None:
        self.last_t = t
        for tok in list(self.tokens.values()):
            if not tok.watching:
                if t - tok.created_t > 20:               # τα metadata δεν ήρθαν ποτέ
                    self.stats["απόρριψη: χωρίς metadata"] += 1
                    del self.tokens[tok.mint]
                continue
            self._step(tok, t)
            self._maybe_unwatch(tok, t)
        if t - self._last_prune > 600:
            self._last_prune = t
            for c in [c for c, dq in self.creators.items() if not dq or dq[-1] < t - 86400]:
                del self.creators[c]

    def _step(self, tok: TokenState, t: float) -> None:
        self._fill_pending(tok, t)
        self._manage(tok, t)
        self._consider_entries(tok, t)

    # ── επιλογή tokens ──
    def _roll_data_day(self, t: float) -> None:
        day = datetime.fromtimestamp(t, ATHENS).date()
        if day != self.data_day:
            self.data_day, self.data_trades_today = day, 0

    def data_cost_today(self, t: float) -> float:
        self._roll_data_day(t)
        return self.data_trades_today / 10_000 * self.costs.data_cost_sol_per_10k_trades

    @staticmethod
    def sampled(mint: str, pct: float) -> bool:
        """Σταθερή (ίδια σε κάθε επανάληψη) επιλογή pct% των tokens."""
        return pct >= 100 or int(hashlib.md5(mint.encode()).hexdigest()[:8], 16) % 10_000 < pct * 100

    def _prefilter(self, tok: TokenState, t: float) -> tuple[bool, str]:
        pf = self.pf
        dq = self.creators.setdefault(tok.creator, deque())
        dq.append(t)
        while dq and dq[0] < t - 86400:
            dq.popleft()
        if tok.pool not in pf.get("pools", ["pump"]):
            return False, "άλλη πλατφόρμα"
        if not float(pf.get("min_dev_buy_sol", 0)) <= tok.dev_buy_sol <= float(pf.get("max_dev_buy_sol", 1e9)):
            return False, "αγορά δημιουργού"
        if tok.dev_pct() > float(pf.get("max_dev_pct", 100)):
            return False, "πολλά στον δημιουργό"
        if tok.creator and len(dq) > int(pf.get("max_tokens_per_creator_24h", 1_000_000)):
            return False, "κατά συρροή δημιουργός"
        text = f"{tok.name} {tok.symbol}".lower()
        if any(w.lower() in text for w in pf.get("blocked_words", [])):
            return False, "όνομα"
        if not self.sampled(tok.mint, float(self.feed_cfg.get("sample_pct", 100))):
            return False, "εκτός δείγματος"
        if self.data_cost_today(t) >= float(self.feed_cfg.get("max_data_sol_per_day", 1e9)):
            return False, "όριο κόστους δεδομένων ημέρας"
        return True, ""

    def watching_count(self) -> int:
        return sum(1 for tk in self.tokens.values() if tk.watching)

    def _watch(self, tok: TokenState, t: float) -> None:
        if self.watching_count() >= int(self.feed_cfg.get("max_watching", 60)):
            self.stats["χωρίς θέση παρακολούθησης"] += 1
            self.tokens.pop(tok.mint, None)
            return
        tok.watching, tok.watch_start_t = True, t
        self.tokens[tok.mint] = tok
        self.actions.subscribe.append(tok.mint)
        self.stats["παρακολουθήθηκαν"] += 1
        self._consider_entries(tok, t)

    def _busy(self, mint: str) -> bool:
        return (any(k[1] == mint for k in self.positions) or any(o.mint == mint for o in self.pending)
                or any(k[1] == mint for k in self.pending_live_buys))

    def _maybe_unwatch(self, tok: TokenState, t: float) -> None:
        if self._busy(tok.mint):
            return
        age = tok.age(t)
        hopeful = any(v.could_still_enter(tok, t) and (v.name, tok.mint) not in self.entered
                      for v in self.variants.values())
        quiet = (age > float(self.feed_cfg.get("drop_quiet_after_s", 45))
                 and tok.net_sol < float(self.feed_cfg.get("drop_quiet_below_net_sol", 1.0)))
        if age > float(self.feed_cfg.get("watch_seconds", 300)) or not hopeful or quiet or tok.migrated:
            self.unwatch(tok, t)

    def unwatch(self, tok: TokenState, t: float) -> None:
        tok.watching = False
        self.actions.unsubscribe.append(tok.mint)
        self.journal.token({"mint": tok.mint, "symbol": tok.symbol, "name": tok.name, "creator": tok.creator,
                            "created_at": local_time(tok.created_t), "watched_s": round(t - tok.watch_start_t),
                            "trades": tok.trades, "peak_mcap_sol": round(tok.peak_mcap, 2),
                            "end_mcap_sol": round(tok.mcap_sol, 2), "migrated": int(tok.migrated),
                            **tok.features(t)})
        self.tokens.pop(tok.mint, None)
        self.entered = {k for k in self.entered if k[1] != tok.mint}

    # ── είσοδοι ──
    def open_count(self, variant: str) -> int:
        return (sum(1 for k in self.positions if k[0] == variant) + sum(1 for o in self.pending if o.variant == variant
                                                                        and o.kind == "buy")
                + sum(1 for k in self.pending_live_buys if k[0] == variant))

    def _consider_entries(self, tok: TokenState, t: float) -> None:
        if not tok.watching or tok.migrated:
            return
        for v in self.variants.values():
            key = (v.name, tok.mint)
            if key in self.entered or self.open_count(v.name) >= v.max_open:
                continue
            ok, _ = v.entry_check(tok, t, exclude=(self.own,) if self.own else ())
            if not ok:
                continue
            if v.live:
                allowed, why = self.guard.can_open(t, self.open_count(v.name))
                if not allowed:
                    self.stats[f"live: όχι αγορά ({why})"] += 1
                    continue
            self.entered.add(key)
            order = Order(next(self._ids), "buy", v.name, tok.mint, tok.symbol, t, tok.price,
                          amount_sol=v.trade_sol, reason="είσοδος", slippage_pct=self.costs.buy_slippage_pct,
                          live=v.live, feats=tok.features(t))
            if v.live:
                self.guard.on_order(t)
                self.pending_live_buys[key] = order
                self.actions.live_orders.append(order)
            else:
                self.pending.append(order)

    # ── έξοδοι ──
    def _manage(self, tok: TokenState, t: float) -> None:
        for v in self.variants.values():
            pos = self.positions.get((v.name, tok.mint))
            if pos is None or pos.pending is not None or t < pos.next_try_t:
                continue
            r = v.exit_check(pos, tok, t)
            if r:
                self._sell(pos, tok, t, r[0], r[1])

    def _sell(self, pos: Position, tok: TokenState, t: float, frac: float, reason: str) -> None:
        slip = min(self.costs.sell_slippage_pct * 2 ** pos.sell_attempt, 95.0)
        final = frac >= 0.999
        order = Order(next(self._ids), "sell", pos.variant, pos.mint, pos.symbol, t, tok.price, frac=frac,
                      final=final, reason=reason, slippage_pct=slip, live=pos.live)
        pos.pending = order
        if pos.live:
            self.actions.live_orders.append(order)
        else:
            self.pending.append(order)

    # ── εικονικές εκτελέσεις ──
    def _fill_pending(self, tok: TokenState, t: float, force: bool = False) -> None:
        due = [o for o in self.pending if o.mint == tok.mint
               and (force or t >= o.t + self.costs.latency_ms / 1000)]
        for o in due:
            self.pending.remove(o)
            self._paper_fill(o, tok, t)

    def _paper_fill(self, o: Order, tok: TokenState, t: float) -> None:
        c, p = self.costs, tok.price
        if o.kind == "buy":
            if p <= 0 or tok.migrated:
                self.stats["ακύρωση αγοράς"] += 1
                return
            if p > o.decision_price * (1 + o.slippage_pct / 100):
                self._failed_buy(o, tok, t, c.network_fee, "slippage")
                return
            f = simulate_buy(tok.v_sol, tok.v_tok, o.amount_sol, c)
            self._open(o, tok, t, f.avg_price, f.tokens, f.sol)
            return
        pos = self.positions.get((o.variant, o.mint))
        if pos is None:
            return
        pos.pending = None
        if not tok.migrated and p < o.decision_price * (1 - o.slippage_pct / 100):
            pos.cost_sol += c.network_fee
            pos.sell_attempt += 1
            pos.next_try_t = t + 1
            self.stats["αποτυχίες πώλησης (slippage)"] += 1
            return
        tokens = pos.tokens if o.final else pos.tokens * o.frac
        haircut = c.migration_exit_haircut_pct if tok.migrated else 0.0
        f = simulate_sell(tok.v_sol, tok.v_tok, tokens, c, last=o.final, haircut_pct=haircut)
        self._after_sell(pos, tok, t, o, f.sol, tokens)

    # ── κοινά για paper και live ──
    def _open(self, o: Order, tok: TokenState, t: float, entry_price: float, tokens: float, cost: float) -> Position:
        pos = Position(o.variant, o.mint, tok.symbol, tok.name, o.live, t, entry_price, tokens, cost,
                       tok.mcap_sol, o.feats, peak_price=max(entry_price, tok.price))
        self.positions[(o.variant, o.mint)] = pos
        if o.live:
            self.actions.notes.append((f"🟢 Αγορά {tok.symbol}",
                                       f"{cost:.4f} SOL · κεφ/ση {tok.mcap_sol:.0f} SOL · {o.variant}\n{tok.mint}"))
        return pos

    def _after_sell(self, pos: Position, tok: TokenState | None, t: float, o: Order, sol: float, tokens_sold: float) -> None:
        pos.realized_sol += sol
        pos.tokens = max(pos.tokens - tokens_sold, 0.0)
        pos.sells += 1
        pos.sell_attempt = 0
        if o.final or pos.tokens <= 0:
            self._close(pos, tok, t, o.reason)
        else:
            pos.tp_done = True
            if pos.live:
                self.actions.notes.append((f"💰 Μερική πώληση {pos.symbol}", f"+{sol:.4f} SOL · {o.reason}"))

    def _failed_buy(self, o: Order, tok: TokenState, t: float, fee: float, why: str) -> None:
        self.stats[f"αποτυχίες αγοράς ({why})"] += 1
        r = self.results[o.variant]
        r["failed"] += 1
        r["pnl"] += -fee
        self.journal.trade(self._row(o.variant, o.live, tok.mint, tok.symbol, tok.name, o.t, t, fee, 0.0,
                                     "αποτυχία αγοράς: " + why, "failed", o.feats, tok.mcap_sol, tok.mcap_sol, 0.0, 0))

    def _close(self, pos: Position, tok: TokenState | None, t: float, reason: str, status: str = "ok") -> None:
        self.positions.pop((pos.variant, pos.mint), None)
        pnl = pos.realized_sol - pos.cost_sol
        if status == "ok":
            r = self.results.setdefault(pos.variant, Counter())
            r["closed"] += 1
            r["wins"] += pnl > 0
            r["pnl"] += pnl
        mcap = tok.mcap_sol if tok else 0.0
        peak = pos.peak_price / pos.entry_price if pos.entry_price > 0 else 0.0
        self.journal.trade(self._row(pos.variant, pos.live, pos.mint, pos.symbol, pos.name, pos.opened_t, t,
                                     pos.cost_sol, pos.realized_sol, reason, status, pos.feats, pos.entry_mcap,
                                     mcap, peak, pos.sells))
        if pos.live:
            self.guard.on_close(pnl, t)
            icon = "✅" if pnl > 0 else "🔻"
            self.actions.notes.append((f"{icon} Κλείσιμο {pos.symbol}: {pnl:+.4f} SOL",
                                       f"{100 * pnl / pos.cost_sol:+.1f}% · {reason} · σε {int(t - pos.opened_t)}″\n"
                                       f"Σήμερα: {self.guard.pnl_today:+.4f} SOL"))

    @staticmethod
    def _row(variant, live, mint, symbol, name, t0, t1, cost, proceeds, reason, status, feats, mcap0, mcap1, peak,
             sells) -> dict:
        pnl = proceeds - cost
        return {"closed_at": local_time(t1), "variant": variant, "mode": "live" if live else "paper",
                "status": status, "mint": mint, "symbol": symbol, "name": name, "opened_at": local_time(t0),
                "hold_s": round(t1 - t0, 1), "cost_sol": round(cost, 6), "proceeds_sol": round(proceeds, 6),
                "pnl_sol": round(pnl, 6), "pnl_pct": round(100 * pnl / cost, 2) if cost > 0 else 0.0,
                "peak_multiple": round(peak, 3), "entry_mcap_sol": round(mcap0, 2), "exit_mcap_sol": round(mcap1, 2),
                "sells": sells, "exit_reason": reason, "entry_age_s": feats.get("age_s", ""),
                "uniq_buyers": feats.get("uniq_buyers", ""), "net_sol": feats.get("net_sol", ""),
                "dev_pct": feats.get("dev_pct", ""), "top_holder_pct": feats.get("top_holder_pct", ""),
                "twitter": feats.get("twitter", ""), "telegram": feats.get("telegram", "")}

    # ── πραγματικές εκτελέσεις: αποτελέσματα από τον live broker ──
    def on_live_result(self, o: Order, res: LiveResult, t: float) -> None:
        self.last_t = t
        key = (o.variant, o.mint)
        tok = self.tokens.get(o.mint)
        if res.ok:
            self.guard.on_success()
        elif res.exception and self.guard.on_error():
            self.actions.notes.append(("⛔ Το bot σταμάτησε τις αγορές", self.guard.halted + ": " + res.error))
        if o.kind == "buy":
            self.pending_live_buys.pop(key, None)
            if not res.ok or res.token_delta <= 0:
                fee = max(-res.sol_delta, 0.0)
                ghost = tok or TokenState(mint=o.mint, symbol=o.symbol)
                self._failed_buy(o, ghost, t, fee, res.error or "χωρίς tokens")
                if res.exception:
                    self.actions.notes.append((f"⚠️ Αποτυχία αγοράς {o.symbol}", res.error))
                return
            cost = -res.sol_delta
            c = self.costs
            to_curve = (cost - c.network_fee - c.token_account_rent_sol) / (1 + c.portal_fee_pct / 100) \
                / (1 + c.curve_fee_pct / 100)
            entry = max(to_curve, 1e-12) / res.token_delta
            self._open(o, tok or TokenState(mint=o.mint, symbol=o.symbol), t, entry, res.token_delta, cost)
            return
        pos = self.positions.get(key)
        if pos is None:
            return
        pos.pending = None
        if not res.ok:
            pos.cost_sol += max(-res.sol_delta, 0.0)
            pos.sell_attempt += 1
            pos.next_try_t = t + 2
            if pos.sell_attempt == 3:
                self.actions.notes.append((f"⚠️ Δεν πουλάει το {pos.symbol}", f"3 αποτυχίες: {res.error}"))
            return
        sold = -res.token_delta if res.token_delta < 0 else (pos.tokens if o.final else pos.tokens * o.frac)
        self._after_sell(pos, tok, t, o, res.sol_delta, sold)

    def restore_live(self, saved: list[dict], t: float) -> None:
        """Μετά από επανεκκίνηση: ξαναπαίρνει υπό διαχείριση τις πραγματικές θέσεις που είχαν μείνει."""
        live = next((v for v in self.variants.values() if v.live), None)
        if live is None:
            return
        for s in saved:
            tok = self.tokens.get(s["mint"]) or TokenState(mint=s["mint"], symbol=s.get("symbol", ""),
                                                          name=s.get("name", ""), created_t=s.get("opened_t", t),
                                                          last_trade_t=t, meta_done=True)
            tok.watching, tok.watch_start_t = True, t
            self.tokens[tok.mint] = tok
            self.actions.subscribe.append(tok.mint)
            pos = Position(live.name, s["mint"], s.get("symbol", ""), s.get("name", ""), True, s["opened_t"],
                           s["entry_price"], s["tokens"], s["cost_sol"], s.get("entry_mcap", 0.0),
                           s.get("feats", {}), peak_price=s.get("peak_price", s["entry_price"]),
                           realized_sol=s.get("realized_sol", 0.0), tp_done=s.get("tp_done", False),
                           sells=s.get("sells", 0))
            self.positions[(live.name, pos.mint)] = pos
            self.entered.add((live.name, pos.mint))

    def force_exit_live(self, t: float, reason: str) -> int:
        """Πώληση όλων των πραγματικών θέσεων (SELL_ALL ή τερματισμός)."""
        n = 0
        for pos in [p for p in self.positions.values() if p.live and p.pending is None]:
            tok = self.tokens.get(pos.mint) or TokenState(mint=pos.mint, symbol=pos.symbol)
            pos.sell_attempt = max(pos.sell_attempt, 2)          # μεγάλο slippage: προτεραιότητα να βγει
            self._sell(pos, tok, t, 1.0, reason)
            n += 1
        return n

    def live_state(self) -> list[dict]:
        return [{"mint": p.mint, "symbol": p.symbol, "name": p.name, "opened_t": p.opened_t,
                 "entry_price": p.entry_price, "tokens": p.tokens, "cost_sol": p.cost_sol,
                 "entry_mcap": p.entry_mcap, "feats": p.feats, "peak_price": p.peak_price,
                 "realized_sol": p.realized_sol, "tp_done": p.tp_done, "sells": p.sells}
                for p in self.positions.values() if p.live]

    # ── τερματισμός και σύνοψη ──
    def shutdown_paper(self, t: float) -> None:
        """Κλείνει τις εικονικές θέσεις στην τρέχουσα τιμή, ώστε το ημερολόγιο να είναι πλήρες. Γράφονται με
        status «shutdown»: δεν τις έκλεισε η στρατηγική, οπότε η αναφορά δεν τις μετράει."""
        self.pending = [o for o in self.pending if o.live]
        for pos in [p for p in self.positions.values() if not p.live]:
            tok = self.tokens.get(pos.mint)
            if tok is None or tok.price <= 0:
                continue
            f = simulate_sell(tok.v_sol, tok.v_tok, pos.tokens, self.costs, last=True)
            pos.realized_sol += f.sol
            pos.tokens = 0.0
            self._close(pos, tok, t, "τερματισμός bot", status="shutdown")

    def summary(self) -> list[dict]:
        out = []
        for name, v in self.variants.items():
            r = self.results.get(name, Counter())
            open_pos = [p for p in self.positions.values() if p.variant == name]
            unreal = 0.0
            for p in open_pos:
                tok = self.tokens.get(p.mint)
                if tok and tok.price > 0 and p.tokens > 0:
                    unreal += simulate_sell(tok.v_sol, tok.v_tok, p.tokens, self.costs).sol + p.realized_sol - p.cost_sol
            out.append({"variant": name, "live": v.live, "closed": r["closed"], "wins": r["wins"],
                        "failed": r["failed"], "pnl_sol": r["pnl"], "open": len(open_pos),
                        "unrealized_sol": unreal})
        return out

    def take_actions(self) -> Actions:
        a, self.actions = self.actions, Actions()
        return a
