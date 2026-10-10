"""Μαθηματικά της bonding curve του pump.fun και πλήρες μοντέλο κόστους.

Η καμπύλη είναι «σταθερό γινόμενο» με εικονικά αποθέματα: v_sol · v_tok = k.
Ξεκινά από 30 SOL / 1.073 δισ. tokens (κεφαλαιοποίηση ~28 SOL) και ολοκληρώνεται
(«αποφοίτηση» στο PumpSwap) όταν έχουν μπει ~85 SOL, σε κεφαλαιοποίηση ~410 SOL.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

INITIAL_V_SOL = 30.0
INITIAL_V_TOK = 1_073_000_000.0
DEFAULT_SUPPLY = 1_000_000_000.0


@dataclass
class Costs:
    curve_fee_pct: float = 1.25          # χρέωση pump.fun σε κάθε αγορά/πώληση πάνω στην καμπύλη
    portal_fee_pct: float = 0.5          # χρέωση PumpPortal (Local API· το Lightning είναι 1%)
    priority_fee_sol: float = 0.0005     # «φιλοδώρημα» προτεραιότητας ανά συναλλαγή
    base_fee_sol: float = 0.000005       # βασική χρέωση δικτύου Solana
    token_account_rent_sol: float = 0.00203928  # εγγύηση λογαριασμού token (επιστρέφεται αν κλείσει)
    close_token_accounts: bool = True
    latency_ms: int = 1500               # πόσο αργότερα «προσγειώνεται» η εντολή μας
    buy_slippage_pct: float = 15
    sell_slippage_pct: float = 30
    migration_exit_haircut_pct: float = 10
    data_cost_sol_per_10k_trades: float = 0.01

    @classmethod
    def from_dict(cls, d: dict | None) -> "Costs":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    @property
    def network_fee(self) -> float:
        return self.priority_fee_sol + self.base_fee_sol


@dataclass
class Fill:
    tokens: float
    sol: float          # αγορά: συνολικό κόστος (θετικό) · πώληση: καθαρά έσοδα
    avg_price: float    # μέση τιμή πάνω στην καμπύλη, χωρίς χρεώσεις
    fees_sol: float


def spot_price(v_sol: float, v_tok: float) -> float:
    return v_sol / v_tok if v_tok > 0 else 0.0


def mcap_from_reserves(v_sol: float, v_tok: float, supply: float = DEFAULT_SUPPLY) -> float:
    return spot_price(v_sol, v_tok) * supply


def tokens_for_sol(v_sol: float, v_tok: float, sol_in: float) -> float:
    return v_tok - v_sol * v_tok / (v_sol + sol_in)


def sol_for_tokens(v_sol: float, v_tok: float, tok_in: float) -> float:
    return v_sol - v_sol * v_tok / (v_tok + tok_in)


def simulate_buy(v_sol: float, v_tok: float, amount_sol: float, c: Costs, new_account: bool = True) -> Fill:
    """Αγορά με amount_sol (μαζί με τη χρέωση της καμπύλης), όπως το PumpPortal με denominatedInSol."""
    to_curve = amount_sol / (1 + c.curve_fee_pct / 100)
    tokens = tokens_for_sol(v_sol, v_tok, to_curve)
    rent = c.token_account_rent_sol if new_account else 0.0
    portal = amount_sol * c.portal_fee_pct / 100
    total = amount_sol + portal + c.network_fee + rent
    return Fill(tokens, total, to_curve / tokens if tokens > 0 else 0.0, total - to_curve - rent)


def simulate_sell(v_sol: float, v_tok: float, tokens: float, c: Costs, last: bool = True,
                  haircut_pct: float = 0.0) -> Fill:
    """Πώληση tokens. Στην τελευταία πώληση κλείνει ο λογαριασμός και επιστρέφεται η εγγύηση."""
    gross = sol_for_tokens(v_sol, v_tok, tokens) * (1 - haircut_pct / 100)
    fees = gross * (c.curve_fee_pct + c.portal_fee_pct) / 100 + c.network_fee
    net = gross - fees
    if last and c.close_token_accounts:
        net += c.token_account_rent_sol - c.base_fee_sol
        fees += c.base_fee_sol
    return Fill(tokens, net, gross / tokens if tokens > 0 else 0.0, fees)


def round_trip_cost_pct(amount_sol: float, c: Costs) -> float:
    """Πόσο % χάνεται σε χρεώσεις αν αγοράσεις και πουλήσεις αμέσως (χωρίς κίνηση τιμής)."""
    b = simulate_buy(INITIAL_V_SOL * 2, INITIAL_V_TOK / 2, amount_sol, c)
    s = simulate_sell(INITIAL_V_SOL * 2 + b.avg_price * b.tokens, INITIAL_V_TOK / 2 - b.tokens, b.tokens, c)
    return (1 - s.sol / b.sol) * 100
