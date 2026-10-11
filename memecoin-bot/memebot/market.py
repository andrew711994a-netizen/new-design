"""Η κατάσταση κάθε νέου token, όπως χτίζεται από τη ροή συναλλαγών του PumpPortal."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .curve import DEFAULT_SUPPLY, spot_price


def num(d: dict, key: str, default: float = 0.0) -> float:
    try:
        v = d.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


@dataclass
class TokenState:
    mint: str
    name: str = ""
    symbol: str = ""
    uri: str = ""
    creator: str = ""
    pool: str = "pump"
    created_t: float = 0.0
    v_sol: float = 0.0
    v_tok: float = 0.0
    mcap_sol: float = 0.0
    supply: float = DEFAULT_SUPPLY
    dev_buy_sol: float = 0.0
    dev_tokens: float = 0.0
    dev_peak_tokens: float = 0.0
    dev_sold_tokens: float = 0.0
    holders: dict = field(default_factory=dict)      # πορτοφόλι → tokens
    buyer_sol: dict = field(default_factory=dict)    # πορτοφόλι → SOL που έβαλε συνολικά
    flow: deque = field(default_factory=deque)       # (χρόνος, +SOL αγορά / −SOL πώληση)
    buys: int = 0
    sells: int = 0
    sol_in: float = 0.0
    sol_out: float = 0.0
    trades: int = 0
    last_trade_t: float = 0.0
    peak_mcap: float = 0.0
    meta: dict | None = None
    meta_done: bool = False
    migrated: bool = False
    watching: bool = False
    watch_start_t: float = 0.0
    passed_prefilter: bool = False
    words: set = field(default_factory=set)          # λέξεις ονόματος/συμβόλου (για θέματα και trends)
    viral_score: int = 0
    viral_why: str = ""

    # ── ενημέρωση από γεγονότα ──
    @classmethod
    def from_create(cls, ev: dict, t: float) -> "TokenState":
        tok = cls(mint=str(ev.get("mint", "")), name=str(ev.get("name", ""))[:60],
                  symbol=str(ev.get("symbol", ""))[:20], uri=str(ev.get("uri", "")),
                  creator=str(ev.get("traderPublicKey", "")), pool=str(ev.get("pool") or "pump"),
                  created_t=t, last_trade_t=t)
        tok._reserves(ev)
        tok.dev_buy_sol = num(ev, "solAmount")
        tok.dev_tokens = tok.dev_peak_tokens = num(ev, "initialBuy")
        if tok.creator and tok.dev_tokens > 0:
            tok.holders[tok.creator] = tok.dev_tokens
        return tok

    def _reserves(self, ev: dict) -> None:
        v_sol, v_tok = num(ev, "vSolInBondingCurve"), num(ev, "vTokensInBondingCurve")
        if v_sol > 0 and v_tok > 0:
            self.v_sol, self.v_tok = v_sol, v_tok
        mcap = num(ev, "marketCapSol")
        if mcap > 0:
            self.mcap_sol = mcap
            if self.price > 0:
                implied = mcap / self.price
                # Κανονικά 1 δισ.· τα tokens «Mayhem» έχουν 2 δισ.
                if 0.5 * DEFAULT_SUPPLY <= implied <= 2.5 * DEFAULT_SUPPLY:
                    self.supply = implied
        elif self.price > 0:
            self.mcap_sol = self.price * self.supply
        self.peak_mcap = max(self.peak_mcap, self.mcap_sol)

    def apply_trade(self, ev: dict, t: float) -> None:
        side = str(ev.get("txType", "")).lower()
        who = str(ev.get("traderPublicKey", ""))
        sol, amount = num(ev, "solAmount"), num(ev, "tokenAmount")
        self._reserves(ev)
        self.trades += 1
        self.last_trade_t = t
        if side == "buy":
            self.buys += 1
            self.sol_in += sol
            self.flow.append((t, sol))
            if who and who != self.creator:
                self.buyer_sol[who] = self.buyer_sol.get(who, 0.0) + sol
        elif side == "sell":
            self.sells += 1
            self.sol_out += sol
            self.flow.append((t, -sol))
            if who == self.creator:
                self.dev_sold_tokens += amount
        if who:
            if "newTokenBalance" in ev:
                bal = num(ev, "newTokenBalance")
            else:
                bal = self.holders.get(who, 0.0) + (amount if side == "buy" else -amount)
            bal = max(bal, 0.0)
            if bal > 0:
                self.holders[who] = bal
            else:
                self.holders.pop(who, None)
            if who == self.creator:
                self.dev_tokens = bal
                self.dev_peak_tokens = max(self.dev_peak_tokens, bal)
        while self.flow and self.flow[0][0] < t - 120:
            self.flow.popleft()

    # ── μετρήσεις για τις στρατηγικές ──
    @property
    def price(self) -> float:
        return spot_price(self.v_sol, self.v_tok)

    def age(self, t: float) -> float:
        return t - self.created_t

    @property
    def net_sol(self) -> float:
        return self.sol_in - self.sol_out

    def recent_net_sol(self, t: float, window_s: float) -> float:
        return sum(s for (ts, s) in self.flow if ts >= t - window_s)

    def unique_buyers(self, min_sol: float = 0.0) -> int:
        return sum(1 for s in self.buyer_sol.values() if s >= min_sol)

    def buy_sell_ratio(self) -> float:
        return self.buys / self.sells if self.sells else float(self.buys) if self.buys else 0.0

    def dev_pct(self) -> float:
        return 100 * self.dev_tokens / self.supply

    def dev_sold_pct(self) -> float:
        return 100 * self.dev_sold_tokens / self.dev_peak_tokens if self.dev_peak_tokens > 0 else 0.0

    def top_holder_pct(self, exclude: tuple = ()) -> float:
        skip = {self.creator, *exclude}
        top = max((b for w, b in self.holders.items() if w not in skip), default=0.0)
        return 100 * top / self.supply

    def socials(self) -> dict:
        m = self.meta or {}
        return {k: bool(str(m.get(k) or "").strip()) for k in ("twitter", "telegram", "website")}

    def has_socials(self) -> bool:
        s = self.socials()
        return s["twitter"] or s["telegram"]

    def features(self, t: float) -> dict:
        """Στιγμιότυπο για το ημερολόγιο (για μελλοντική έρευνα)."""
        s = self.socials()
        return {
            "age_s": round(self.age(t), 1), "mcap_sol": round(self.mcap_sol, 2),
            "uniq_buyers": self.unique_buyers(0.05), "buys": self.buys, "sells": self.sells,
            "net_sol": round(self.net_sol, 3), "dev_buy_sol": round(self.dev_buy_sol, 3),
            "dev_pct": round(self.dev_pct(), 2), "dev_sold_pct": round(self.dev_sold_pct(), 1),
            "top_holder_pct": round(self.top_holder_pct(), 2),
            "twitter": int(s["twitter"]), "telegram": int(s["telegram"]), "website": int(s["website"]),
            "viral_score": self.viral_score, "viral_why": self.viral_why,
        }
