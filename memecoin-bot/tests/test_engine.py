import pytest

from memebot.backtest import replay
from memebot.curve import Costs, round_trip_cost_pct, simulate_buy, simulate_sell, tokens_for_sol
from memebot.engine import Engine, LiveResult
from memebot.journal import Journal
from memebot.market import TokenState
from memebot.report import build_report, variant_stats

from sim import Driver, Market, base_config


def make(only=None, live_variant=None, **live):
    cfg = base_config(only, **live)
    j = Journal(None)
    return Engine(cfg, j, live_variant=live_variant), j, Market()


def crowd(drv, mkt, mint, n, sol, every=1.0, prefix="B"):
    for i in range(n):
        drv.at(every, mkt.buy(mint, f"{prefix}{i}", sol))


# ── καμπύλη και κόστη ──
def test_curve_graduation_and_costs():
    # Η αποφοίτηση: ~793 εκ. tokens πωλημένα με ~85 SOL, κεφαλαιοποίηση ~410 SOL
    sold = tokens_for_sol(30, 1.073e9, 85)
    assert 790e6 < sold < 796e6
    assert 400 < (115 / (1.073e9 - sold)) * 1e9 < 420
    c = Costs()
    rt = round_trip_cost_pct(0.1, c)
    assert 4.0 < rt < 5.0          # 2×(1,25%+0,5%) + 2×0,0005 SOL σε 0,1 SOL
    assert round_trip_cost_pct(0.02, c) > 7   # μικρές θέσεις: τα σταθερά κόστη τρώνε πολλά
    b = simulate_buy(30, 1.073e9, 0.1, c)
    s = simulate_sell(30 + b.avg_price * b.tokens, 1.073e9 - b.tokens, b.tokens, c)
    assert s.sol < b.sol


def test_mayhem_supply_detected():
    tok = TokenState.from_create({"mint": "M", "traderPublicKey": "D", "initialBuy": 20e6, "solAmount": 0.6,
                                  "vSolInBondingCurve": 30.6, "vTokensInBondingCurve": 1.053e9,
                                  "marketCapSol": 30.6 / 1.053e9 * 2e9}, 0)
    assert abs(tok.supply - 2e9) < 1
    assert abs(tok.dev_pct() - 1.0) < 0.01


# ── στρατηγικές ──
def test_momentum_pump_takes_profit_and_trails():
    eng, j, mkt = make("momentum_early")
    drv = Driver(eng)
    drv.send(mkt.create("PUMP"))
    crowd(drv, mkt, "PUMP", 10, 0.7)                    # 10 αγοραστές, ~7 SOL καθαρά → είσοδος
    drv.advance(3)
    pos = eng.positions[("momentum_early", "PUMP")]
    assert pos.tokens > 0 and pos.cost_sol > 0.1
    crowd(drv, mkt, "PUMP", 30, 1.0, prefix="C")        # ράλι → στόχος +80%, πώληση μισών
    drv.advance(3)
    assert pos.tp_done and pos.sells == 1
    for i in range(30):                                 # οι αγοραστές πουλάνε → trailing stop
        drv.at(1, mkt.sell("PUMP", f"C{i}"))
    drv.advance(3)
    assert ("momentum_early", "PUMP") not in eng.positions
    row = j.trades[-1]
    assert row["status"] == "ok" and row["pnl_sol"] > 0
    assert row["exit_reason"] in ("trailing stop", "stop-loss")
    assert row["peak_multiple"] > 1.8


def test_rug_dev_dump_exits_with_loss():
    eng, j, mkt = make("momentum_early")
    drv = Driver(eng)
    drv.send(mkt.create("RUG", dev_sol=1.5))
    crowd(drv, mkt, "RUG", 10, 0.7)
    drv.advance(3)
    assert ("momentum_early", "RUG") in eng.positions
    drv.at(5, mkt.sell("RUG", "DEV"))                   # ο δημιουργός πουλάει τα πάντα
    drv.advance(3)
    row = j.trades[-1]
    assert row["exit_reason"] == "πούλησε ο δημιουργός"
    assert row["pnl_sol"] < 0


def test_buy_fails_when_price_runs_away_within_latency():
    eng, j, mkt = make("momentum_early")
    drv = Driver(eng)
    drv.send(mkt.create("FAST"))
    crowd(drv, mkt, "FAST", 8, 0.7)                     # ο 8ος αγοραστής ενεργοποιεί την είσοδο
    assert any(o.kind == "buy" for o in eng.pending)
    drv.at(0.5, mkt.buy("FAST", "WHALE", 12))           # +60% μέσα στο 1,5″ της καθυστέρησης
    drv.advance(2)
    row = j.trades[-1]
    assert row["status"] == "failed"
    assert row["pnl_sol"] == pytest.approx(-Costs().network_fee)
    assert ("momentum_early", "FAST") not in eng.positions


def test_snipe_requires_socials():
    cfg = base_config("snipe_social")
    cfg["metadata"]["fetch"] = True
    eng = Engine(cfg, Journal(None))
    mkt = Market()
    drv = Driver(eng)
    drv.send(mkt.create("S1", uri="https://ipfs/x", dev_sol=0.5))
    assert eng.take_actions().meta == [] and not eng.pending      # οι ενέργειες ελήφθησαν ήδη
    eng.on_meta("S1", {"twitter": "", "telegram": "https://t.me/frog", "website": ""}, drv.t + 1)
    assert [o.mint for o in eng.pending] == ["S1"]
    drv.send(mkt.create("S2", uri="https://ipfs/y", dev_sol=0.5))
    eng.on_meta("S2", {"twitter": "", "telegram": "", "website": "x"}, drv.t + 1)
    assert all(o.mint != "S2" for o in eng.pending)


def test_quiet_tokens_are_dropped_and_capacity_is_respected():
    cfg = base_config("momentum_strong")
    cfg["feed"]["max_watching"] = 2
    eng, mkt = Engine(cfg, Journal(None)), Market()
    drv = Driver(eng)
    for m in ("A", "B", "C"):
        drv.send(mkt.create(m))
    assert set(eng.tokens) == {"A", "B"}
    assert eng.stats["χωρίς θέση παρακολούθησης"] == 1
    drv.advance(50)                                     # κανείς δεν αγόρασε → πέφτουν
    assert eng.watching_count() == 0


def test_serial_creator_and_name_filters():
    cfg = base_config("baseline_all")
    cfg["prefilter"]["blocked_words"] = ["rug"]
    eng, mkt = Engine(cfg, Journal(None)), Market()
    drv = Driver(eng)
    for i in range(4):
        drv.send(mkt.create(f"X{i}", dev="SAME"))
    drv.send(mkt.create("Y", dev="OTHER", name="Rug Pull"))
    assert eng.stats["απόρριψη: κατά συρροή δημιουργός"] == 1
    assert eng.stats["απόρριψη: όνομα"] == 1


def test_baseline_buys_everything_alive():
    eng, j, mkt = make("baseline_all")
    drv = Driver(eng)
    drv.send(mkt.create("Z"))
    crowd(drv, mkt, "Z", 3, 0.5)
    drv.advance(20)
    drv.send(mkt.buy("Z", "late", 0.3))
    drv.advance(3)
    assert ("baseline_all", "Z") in eng.positions


def test_migration_forces_exit_with_haircut():
    eng, j, mkt = make("momentum_early")
    drv = Driver(eng)
    drv.send(mkt.create("GRAD"))
    crowd(drv, mkt, "GRAD", 10, 0.7)
    drv.advance(3)
    drv.send({"txType": "migrate", "mint": "GRAD", "signature": "s", "pool": "pump-amm"}, kind="m")
    drv.advance(3)
    assert j.trades[-1]["exit_reason"] == "αποφοίτηση"


# ── live: φρένα και ροή αποτελεσμάτων (χωρίς δίκτυο) ──
def test_live_flow_and_daily_loss_limit():
    eng, j, mkt = make("momentum_early", live_variant="momentum_early", trade_sol=0.05, daily_loss_limit_sol=0.01,
                       max_open_positions=2)
    assert "momentum_early@live" in eng.variants
    t = 1_000_000.0
    live_orders = []

    def step(ev):
        nonlocal t
        t += 1
        eng.on_tick(t)
        eng.on_trade(ev, t)
        live_orders.extend(eng.take_actions().live_orders)

    eng.on_create(mkt.create("L1"), t)
    for i in range(10):
        step(mkt.buy("L1", f"B{i}", 0.7))
    buys = [o for o in live_orders if o.kind == "buy"]
    assert len(buys) == 1 and buys[0].amount_sol == 0.05
    tokens = 0.0491 / mkt.price("L1")
    eng.on_live_result(buys[0], LiveResult(True, sol_delta=-0.0535, token_delta=tokens, signature="x"), t)
    pos = eng.positions[("momentum_early@live", "L1")]
    assert pos.live and pos.cost_sol == pytest.approx(0.0535)
    live_orders.clear()
    for i in range(10):                                  # κατάρρευση και πώληση του δημιουργού
        step(mkt.sell("L1", f"B{i}"))
    step(mkt.sell("L1", "DEV"))
    sells = [o for o in live_orders if o.kind == "sell"]
    assert len(sells) == 1 and sells[0].final            # μία εντολή: όσο εκκρεμεί, δεν στέλνει δεύτερη
    eng.on_live_result(sells[0], LiveResult(True, sol_delta=0.02, token_delta=-tokens), t)
    assert ("momentum_early@live", "L1") not in eng.positions
    assert eng.guard.pnl_today == pytest.approx(0.02 - 0.0535)
    ok, why = eng.guard.can_open(t, 0)
    assert not ok and why == "όριο ζημιάς ημέρας"


def test_live_errors_halt_buying():
    eng, j, mkt = make("momentum_early", live_variant="momentum_early", max_consecutive_errors=2)
    from memebot.engine import Order
    o = Order(1, "buy", "momentum_early@live", "Q", "Q", 0, 1e-8, amount_sol=0.05, live=True)
    eng.pending_live_buys[("momentum_early@live", "Q")] = o
    eng.on_live_result(o, LiveResult(False, error="RPC down", exception=True), 1)
    eng.on_live_result(o, LiveResult(False, error="RPC down", exception=True), 2)
    assert eng.guard.halted
    assert any("σταμάτησε" in n[0] for n in eng.take_actions().notes)


def test_live_restore_and_force_exit():
    eng, j, mkt = make("momentum_early", live_variant="momentum_early")
    eng.restore_live([{"mint": "R", "symbol": "R", "opened_t": 0, "entry_price": 1e-7, "tokens": 1e6,
                       "cost_sol": 0.05}], 100)
    assert eng.take_actions().subscribe == ["R"]
    assert eng.force_exit_live(101, "τέλος") == 1
    orders = eng.take_actions().live_orders
    assert orders[0].kind == "sell" and orders[0].slippage_pct > 30


# ── επανάληψη: ίδια αποτελέσματα με τη «ζωντανή» εκτέλεση ──
def test_backtest_replay_matches_live_paper(tmp_path):
    cfg = base_config()
    live_j = Journal(tmp_path, record_ticks=True)
    eng, mkt = Engine(cfg, live_j), Market()
    drv = Driver(eng, live_j)
    for k, m in enumerate(("P1", "P2", "P3")):
        drv.send(mkt.create(m, dev=f"D{k}"))
        crowd(drv, mkt, m, 12 + 6 * k, 0.8, every=1.5, prefix=f"{m}b")
        crowd(drv, mkt, m, 25, 0.9, every=2, prefix=f"{m}c")
        for i in range(20):
            drv.at(2, mkt.sell(m, f"{m}c{i}"))
    drv.advance(5)
    drv.send(mkt.buy("P3", "last", 0.1))
    eng.shutdown_paper(drv.t)
    live_j.close()
    rows, _ = replay(cfg, tmp_path / "ticks")
    key = lambda r: (r["variant"], r["mint"], r["exit_reason"], round(r["pnl_sol"], 9))
    assert len(live_j.trades) >= 4
    assert sorted(map(key, rows)) == sorted(map(key, live_j.trades))


def test_report_runs_and_judges_sample_size():
    rows = [{"closed_at": f"2026-10-1{i % 3} 10:00:00", "opened_at": "2026-10-10 09:00:00", "variant": "v",
             "mode": "paper", "status": "ok", "pnl_sol": 0.01 if i % 4 == 0 else -0.003, "pnl_pct": 10.0,
             "cost_sol": 0.1, "peak_multiple": 1.5, "hold_s": 60, "exit_reason": "stop-loss"} for i in range(40)]
    s = variant_stats(rows)
    assert s["trades"] == 40 and 0 < s["win_rate"] < 100
    text = build_report(rows)
    assert "λίγες συναλλαγές" in text


def test_sampling_and_data_budget():
    cfg = base_config("baseline_all")
    cfg["feed"]["sample_pct"] = 30
    eng, mkt = Engine(cfg, Journal(None)), Market()
    drv = Driver(eng)
    for i in range(1000):
        drv.send(mkt.create(f"S{i}", dev=f"D{i}"))
        eng.unwatch(eng.tokens[f"S{i}"], drv.t) if f"S{i}" in eng.tokens else None
    assert 250 < eng.stats["παρακολουθήθηκαν"] < 350
    assert Engine.sampled("abc", 30) == Engine.sampled("abc", 30)      # ίδιο σε κάθε επανάληψη

    cfg = base_config("baseline_all")
    cfg["feed"]["max_data_sol_per_day"] = 0.0001                       # = 100 συναλλαγές
    eng, mkt = Engine(cfg, Journal(None)), Market()
    drv = Driver(eng)
    drv.send(mkt.create("A"))
    crowd(drv, mkt, "A", 101, 0.1)
    drv.send(mkt.create("B", dev="D2"))
    assert "B" not in eng.tokens and eng.stats["απόρριψη: όριο κόστους δεδομένων ημέρας"] == 1


def test_report_in_euros_and_peak_capital():
    from memebot.report import peak_capital
    rows = [
        {"opened_at": "2026-10-11 10:00:00", "closed_at": "2026-10-11 10:05:00", "cost_sol": 0.1},
        {"opened_at": "2026-10-11 10:01:00", "closed_at": "2026-10-11 10:02:00", "cost_sol": 0.1},
        {"opened_at": "2026-10-11 10:02:00", "closed_at": "2026-10-11 10:03:00", "cost_sol": 0.1},
        {"opened_at": "2026-10-11 11:00:00", "closed_at": "2026-10-11 11:01:00", "cost_sol": 0.1, "status": "failed"},
    ]
    assert peak_capital(rows) == pytest.approx(0.2)      # το δεύτερο κλείνει τη στιγμή που ανοίγει το τρίτο
    full = [dict(r, variant="v", mode="paper", status=r.get("status", "ok"), pnl_sol=-0.01, pnl_pct=-10.0,
                 peak_multiple=1.1, hold_s=60, exit_reason="stop-loss") for r in rows]
    text = build_report(full, eur=100.0)
    assert "Ζημιά -0.0400 SOL ≈ -4.00 €" in text and "κεφάλαιο έως 0.20 SOL ≈ 20 €" in text
    assert "Σε απλά λόγια (τιμή SOL ≈ 100 €)" in text
    assert "≈" not in build_report(full, eur=None).split("## Λεπτομέρειες")[0]
