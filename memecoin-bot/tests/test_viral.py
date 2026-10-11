from memebot.backtest import replay
from memebot.engine import Engine
from memebot.journal import Journal
from memebot.narrative import Narrative, real_website, words, x_link
from memebot.trends import parse_coingecko, parse_rss

from sim import Driver, Market, base_config


def test_words_and_links():
    assert words("Trump Cat 🐱", "TCAT") == {"trump", "cat", "tcat"}
    assert words("The Official Coin", "SOL") == set()
    assert x_link("https://x.com/elonmusk/status/123") == ("elonmusk", True)
    assert x_link("https://twitter.com/FrogCoin") == ("frogcoin", False)
    assert real_website("https://frog.lol") and not real_website("https://x.com/frog")


class Tok:
    def __init__(self, mint, ws, creator="C", meta=None):
        self.mint, self.words, self.creator, self.meta = mint, set(ws), creator, meta or {}


def test_theme_leader_trend_influencer_and_creator():
    n = Narrative({"min_theme_copies": 3})
    for i in range(4):
        n.on_create(f"F{i}", f"C{i}", {"frog"}, 100 + i)
    n.on_buy("F2", 5.0)
    n.on_buy("F1", 1.0)
    assert n.theme("F2", {"frog"}) == ("frog", 3, True)
    assert n.theme("F1", {"frog"})[2] is False
    n.set_trending({"trump": "ειδήσεις"})
    s, why = n.score(Tok("F2", {"frog", "trumpfrog"}, meta={"twitter": "https://x.com/elonmusk/status/1",
                                                            "telegram": "https://t.me/frog"}))
    assert s == 30 + 25 + 15 + 5 and "trend:trump" in why and "αρχηγός" in why and "@elonmusk" in why
    n.on_create("G1", "PRO", {"gg"}, 200)
    n.on_migration("G1")
    assert n.score(Tok("G2", {"zz"}, creator="PRO"))[0] == 20
    n.on_create("late", "x", {"other"}, 100 + 3700)        # παλιά θέματα σβήνουν μετά από μία ώρα
    assert n.count.get("frog", 0) == 0 and n.hot_themes() == []


def test_trend_parsers():
    trends = "<rss><channel><item><title>taylor swift</title></item><item><title>the weather</title></item></channel></rss>"
    assert parse_rss(trends, proper_only=False) == {"taylor", "swift", "weather"}
    news = ("<rss><channel><item><title>Elon Musk unveils new rocket after delay - Reuters</title></item>"
            "</channel></rss>")
    assert parse_rss(news, proper_only=True) == {"elon", "musk"}
    assert parse_coingecko({"coins": [{"item": {"name": "Pudgy Penguins", "symbol": "PENGU"}}]}) == \
        {"pudgy", "penguins", "pengu"}
    assert parse_rss("not xml", True) == set()


def _viral_engine(journal=None):
    cfg = base_config("viral_hunter")
    cfg["metadata"]["fetch"] = True
    return Engine(cfg, journal or Journal(None)), Market()


def test_viral_hunter_buys_the_trending_coin_only():
    eng, mkt = _viral_engine()
    drv = Driver(eng)
    eng.on_trending({"pepe": "google trends"}, drv.t)
    for mint, name in (("HOT", "Pepe Cat"), ("COLD", "Random Thing")):
        drv.send(mkt.create(mint, name=name, symbol=mint, uri="https://ipfs/x", dev=f"D{mint}"))
        eng.on_meta(mint, {"twitter": "https://x.com/somecoin", "telegram": "", "website": ""}, drv.t)
    for i in range(4):
        drv.at(2, mkt.buy("HOT", f"h{i}", 0.5))
        drv.at(0, mkt.buy("COLD", f"c{i}", 0.5))
    drv.advance(3)
    held = {k[1] for k in eng.positions}
    assert held == {"HOT"}
    assert eng.positions[("viral_hunter", "HOT")].feats["viral_score"] == 35
    assert "trend:pepe" in eng.positions[("viral_hunter", "HOT")].feats["viral_why"]


def test_replay_includes_trends(tmp_path):
    j = Journal(tmp_path, record_ticks=True)
    eng, mkt = _viral_engine(j)
    drv = Driver(eng, j)
    j.tick("trend", {"words": {"pepe": "google trends"}}, drv.t)
    eng.on_trending({"pepe": "google trends"}, drv.t)
    drv.send(mkt.create("HOT", name="Pepe Cat", symbol="HOT", uri="https://ipfs/x"))
    meta = {"twitter": "https://x.com/somecoin", "telegram": "", "website": ""}
    j.tick("meta", {"mint": "HOT", "meta": meta}, drv.t)
    eng.on_meta("HOT", meta, drv.t)
    for i in range(4):
        drv.at(2, mkt.buy("HOT", f"h{i}", 0.5))
    for i in range(4):
        drv.at(2, mkt.sell("HOT", f"h{i}"))
    drv.at(2, mkt.sell("HOT", "DEV"))
    drv.advance(400)
    drv.send(mkt.create("END", name="End", symbol="END"))       # η καταγραφή φτάνει ως εδώ
    eng.shutdown_paper(drv.t)
    j.close()
    cfg = base_config("viral_hunter")
    cfg["metadata"]["fetch"] = True
    rows, _ = replay(cfg, tmp_path / "ticks")
    key = lambda r: (r["variant"], r["mint"], r["exit_reason"], r["viral_score"])
    assert [key(r) for r in rows] == [key(r) for r in j.trades] and j.trades


def test_ladder_takes_initials_out_then_locks_profit_then_trails():
    cfg = base_config("light")
    light = next(v for v in cfg["strategies"] if v["name"] == "light")
    light["exit"] = {"stop_loss_pct": 40, "take_profit_ladder": [[100, 0.5], [300, 0.5]], "trail_activate_pct": 80,
                     "trailing_stop_pct": 35, "time_stop_s": 900, "time_stop_min_gain_pct": 0, "max_hold_s": 7200,
                     "inactivity_s": 300, "exit_mcap_sol": 1e9, "exit_on_dev_sell": False}
    j = Journal(None)
    eng, mkt = Engine(cfg, j), Market()
    drv = Driver(eng)
    drv.send(mkt.create("MOON"))
    for i in range(6):
        drv.at(1, mkt.buy("MOON", f"a{i}", 0.6))
    drv.advance(3)
    pos = eng.positions[("light", "MOON")]
    start = pos.tokens
    k = 0
    while mkt.price("MOON") < pos.entry_price * 2.2:          # ράλι ως το 2×
        drv.at(1, mkt.buy("MOON", f"r{k}", 2.0)); k += 1
    drv.advance(3)
    assert pos.tp_level == 1 and abs(pos.tokens - start / 2) / start < 0.01
    assert pos.realized_sol > 0.9 * pos.cost_sol                # τα αρχικά βγήκαν
    while mkt.price("MOON") < pos.entry_price * 4.4:          # ως το 4×
        drv.at(1, mkt.buy("MOON", f"r{k}", 3.0)); k += 1
    drv.advance(3)
    assert pos.tp_level == 2 and abs(pos.tokens - start / 4) / start < 0.01
    for i in range(k):                                        # κατάρρευση → trailing stop για το υπόλοιπο
        drv.at(1, mkt.sell("MOON", f"r{i}"))
    drv.advance(3)
    row = j.trades[-1]
    assert row["exit_reason"] == "trailing stop" and row["sells"] == 3 and row["pnl_sol"] > 0


def test_report_splits_results_by_viral_score():
    from memebot.report import build_report
    rows = []
    for i in range(40):
        hot = i % 4 == 0
        rows.append({"closed_at": "2026-10-12 10:00:00", "opened_at": "2026-10-12 09:59:00", "variant": "baseline_all",
                     "mode": "paper", "status": "ok", "cost_sol": 0.1, "hold_s": 60, "exit_reason": "stop-loss",
                     "pnl_sol": 0.05 if hot else -0.005, "pnl_pct": 50.0 if hot else -5.0,
                     "peak_multiple": 5.5 if hot else 1.1, "viral_score": 45 if hot else 0})
    text = build_report(rows)
    assert "Βοηθάει το viral score;" in text
    assert "| 45+ | 10 | +50.0% | 100% | 100% | 100% |" in text
    assert "| 0 | 30 | -5.0% | 0% | 0% | 0% |" in text
