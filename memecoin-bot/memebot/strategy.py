"""Κανόνες εισόδου και εξόδου. Κάθε «στρατηγική» του config.json είναι ένα Variant.

Όλες οι στρατηγικές τρέχουν ταυτόχρονα πάνω στα ίδια ζωντανά δεδομένα, ώστε να
συγκρίνονται δίκαια. Στο live, μόνο μία κάνει πραγματικές εντολές.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .market import TokenState

INF = float("inf")


@dataclass
class EntryRules:
    min_age_s: float = 0
    max_age_s: float = 120
    require_socials: bool = False       # Telegram ή X (Twitter)
    require_telegram: bool = False
    min_dev_buy_sol: float = 0
    max_dev_buy_sol: float = INF
    max_dev_pct: float = 100
    max_dev_sold_pct: float = 0         # 0 = καμία είσοδος αν ο δημιουργός πούλησε έστω και λίγο
    min_unique_buyers: int = 0
    min_buyer_sol: float = 0.05         # αγοραστές με λιγότερα δεν μετράνε (bots με «σκόνη»)
    min_net_sol: float = -INF
    min_recent_net_sol: float = -INF
    recent_window_s: float = 15
    min_buy_sell_ratio: float = 0
    min_mcap_sol: float = 0
    max_mcap_sol: float = INF
    max_top_holder_pct: float = 100


@dataclass
class ExitRules:
    stop_loss_pct: float = 30
    take_profit_pct: float = 100
    take_profit_sell_frac: float = 0.5
    trail_activate_pct: float = 50
    trailing_stop_pct: float = 30
    time_stop_s: float = 300
    time_stop_min_gain_pct: float = 10
    max_hold_s: float = 1800
    inactivity_s: float = 120
    exit_on_dev_sell: bool = True
    dev_sell_exit_pct: float = 10       # % των tokens του δημιουργού που αν πουληθούν → έξοδος
    exit_mcap_sol: float = 350          # πούλα πριν την αποφοίτηση (~410 SOL)


def _build(cls, d: dict | None):
    names = {f.name for f in fields(cls)}
    unknown = set(d or {}) - names
    if unknown:
        raise SystemExit(f"Άγνωστες ρυθμίσεις στο config.json: {', '.join(sorted(unknown))}")
    return cls(**(d or {}))


@dataclass
class Variant:
    name: str
    trade_sol: float = 0.1
    max_open: int = 5
    enabled: bool = True
    live: bool = False
    entry: EntryRules = field(default_factory=EntryRules)
    exit: ExitRules = field(default_factory=ExitRules)

    @classmethod
    def from_dict(cls, d: dict) -> "Variant":
        return cls(name=d["name"], trade_sol=float(d.get("trade_sol", 0.1)), max_open=int(d.get("max_open", 5)),
                   enabled=bool(d.get("enabled", True)), entry=_build(EntryRules, d.get("entry")),
                   exit=_build(ExitRules, d.get("exit")))

    @property
    def needs_meta(self) -> bool:
        return self.entry.require_socials or self.entry.require_telegram

    def could_still_enter(self, tok: TokenState, t: float) -> bool:
        e = self.entry
        return (tok.age(t) <= e.max_age_s and not tok.migrated
                and tok.dev_sold_pct() <= e.max_dev_sold_pct and tok.mcap_sol <= e.max_mcap_sol)

    def entry_check(self, tok: TokenState, t: float, exclude: tuple = ()) -> tuple[bool, str]:
        """(True, "") αν πληρούνται όλοι οι όροι, αλλιώς (False, ο πρώτος όρος που λείπει)."""
        e, age = self.entry, tok.age(t)
        if age < e.min_age_s:
            return False, "νωρίς"
        if age > e.max_age_s:
            return False, "αργά"
        if tok.migrated or tok.price <= 0:
            return False, "χωρίς τιμή"
        if e.require_socials or e.require_telegram:
            if not tok.meta_done:
                return False, "αναμονή metadata"
            if e.require_telegram and not tok.socials()["telegram"]:
                return False, "χωρίς Telegram"
            if e.require_socials and not tok.has_socials():
                return False, "χωρίς social"
        if not e.min_dev_buy_sol <= tok.dev_buy_sol <= e.max_dev_buy_sol:
            return False, "αγορά δημιουργού"
        if tok.dev_pct() > e.max_dev_pct:
            return False, "πολλά στον δημιουργό"
        if tok.dev_sold_pct() > e.max_dev_sold_pct:
            return False, "πούλησε ο δημιουργός"
        if tok.unique_buyers(e.min_buyer_sol) < e.min_unique_buyers:
            return False, "λίγοι αγοραστές"
        if tok.net_sol < e.min_net_sol:
            return False, "λίγη καθαρή εισροή"
        if tok.recent_net_sol(t, e.recent_window_s) < e.min_recent_net_sol:
            return False, "εκροή τελευταία"
        if tok.buy_sell_ratio() < e.min_buy_sell_ratio:
            return False, "πολλές πωλήσεις"
        if not e.min_mcap_sol <= tok.mcap_sol <= e.max_mcap_sol:
            return False, "κεφαλαιοποίηση εκτός εύρους"
        if tok.top_holder_pct(exclude) > e.max_top_holder_pct:
            return False, "συγκέντρωση σε ένα πορτοφόλι"
        return True, ""

    def exit_check(self, pos, tok: TokenState, t: float) -> tuple[float, str] | None:
        """(ποσοστό προς πώληση 0–1, λόγος) ή None."""
        x = self.exit
        if tok.migrated:
            return 1.0, "αποφοίτηση"
        p = tok.price
        if p > 0 and pos.entry_price > 0:
            pos.peak_price = max(pos.peak_price, p)
            gain = 100 * (p / pos.entry_price - 1)
            peak_gain = 100 * (pos.peak_price / pos.entry_price - 1)
            if x.exit_on_dev_sell and tok.dev_peak_tokens > 0 and tok.dev_sold_pct() >= x.dev_sell_exit_pct:
                return 1.0, "πούλησε ο δημιουργός"
            if tok.mcap_sol >= x.exit_mcap_sol:
                return 1.0, "κοντά στην αποφοίτηση"
            if gain <= -x.stop_loss_pct:
                return 1.0, "stop-loss"
            if not pos.tp_done and gain >= x.take_profit_pct:
                return min(max(x.take_profit_sell_frac, 0.0), 1.0) or 1.0, "στόχος"
            if (pos.tp_done or peak_gain >= x.trail_activate_pct) and p <= pos.peak_price * (1 - x.trailing_stop_pct / 100):
                return 1.0, "trailing stop"
            if t - pos.opened_t >= x.time_stop_s and gain < x.time_stop_min_gain_pct and not pos.tp_done:
                return 1.0, "δεν κινήθηκε"
        if t - pos.opened_t >= x.max_hold_s:
            return 1.0, "μέγιστη διάρκεια"
        if t - tok.last_trade_t >= x.inactivity_s:
            return 1.0, "χωρίς συναλλαγές"
        return None
