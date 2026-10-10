"""Μικρός προσομοιωτής pump.fun για τα τεστ: παράγει γεγονότα όπως του PumpPortal."""

from __future__ import annotations

import copy
import json
import math

from memebot.config import ROOT
from memebot.curve import INITIAL_V_SOL, INITIAL_V_TOK, sol_for_tokens, tokens_for_sol

CURVE_FEE = 0.0125


def base_config(only: str | None = None, **live) -> dict:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg["metadata"]["fetch"] = False
    cfg["feed"]["sample_pct"] = 100
    cfg["feed"]["max_data_sol_per_day"] = 1e9
    cfg["prefilter"]["blocked_words"] = []
    for s in cfg["strategies"]:
        s["enabled"] = only is None or s["name"] == only
    cfg["live"].update(live)
    return copy.deepcopy(cfg)


class Market:
    def __init__(self):
        self.res: dict[str, list[float]] = {}
        self.bal: dict[tuple, float] = {}

    def _ev(self, mint: str, extra: dict) -> dict:
        v_sol, v_tok = self.res[mint]
        return {"mint": mint, "vSolInBondingCurve": v_sol, "vTokensInBondingCurve": v_tok,
                "marketCapSol": v_sol / v_tok * 1e9, "pool": "pump", "signature": "sig", **extra}

    def create(self, mint: str, dev: str = "DEV", dev_sol: float = 0.5, name: str = "Frog", symbol: str = "FROG",
               uri: str = "") -> dict:
        self.res[mint] = [INITIAL_V_SOL, INITIAL_V_TOK]
        tokens = self._buy(mint, dev, dev_sol)
        return self._ev(mint, {"txType": "create", "traderPublicKey": dev, "initialBuy": tokens,
                               "solAmount": dev_sol, "name": name, "symbol": symbol, "uri": uri,
                               "bondingCurveKey": "curve"})

    def _buy(self, mint: str, who: str, sol: float) -> float:
        v_sol, v_tok = self.res[mint]
        to_curve = sol / (1 + CURVE_FEE)
        tokens = tokens_for_sol(v_sol, v_tok, to_curve)
        self.res[mint] = [v_sol + to_curve, v_tok - tokens]
        self.bal[(mint, who)] = self.bal.get((mint, who), 0.0) + tokens
        return tokens

    def buy(self, mint: str, who: str, sol: float) -> dict:
        tokens = self._buy(mint, who, sol)
        return self._ev(mint, {"txType": "buy", "traderPublicKey": who, "solAmount": sol, "tokenAmount": tokens,
                               "newTokenBalance": self.bal[(mint, who)]})

    def sell(self, mint: str, who: str, frac: float = 1.0) -> dict:
        tokens = self.bal.get((mint, who), 0.0) * frac
        v_sol, v_tok = self.res[mint]
        sol = sol_for_tokens(v_sol, v_tok, tokens)
        self.res[mint] = [v_sol - sol, v_tok + tokens]
        self.bal[(mint, who)] -= tokens
        return self._ev(mint, {"txType": "sell", "traderPublicKey": who, "solAmount": sol * (1 - CURVE_FEE),
                               "tokenAmount": tokens, "newTokenBalance": self.bal[(mint, who)]})

    def price(self, mint: str) -> float:
        v_sol, v_tok = self.res[mint]
        return v_sol / v_tok


class Driver:
    """Τροφοδοτεί ένα Engine με γεγονότα και ticks ανά δευτερόλεπτο (όπως ο runner)."""

    def __init__(self, engine, journal=None):
        self.engine, self.journal, self.t = engine, journal, 1_000_000.0

    def advance(self, seconds: float) -> None:
        """Ticks σε κάθε ακέραιο δευτερόλεπτο, όπως και στο backtest."""
        end = self.t + seconds
        k = math.floor(self.t) + 1
        while k <= end:
            self.engine.on_tick(float(k))
            self.engine.take_actions()
            k += 1
        self.t = end

    def send(self, ev: dict, kind: str | None = None) -> None:
        kind = kind or {"create": "c", "buy": "t", "sell": "t"}[ev["txType"]]
        if self.journal is not None:
            self.journal.tick(kind, ev, self.t)
        {"c": self.engine.on_create, "t": self.engine.on_trade, "m": self.engine.on_migration}[kind](ev, self.t)
        self.engine.take_actions()

    def at(self, seconds: float, ev: dict) -> None:
        self.advance(seconds)
        self.send(ev)
